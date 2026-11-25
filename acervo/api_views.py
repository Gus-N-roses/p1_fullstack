from contextlib import contextmanager

from django.db.models import ProtectedError
from rest_framework import generics, serializers
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from . import regras
from .models import Autor, Emprestimo, Exemplar, Livro, Membro, Reserva
from .permissoes import AdminOuSomenteLeitura
from .serializers import (
    AutorSerializer, DevolucaoSerializer, EmprestimoSerializer, ExemplarSerializer, LivroSerializer,
    MembroSerializer, ReservaSerializer,
)
from .views import org_atual


@contextmanager
def regras_como_400():
    """Uma recusa de regras.py vira resposta 400 em JSON."""
    try:
        yield
    except regras.RegraNegocioErro as erro:
        raise serializers.ValidationError({'detail': str(erro)})


class DaOrganizacaoMixin:
    """Restringe consultas e gravações à organização do usuário logado."""

    def get_queryset(self):
        return super().get_queryset().filter(organizacao=org_atual(self.request))

    def get_serializer_context(self):
        return {**super().get_serializer_context(), 'organizacao': org_atual(self.request)}

    def perform_create(self, serializer):
        serializer.save(organizacao=org_atual(self.request))

    def perform_destroy(self, instance):
        try:
            instance.delete()
        except ProtectedError:
            raise serializers.ValidationError(
                {'detail': 'Não é possível excluir: há empréstimos registrados.'},
            )


class CatalogoMixin(DaOrganizacaoMixin):
    """Autores, livros e exemplares: o operador só consulta."""
    permission_classes = [IsAuthenticated, AdminOuSomenteLeitura]


# Catálogo

class AutorListCreate(CatalogoMixin, generics.ListCreateAPIView):
    queryset = Autor.objects.all()
    serializer_class = AutorSerializer


class AutorDetail(CatalogoMixin, generics.RetrieveUpdateDestroyAPIView):
    queryset = Autor.objects.all()
    serializer_class = AutorSerializer


class LivroListCreate(CatalogoMixin, generics.ListCreateAPIView):
    queryset = Livro.objects.prefetch_related('autores')
    serializer_class = LivroSerializer


class LivroDetail(CatalogoMixin, generics.RetrieveUpdateDestroyAPIView):
    queryset = Livro.objects.prefetch_related('autores')
    serializer_class = LivroSerializer


class ExemplarListCreate(CatalogoMixin, generics.ListCreateAPIView):
    queryset = Exemplar.objects.select_related('livro')
    serializer_class = ExemplarSerializer


class ExemplarDetail(CatalogoMixin, generics.RetrieveUpdateDestroyAPIView):
    queryset = Exemplar.objects.select_related('livro')
    serializer_class = ExemplarSerializer


# Balcão

class MembroListCreate(DaOrganizacaoMixin, generics.ListCreateAPIView):
    queryset = Membro.objects.all()
    serializer_class = MembroSerializer


class MembroDetail(DaOrganizacaoMixin, generics.RetrieveUpdateDestroyAPIView):
    queryset = Membro.objects.all()
    serializer_class = MembroSerializer


class EmprestimoListCreate(DaOrganizacaoMixin, generics.ListCreateAPIView):
    queryset = Emprestimo.objects.all()
    serializer_class = EmprestimoSerializer

    def perform_create(self, serializer):
        # Não usa serializer.save(): quem cria é a regra (multa, atraso, limite e fila)
        dados = serializer.validated_data
        with regras_como_400():
            serializer.instance = regras.realizar_emprestimo(
                dados['membro'], dados['exemplar'], dados.get('data_prevista_devolucao'),
            )


class EmprestimoDetail(DaOrganizacaoMixin, generics.RetrieveAPIView):
    queryset = Emprestimo.objects.all()
    serializer_class = EmprestimoSerializer


class ReservaListCreate(DaOrganizacaoMixin, generics.ListCreateAPIView):
    queryset = Reserva.objects.all()
    serializer_class = ReservaSerializer

    def get_queryset(self):
        regras.expirar_reservas_vencidas(org_atual(self.request))
        return super().get_queryset()

    def perform_create(self, serializer):
        dados = serializer.validated_data
        with regras_como_400():
            serializer.instance = regras.criar_reserva(dados['membro'], dados['livro'])


class ReservaDetail(DaOrganizacaoMixin, generics.RetrieveAPIView):
    queryset = Reserva.objects.all()
    serializer_class = ReservaSerializer


# Ações (POST em /recurso/<id>/acao/)

class AcaoView(DaOrganizacaoMixin, generics.GenericAPIView):
    serializer_class = serializers.Serializer  # sem dados de entrada
    serializer_saida = None

    def post(self, request, pk):
        objeto = self.get_object()
        entrada = self.get_serializer(data=request.data)
        entrada.is_valid(raise_exception=True)
        with regras_como_400():
            objeto = self.executar(objeto, entrada.validated_data)
        return Response(self.serializer_saida(objeto, context=self.get_serializer_context()).data)


class DevolverEmprestimo(AcaoView):
    queryset = Emprestimo.objects.all()
    serializer_class = DevolucaoSerializer
    serializer_saida = EmprestimoSerializer

    def executar(self, emprestimo, dados):
        return regras.registrar_devolucao(emprestimo, dados.get('data_devolucao'))


class PagarMulta(AcaoView):
    queryset = Emprestimo.objects.all()
    serializer_saida = EmprestimoSerializer

    def executar(self, emprestimo, dados):
        return regras.pagar_multa(emprestimo)


class CancelarReserva(AcaoView):
    queryset = Reserva.objects.all()
    serializer_saida = ReservaSerializer

    def executar(self, reserva, dados):
        return regras.cancelar_reserva(reserva)
