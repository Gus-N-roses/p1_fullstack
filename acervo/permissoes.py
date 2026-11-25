"""O que cada papel pode fazer, nas telas e na API.

O operador atende o balcão (empréstimos, devoluções, reservas e membros) e só
consulta o catálogo. Cadastrar, editar e excluir autores, livros e exemplares é
do administrador.
"""
from functools import wraps

from django.core.exceptions import PermissionDenied
from rest_framework import permissions


def eh_admin(usuario):
    perfil = getattr(usuario, 'perfil', None)
    return perfil is not None and perfil.eh_admin


def somente_admin(view):
    @wraps(view)
    def protegida(request, *args, **kwargs):
        if not eh_admin(request.user):
            raise PermissionDenied('Apenas o administrador pode alterar o catálogo.')
        return view(request, *args, **kwargs)
    return protegida


class AdminOuSomenteLeitura(permissions.BasePermission):
    message = 'Apenas o administrador pode alterar o catálogo.'

    def has_permission(self, request, view):
        return request.method in permissions.SAFE_METHODS or eh_admin(request.user)
