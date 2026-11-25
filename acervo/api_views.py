from django.db.models import ProtectedError
from rest_framework import generics, serializers
from rest_framework.permissions import IsAuthenticated

from .models import Livro
from .permissoes import AdminOuSomenteLeitura
from .serializers import LivroSerializer
from .views import org_atual


class DaOrganizacaoMixin:
    """Restringe consultas e gravações à organização do usuário logado."""

    def get_queryset(self):
        return super().get_queryset().filter(organizacao=org_atual(self.request))

    def get_serializer_context(self):
        return {**super().get_serializer_context(), 'organizacao': org_atual(self.request)}

    def perform_create(self, serializer):
        serializer.save(organizacao=org_atual(self.request))


class LivroListCreate(DaOrganizacaoMixin, generics.ListCreateAPIView):
    queryset = Livro.objects.prefetch_related('autores')
    serializer_class = LivroSerializer
    permission_classes = [IsAuthenticated, AdminOuSomenteLeitura]


class LivroDetail(DaOrganizacaoMixin, generics.RetrieveUpdateDestroyAPIView):
    queryset = Livro.objects.prefetch_related('autores')
    serializer_class = LivroSerializer
    permission_classes = [IsAuthenticated, AdminOuSomenteLeitura]

    def perform_destroy(self, instance):
        try:
            instance.delete()
        except ProtectedError:
            raise serializers.ValidationError(
                {'detail': 'Não é possível excluir o livro: há empréstimos registrados.'},
            )
