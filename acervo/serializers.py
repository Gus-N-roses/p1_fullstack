from rest_framework import serializers
from rest_framework.validators import UniqueValidator

from .models import Autor, Emprestimo, Exemplar, Livro, Membro, Reserva
from .validadores import normalizar_cpf, normalizar_isbn


class ISBNField(serializers.CharField):
    """Normaliza antes dos validadores, para a unicidade comparar o ISBN já sem hífens."""

    def to_internal_value(self, data):
        return normalizar_isbn(super().to_internal_value(data))


class CPFField(serializers.CharField):
    """Mesma ideia do ISBNField: compara o CPF já formatado."""

    def to_internal_value(self, data):
        return normalizar_cpf(super().to_internal_value(data))


class DaOrganizacaoSerializer(serializers.ModelSerializer):
    """Campos relacionados só aceitam registros da organização do usuário."""

    def get_fields(self):
        campos = super().get_fields()
        for campo in campos.values():
            relacao = getattr(campo, 'child_relation', campo)
            if getattr(relacao, 'queryset', None) is not None:
                relacao.queryset = relacao.queryset.filter(organizacao=self.context['organizacao'])
        return campos


class AutorSerializer(DaOrganizacaoSerializer):
    class Meta:
        model = Autor
        fields = ['id', 'nome', 'nacionalidade', 'data_nascimento']


class LivroSerializer(DaOrganizacaoSerializer):
    isbn = ISBNField(
        max_length=17,
        validators=[UniqueValidator(queryset=Livro.objects.all(), message='Já existe um livro com este ISBN.')],
    )

    class Meta:
        model = Livro
        fields = ['id', 'titulo', 'autores', 'isbn', 'editora', 'ano_publicacao', 'sinopse']


class ExemplarSerializer(DaOrganizacaoSerializer):
    situacao = serializers.CharField(read_only=True)

    class Meta:
        model = Exemplar
        fields = ['id', 'livro', 'codigo', 'data_aquisicao', 'ativo', 'situacao']


class MembroSerializer(DaOrganizacaoSerializer):
    cpf = CPFField(
        max_length=14,
        validators=[UniqueValidator(queryset=Membro.objects.all(), message='Já existe um membro com este CPF.')],
    )

    class Meta:
        model = Membro
        fields = ['id', 'nome', 'cpf', 'email', 'telefone', 'data_cadastro', 'ativo']
        read_only_fields = ['data_cadastro']


class EmprestimoSerializer(DaOrganizacaoSerializer):
    class Meta:
        model = Emprestimo
        fields = ['id', 'membro', 'exemplar', 'data_emprestimo', 'data_prevista_devolucao',
                  'data_devolucao', 'multa', 'multa_paga']
        read_only_fields = ['data_emprestimo', 'data_devolucao', 'multa', 'multa_paga']
        # A disponibilidade do exemplar é conferida em regras.py, com mensagem própria
        extra_kwargs = {'exemplar': {'validators': []}}


class DevolucaoSerializer(serializers.Serializer):
    data_devolucao = serializers.DateField(required=False, help_text='Em branco: hoje.')


class ReservaSerializer(DaOrganizacaoSerializer):
    class Meta:
        model = Reserva
        fields = ['id', 'livro', 'membro', 'data_reserva', 'status', 'data_limite_retirada']
        read_only_fields = ['data_reserva', 'status', 'data_limite_retirada']
