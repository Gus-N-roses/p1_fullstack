from contextlib import contextmanager

from django.db.models import ProtectedError
from rest_framework import generics, serializers
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from . import metricas, regras
from .forms import PeriodoForm
from .models import Autor, Emprestimo, Exemplar, Livro, Membro, Reserva
from .permissoes import AdminOuSomenteLeitura, eh_admin
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
    queryset = Exemplar.objects.com_situacao()
    serializer_class = ExemplarSerializer


class ExemplarDetail(CatalogoMixin, generics.RetrieveUpdateDestroyAPIView):
    queryset = Exemplar.objects.com_situacao()
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


# Dashboard

class DashboardApi(APIView):
    """As mesmas métricas da tela. Período opcional: ?de=AAAA-MM-DD&ate=AAAA-MM-DD."""

    def get(self, request):
        organizacao = org_atual(request)
        periodo = metricas.periodo_padrao()
        if 'de' in request.query_params or 'ate' in request.query_params:
            form = PeriodoForm(request.query_params)
            # Na API, data inválida é erro de quem chamou: nada de trocar o período em silêncio
            if not form.is_valid():
                raise serializers.ValidationError(form.errors)
            periodo = form.cleaned_data

        dados = metricas.do_periodo(organizacao, periodo['de'], periodo['ate'])
        resposta = {
            'periodo': periodo,
            'emprestimos': dados['emprestimos'],
            'abertos': dados['abertos'],
            'leitores': dados['leitores'],
            'devolucoes': dados['devolucoes'],
            'multas_geradas': str(dados['multas_geradas']),
            'multas_pendentes': str(dados['multas_pendentes']),
            'livros': [
                {'id': item['exemplar__livro'], 'titulo': item['exemplar__livro__titulo'], 'total': item['total']}
                for item in dados['livros']
            ],
            'membros': [
                {'id': item['membro'], 'nome': item['membro__nome'], 'total': item['total']}
                for item in dados['membros']
            ],
            'reservas_por_status': dados['reservas_por_status'],
        }
        # Mesma regra da tela: o operador não recebe a série
        if eh_admin(request.user):
            resposta['por_mes'] = dados['grafico_mensal']
        return Response(resposta)
