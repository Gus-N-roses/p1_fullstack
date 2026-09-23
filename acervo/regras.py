"""Regras de negócio da biblioteca: empréstimo, devolução, multa e fila de reserva.

As views chamam estas funções; toda a lógica fica aqui, não nos templates.
"""
from django.conf import settings
from django.db import transaction
from django.utils import timezone

from .models import Emprestimo, Exemplar, Membro


class RegraNegocioErro(Exception):
    """Operação recusada por uma regra da biblioteca (mensagem pronta para o usuário)."""


def verificar_membro_pode_emprestar(membro):
    if not membro.ativo:
        raise RegraNegocioErro(f'{membro} está inativo e não pode pegar livros.')
    if membro.total_multas_pendentes() > 0:
        raise RegraNegocioErro(
            f'{membro} tem R$ {membro.total_multas_pendentes()} em multas pendentes.'
        )
    if membro.tem_atraso():
        raise RegraNegocioErro(f'{membro} tem empréstimo em atraso. Devolva antes de pegar outro.')
    if membro.emprestimos_em_aberto().count() >= settings.LIMITE_EMPRESTIMOS_POR_MEMBRO:
        raise RegraNegocioErro(
            f'{membro} já atingiu o limite de {settings.LIMITE_EMPRESTIMOS_POR_MEMBRO} empréstimos.'
        )


@transaction.atomic
def realizar_emprestimo(membro, exemplar, data_prevista_devolucao=None):
    # Trava o exemplar para dois atendentes não emprestarem o mesmo ao mesmo tempo
    exemplar = Exemplar.objects.select_for_update().get(pk=exemplar.pk)
    membro = Membro.objects.get(pk=membro.pk)

    verificar_membro_pode_emprestar(membro)
    if not exemplar.esta_disponivel:
        raise RegraNegocioErro(f'O exemplar {exemplar.codigo} não está disponível.')

    emprestimo = Emprestimo(membro=membro, exemplar=exemplar)
    if data_prevista_devolucao:
        if data_prevista_devolucao < timezone.localdate():
            raise RegraNegocioErro('A devolução prevista não pode ser no passado.')
        emprestimo.data_prevista_devolucao = data_prevista_devolucao
    emprestimo.save()
    return emprestimo


@transaction.atomic
def registrar_devolucao(emprestimo, data_devolucao=None):
    emprestimo = Emprestimo.objects.select_for_update().get(pk=emprestimo.pk)
    if not emprestimo.em_aberto:
        raise RegraNegocioErro('Este empréstimo já foi devolvido.')

    data_devolucao = data_devolucao or timezone.localdate()
    if data_devolucao < emprestimo.data_emprestimo:
        raise RegraNegocioErro('A devolução não pode ser anterior ao empréstimo.')

    emprestimo.data_devolucao = data_devolucao
    emprestimo.multa = emprestimo.calcular_multa()
    emprestimo.multa_paga = emprestimo.multa == 0
    emprestimo.save()
    return emprestimo


def pagar_multa(emprestimo):
    if emprestimo.em_aberto:
        raise RegraNegocioErro('A multa só é cobrada após a devolução.')
    if emprestimo.multa_paga:
        raise RegraNegocioErro('Esta multa já foi paga.')
    emprestimo.multa_paga = True
    emprestimo.save(update_fields=['multa_paga'])
    return emprestimo
