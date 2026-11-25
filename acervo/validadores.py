"""Validações compartilhadas pelos formulários e pelos serializers da API."""
from django.core.exceptions import ValidationError


def normalizar_isbn(valor):
    """Guarda só dígitos (e X do ISBN-10), aceitando o usuário digitar com hífens."""
    isbn = valor.replace('-', '').replace(' ', '').upper()
    if len(isbn) not in (10, 13) or not isbn[:-1].isdigit():
        raise ValidationError('Informe um ISBN com 10 ou 13 dígitos.')
    return isbn
