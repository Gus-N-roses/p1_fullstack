"""Regras de negócio da biblioteca: empréstimo, devolução, multa e fila de reserva.

As views chamam estas funções; toda a lógica fica aqui, não nos templates.
"""
from datetime import timedelta

from django.conf import settings
from django.db import transaction
from django.utils import timezone

from .models import Emprestimo, Exemplar, Membro, Reserva


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

    livro = exemplar.livro
    processar_fila(livro)
    reserva_do_membro = livro.reservas_ativas().filter(membro=membro).first()
    separada_para_ele = reserva_do_membro and reserva_do_membro.status == Reserva.DISPONIVEL
    if not separada_para_ele and livro.quantidade_livre() == 0:
        raise RegraNegocioErro(
            f'Os exemplares de "{livro}" estão separados para quem está na fila de reserva.'
        )

    emprestimo = Emprestimo(membro=membro, exemplar=exemplar)
    if data_prevista_devolucao:
        if data_prevista_devolucao < timezone.localdate():
            raise RegraNegocioErro('A devolução prevista não pode ser no passado.')
        emprestimo.data_prevista_devolucao = data_prevista_devolucao
    emprestimo.save()

    if reserva_do_membro:
        reserva_do_membro.status = Reserva.ATENDIDA
        reserva_do_membro.save(update_fields=['status'])
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

    # O exemplar voltou: passa a vez para o próximo da fila de reserva
    processar_fila(emprestimo.exemplar.livro)
    return emprestimo


def pagar_multa(emprestimo):
    if emprestimo.em_aberto:
        raise RegraNegocioErro('A multa só é cobrada após a devolução.')
    if emprestimo.multa_paga:
        raise RegraNegocioErro('Esta multa já foi paga.')
    emprestimo.multa_paga = True
    emprestimo.save(update_fields=['multa_paga'])
    return emprestimo


# ---------------------------------------------------------------------------
# Fila de reserva
# ---------------------------------------------------------------------------

def processar_fila(livro):
    """Atualiza a fila de um livro.

    1. Reservas separadas cujo prazo de retirada venceu passam a "expirada".
    2. Cada exemplar livre é separado para o próximo "aguardando" da fila,
       que ganha PRAZO_RETIRADA_RESERVA_DIAS para retirar.
    """
    hoje = timezone.localdate()
    livro.reservas.filter(
        status=Reserva.DISPONIVEL, data_limite_retirada__lt=hoje,
    ).update(status=Reserva.EXPIRADA)

    vagas = livro.quantidade_livre()
    if vagas == 0:
        return []

    proximos = list(livro.reservas.filter(status=Reserva.AGUARDANDO).order_by('data_reserva', 'pk')[:vagas])
    data_limite = hoje + timedelta(days=settings.PRAZO_RETIRADA_RESERVA_DIAS)
    for reserva in proximos:
        reserva.status = Reserva.DISPONIVEL
        reserva.data_limite_retirada = data_limite
        reserva.save(update_fields=['status', 'data_limite_retirada'])
    return proximos


@transaction.atomic
def criar_reserva(membro, livro):
    if not membro.ativo:
        raise RegraNegocioErro(f'{membro} está inativo e não pode reservar.')
    if livro.reservas_ativas().filter(membro=membro).exists():
        raise RegraNegocioErro(f'{membro} já está na fila de "{livro}".')
    if membro.emprestimos_em_aberto().filter(exemplar__livro=livro).exists():
        raise RegraNegocioErro(f'{membro} já está com um exemplar de "{livro}".')
    if not livro.exemplares.filter(ativo=True).exists():
        raise RegraNegocioErro(f'"{livro}" não tem exemplares em circulação.')

    processar_fila(livro)
    if livro.quantidade_livre() > 0:
        raise RegraNegocioErro(
            f'Há exemplar de "{livro}" disponível agora — faça o empréstimo direto.'
        )
    return Reserva.objects.create(membro=membro, livro=livro)


@transaction.atomic
def cancelar_reserva(reserva):
    if not reserva.ativa:
        raise RegraNegocioErro('Esta reserva não está mais ativa.')
    reserva.status = Reserva.CANCELADA
    reserva.save(update_fields=['status'])
    processar_fila(reserva.livro)
    return reserva
