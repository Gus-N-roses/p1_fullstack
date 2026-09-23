from django.contrib import messages
from django.db.models import ProtectedError, Q
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone

from .models import Emprestimo, Exemplar, Livro, Membro, Reserva


def inicio(request):
    hoje = timezone.localdate()
    emprestimos_abertos = Emprestimo.objects.filter(data_devolucao__isnull=True)
    atrasados = emprestimos_abertos.filter(data_prevista_devolucao__lt=hoje).select_related(
        'membro', 'exemplar__livro',
    )
    contexto = {
        'total_livros': Livro.objects.count(),
        'total_exemplares': Exemplar.objects.filter(ativo=True).count(),
        'total_membros': Membro.objects.filter(ativo=True).count(),
        'total_emprestimos_abertos': emprestimos_abertos.count(),
        'atrasados': atrasados,
        'reservas_para_retirada': Reserva.objects.filter(status=Reserva.DISPONIVEL).select_related(
            'membro', 'livro',
        ),
    }
    return render(request, 'acervo/inicio.html', contexto)
