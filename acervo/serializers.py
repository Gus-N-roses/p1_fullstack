from rest_framework import serializers
from rest_framework.validators import UniqueValidator

from .models import Autor, Livro
from .validadores import normalizar_isbn


class ISBNField(serializers.CharField):
    """Normaliza antes dos validadores, para a unicidade comparar o ISBN já sem hífens."""

    def to_internal_value(self, data):
        return normalizar_isbn(super().to_internal_value(data))


class LivroSerializer(serializers.ModelSerializer):
    isbn = ISBNField(
        max_length=17,
        validators=[UniqueValidator(queryset=Livro.objects.all(), message='Já existe um livro com este ISBN.')],
    )

    class Meta:
        model = Livro
        fields = ['id', 'titulo', 'autores', 'isbn', 'editora', 'ano_publicacao', 'sinopse']

    def get_fields(self):
        campos = super().get_fields()
        # Só aceita (e só oferece na Browsable API) autores da organização do usuário
        campos['autores'].child_relation.queryset = Autor.objects.filter(
            organizacao=self.context['organizacao'],
        )
        return campos
