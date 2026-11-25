"""Métricas do painel, calculadas pelo ORM e sempre restritas a uma organização."""
from decimal import Decimal

from django.db.models import Count, Q, Sum

from .models import Emprestimo

TAMANHO_RANKING = 5


def _ranking(emprestimos, *campos):
    """Agrupa os empréstimos pelos campos e conta, do maior para o menor."""
    return list(
        emprestimos.values(*campos)
        .annotate(total=Count('id'))
        .order_by('-total', *campos[::-1])[:TAMANHO_RANKING]
    )


def do_periodo(organizacao, inicio, fim):
    emprestimos = Emprestimo.objects.filter(organizacao=organizacao)
    feitos = emprestimos.filter(data_emprestimo__range=(inicio, fim))
    devolvidos = emprestimos.filter(data_devolucao__range=(inicio, fim))

    # A multa nasce na devolução, por isso o período dela é o da data de devolução
    multas = devolvidos.aggregate(
        geradas=Sum('multa'),
        pendentes=Sum('multa', filter=Q(multa_paga=False)),
    )
    multas = {chave: valor or Decimal('0.00') for chave, valor in multas.items()}

    return {
        'emprestimos': feitos.count(),
        'devolucoes': devolvidos.count(),
        'multas_geradas': multas['geradas'],
        'multas_pendentes': multas['pendentes'],
        # Agrupa pela chave, e não só pelo nome: dois livros homônimos não se somam
        'livros': _ranking(feitos, 'exemplar__livro', 'exemplar__livro__titulo'),
        'membros': _ranking(feitos, 'membro', 'membro__nome'),
    }
