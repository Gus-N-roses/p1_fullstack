"""Métricas do dashboard, calculadas pelo ORM e sempre restritas a uma organização.

Cada função responde a uma das perguntas listadas no README.
"""
from datetime import date
from decimal import Decimal

from django.db.models import Count, Q, Sum
from django.db.models.functions import TruncMonth
from django.utils import timezone

from .models import Emprestimo, Reserva

TAMANHO_RANKING = 5


def periodo_padrao():
    """Do dia 1º de cinco meses atrás até hoje: seis meses no gráfico, contando o atual."""
    hoje = timezone.localdate()
    ano, mes = divmod(hoje.year * 12 + hoje.month - 1 - 5, 12)
    return {'de': date(ano, mes + 1, 1), 'ate': hoje}


def kpis(feitos, devolvidos):
    """Totais do período: uma consulta para os empréstimos e outra para as devoluções."""
    totais = feitos.aggregate(
        emprestimos=Count('id'),
        abertos=Count('id', filter=Q(data_devolucao__isnull=True)),
        leitores=Count('membro', distinct=True),
    )
    # A multa nasce na devolução, por isso o período dela é o da data de devolução
    totais.update(devolvidos.aggregate(
        devolucoes=Count('id'),
        multas_geradas=Sum('multa', default=Decimal('0.00')),
        multas_pendentes=Sum('multa', filter=Q(multa_paga=False), default=Decimal('0.00')),
    ))
    return totais


def ranking(emprestimos, *campos):
    """Agrupa os empréstimos pelos campos e conta, do maior para o menor."""
    return list(
        emprestimos.values(*campos)
        .annotate(total=Count('id'))
        .order_by('-total', *campos[::-1])[:TAMANHO_RANKING]
    )


def serie_mensal(emprestimos):
    """Empréstimos por mês, em ordem cronológica."""
    return list(
        emprestimos.annotate(mes=TruncMonth('data_emprestimo'))
        .values('mes')
        .annotate(total=Count('id'))
        .order_by('mes')
    )


def dados_do_grafico(serie, inicio, fim):
    """A série pronta para o JavaScript: mês como "MM/AAAA" e meses sem movimento com zero."""
    if not serie:
        return []
    totais = {(linha['mes'].year, linha['mes'].month): linha['total'] for linha in serie}
    # Conta os meses em sequência (ano * 12 + mês) para atravessar a virada do ano
    primeiro = inicio.year * 12 + inicio.month - 1
    ultimo = fim.year * 12 + fim.month - 1
    meses = (divmod(numero, 12) for numero in range(primeiro, ultimo + 1))
    return [{'mes': f'{mes + 1:02d}/{ano}', 'total': totais.get((ano, mes + 1), 0)} for ano, mes in meses]


def distribuicao_reservas(reservas):
    """Quantas reservas há em cada status."""
    nomes = dict(Reserva.STATUS_CHOICES)
    linhas = reservas.values('status').annotate(total=Count('id')).order_by('-total', 'status')
    return [{'status': nomes[linha['status']], 'total': linha['total']} for linha in linhas]


def emprestimos_do_periodo(organizacao, inicio, fim):
    """Os empréstimos feitos no período: base do dashboard e do relatório em CSV."""
    return Emprestimo.objects.filter(organizacao=organizacao, data_emprestimo__range=(inicio, fim))


def do_periodo(organizacao, inicio, fim):
    periodo = (inicio, fim)
    emprestimos = Emprestimo.objects.filter(organizacao=organizacao)
    feitos = emprestimos_do_periodo(organizacao, inicio, fim)
    devolvidos = emprestimos.filter(data_devolucao__range=periodo)
    reservas = Reserva.objects.filter(organizacao=organizacao, data_reserva__date__range=periodo)

    por_mes = serie_mensal(feitos)

    return {
        **kpis(feitos, devolvidos),
        # Agrupa pela chave, e não só pelo nome: dois livros homônimos não se somam
        'livros': ranking(feitos, 'exemplar__livro', 'exemplar__livro__titulo'),
        'membros': ranking(feitos, 'membro', 'membro__nome'),
        'por_mes': por_mes,
        'grafico_mensal': dados_do_grafico(por_mes, inicio, fim),
        'reservas_por_status': distribuicao_reservas(reservas),
    }
