"""Validações compartilhadas pelos formulários e pelos serializers da API."""
from django.core.exceptions import ValidationError


def normalizar_isbn(valor):
    """Guarda só dígitos (e X do ISBN-10), aceitando o usuário digitar com hífens."""
    isbn = valor.replace('-', '').replace(' ', '').upper()
    if len(isbn) not in (10, 13) or not isbn[:-1].isdigit():
        raise ValidationError('Informe um ISBN com 10 ou 13 dígitos.')
    return isbn


def normalizar_cpf(valor):
    """Aceita o CPF com ou sem pontuação e devolve no formato 000.000.000-00."""
    cpf = ''.join(c for c in valor if c.isdigit())
    if len(cpf) != 11:
        raise ValidationError('O CPF deve ter 11 dígitos.')
    return f'{cpf[:3]}.{cpf[3:6]}.{cpf[6:9]}-{cpf[9:]}'
