from django.contrib import messages
from django.db.models import Count, ProtectedError, Q
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_POST
from django.utils import timezone

from . import regras
from .forms import (
    AutorForm, DevolucaoForm, EmprestimoForm, ExemplarForm, LivroForm, MembroForm, ReservaForm,
)
from .models import Autor, Emprestimo, Exemplar, Livro, Membro, Reserva


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


# ---------------------------------------------------------------------------
# Auxiliares: o mesmo fluxo GET mostra / POST salva serve para vários cadastros
# ---------------------------------------------------------------------------

def _formulario(request, classe_form, titulo, destino, instancia=None, mensagem='Registro salvo.', inicial=None):
    if request.method == 'POST':
        form = classe_form(request.POST, instance=instancia)
        if form.is_valid():
            objeto = form.save()
            messages.success(request, mensagem)
            return redirect(destino(objeto) if callable(destino) else destino)
    else:
        form = classe_form(instance=instancia, initial=inicial)
    return render(request, 'acervo/form.html', {'form': form, 'titulo': titulo, 'voltar': request.GET.get('voltar')})


def _excluir(request, objeto, destino, cancelar):
    if request.method == 'POST':
        try:
            objeto.delete()
        except ProtectedError:
            messages.error(request, f'Não é possível excluir "{objeto}": há empréstimos registrados.')
            return redirect(cancelar)
        messages.success(request, f'"{objeto}" foi excluído.')
        return redirect(destino)
    return render(request, 'acervo/confirmar_exclusao.html', {'objeto': objeto, 'cancelar': cancelar})


# ---------------------------------------------------------------------------
# Autores
# ---------------------------------------------------------------------------

def lista_autores(request):
    autores = Autor.objects.annotate(quantidade_livros=Count('livros'))
    return render(request, 'acervo/autores/lista.html', {'autores': autores})


def novo_autor(request):
    return _formulario(request, AutorForm, 'Novo autor', 'lista_autores', mensagem='Autor cadastrado.')


def editar_autor(request, pk):
    autor = get_object_or_404(Autor, pk=pk)
    return _formulario(request, AutorForm, f'Editar {autor}', 'lista_autores', autor, 'Autor atualizado.')


def excluir_autor(request, pk):
    autor = get_object_or_404(Autor, pk=pk)
    return _excluir(request, autor, 'lista_autores', 'lista_autores')


# ---------------------------------------------------------------------------
# Livros
# ---------------------------------------------------------------------------

def lista_livros(request):
    busca = request.GET.get('q', '').strip()
    livros = Livro.objects.prefetch_related('autores', 'exemplares__emprestimos')
    if busca:
        livros = livros.filter(
            Q(titulo__icontains=busca) | Q(autores__nome__icontains=busca) | Q(isbn__icontains=busca)
        ).distinct()
    return render(request, 'acervo/livros/lista.html', {'livros': livros, 'busca': busca})


def livro_detalhe(request, pk):
    livro = get_object_or_404(Livro, pk=pk)
    contexto = {
        'livro': livro,
        'exemplares': livro.exemplares.all(),
        'fila': livro.reservas_ativas().select_related('membro'),
        'quantidade_livre': livro.quantidade_livre(),
    }
    return render(request, 'acervo/livros/detalhe.html', contexto)


def novo_livro(request):
    return _formulario(request, LivroForm, 'Novo livro', lambda livro: livro.get_absolute_url(),
                       mensagem='Livro cadastrado. Agora cadastre os exemplares.')


def editar_livro(request, pk):
    livro = get_object_or_404(Livro, pk=pk)
    return _formulario(request, LivroForm, f'Editar {livro}', lambda l: l.get_absolute_url(),
                       livro, 'Livro atualizado.')


def excluir_livro(request, pk):
    livro = get_object_or_404(Livro, pk=pk)
    return _excluir(request, livro, 'lista_livros', livro.get_absolute_url())


# ---------------------------------------------------------------------------
# Exemplares
# ---------------------------------------------------------------------------

def lista_exemplares(request):
    exemplares = Exemplar.objects.select_related('livro').prefetch_related('emprestimos')
    return render(request, 'acervo/exemplares/lista.html', {'exemplares': exemplares})


def novo_exemplar(request):
    # Vindo da página do livro (?livro=ID), o livro já aparece selecionado
    return _formulario(request, ExemplarForm, 'Novo exemplar', lambda e: e.livro.get_absolute_url(),
                       mensagem='Exemplar cadastrado.', inicial={'livro': request.GET.get('livro')})


def editar_exemplar(request, pk):
    exemplar = get_object_or_404(Exemplar, pk=pk)
    return _formulario(request, ExemplarForm, f'Editar exemplar {exemplar.codigo}',
                       lambda e: e.livro.get_absolute_url(), exemplar, 'Exemplar atualizado.')


def excluir_exemplar(request, pk):
    exemplar = get_object_or_404(Exemplar, pk=pk)
    return _excluir(request, exemplar, exemplar.livro.get_absolute_url(), 'lista_exemplares')


# ---------------------------------------------------------------------------
# Membros
# ---------------------------------------------------------------------------

def lista_membros(request):
    busca = request.GET.get('q', '').strip()
    membros = Membro.objects.all()
    if busca:
        membros = membros.filter(Q(nome__icontains=busca) | Q(cpf__icontains=busca) | Q(email__icontains=busca))
    return render(request, 'acervo/membros/lista.html', {'membros': membros, 'busca': busca})


def membro_detalhe(request, pk):
    membro = get_object_or_404(Membro, pk=pk)
    emprestimos = membro.emprestimos.select_related('exemplar__livro')
    contexto = {
        'membro': membro,
        'em_aberto': emprestimos.filter(data_devolucao__isnull=True),
        'historico': emprestimos.filter(data_devolucao__isnull=False),
        'total_multas': membro.total_multas_pendentes(),
        'reservas': membro.reservas.select_related('livro').order_by('-data_reserva'),
    }
    return render(request, 'acervo/membros/detalhe.html', contexto)


def novo_membro(request):
    return _formulario(request, MembroForm, 'Novo membro', lambda m: m.get_absolute_url(),
                       mensagem='Membro cadastrado.')


def editar_membro(request, pk):
    membro = get_object_or_404(Membro, pk=pk)
    return _formulario(request, MembroForm, f'Editar {membro}', lambda m: m.get_absolute_url(),
                       membro, 'Membro atualizado.')


def excluir_membro(request, pk):
    membro = get_object_or_404(Membro, pk=pk)
    return _excluir(request, membro, 'lista_membros', membro.get_absolute_url())


# ---------------------------------------------------------------------------
# Empréstimos
# ---------------------------------------------------------------------------

FILTROS_EMPRESTIMO = {
    'abertos': ('Em aberto', Q(data_devolucao__isnull=True)),
    'atrasados': ('Atrasados', Q(data_devolucao__isnull=True)),  # refinado na view (depende de hoje)
    'devolvidos': ('Devolvidos', Q(data_devolucao__isnull=False)),
    'multas': ('Multas pendentes', Q(data_devolucao__isnull=False, multa__gt=0, multa_paga=False)),
    'todos': ('Todos', Q()),
}


def lista_emprestimos(request):
    filtro = request.GET.get('filtro', 'abertos')
    if filtro not in FILTROS_EMPRESTIMO:
        filtro = 'abertos'
    emprestimos = Emprestimo.objects.filter(FILTROS_EMPRESTIMO[filtro][1]).select_related(
        'membro', 'exemplar__livro',
    )
    if filtro == 'atrasados':
        emprestimos = emprestimos.filter(data_prevista_devolucao__lt=timezone.localdate())
    filtros = [(chave, rotulo) for chave, (rotulo, _) in FILTROS_EMPRESTIMO.items()]
    return render(request, 'acervo/emprestimos/lista.html', {
        'emprestimos': emprestimos, 'filtro': filtro, 'filtros': filtros,
    })


def novo_emprestimo(request):
    if request.method == 'POST':
        form = EmprestimoForm(request.POST)
        if form.is_valid():
            try:
                emprestimo = regras.realizar_emprestimo(
                    form.cleaned_data['membro'],
                    form.cleaned_data['exemplar'],
                    form.cleaned_data['data_prevista_devolucao'],
                )
            except regras.RegraNegocioErro as erro:
                form.add_error(None, str(erro))
            else:
                messages.success(
                    request,
                    f'Empréstimo registrado. Devolver até {emprestimo.data_prevista_devolucao:%d/%m/%Y}.',
                )
                return redirect('lista_emprestimos')
    else:
        form = EmprestimoForm(initial={
            'membro': request.GET.get('membro'),
            'exemplar': request.GET.get('exemplar'),
        })
    return render(request, 'acervo/form.html', {'form': form, 'titulo': 'Novo empréstimo'})


def devolver_emprestimo(request, pk):
    emprestimo = get_object_or_404(Emprestimo.objects.select_related('membro', 'exemplar__livro'), pk=pk)
    if not emprestimo.em_aberto:
        messages.warning(request, 'Este empréstimo já foi devolvido.')
        return redirect('lista_emprestimos')

    if request.method == 'POST':
        form = DevolucaoForm(request.POST)
        if form.is_valid():
            try:
                emprestimo = regras.registrar_devolucao(emprestimo, form.cleaned_data['data_devolucao'])
            except regras.RegraNegocioErro as erro:
                form.add_error(None, str(erro))
            else:
                if emprestimo.multa:
                    messages.warning(
                        request,
                        f'Devolução com {emprestimo.dias_atraso()} dia(s) de atraso: multa de R$ {emprestimo.multa}.',
                    )
                else:
                    messages.success(request, 'Devolução registrada dentro do prazo.')
                separada = emprestimo.exemplar.livro.reservas.filter(status=Reserva.DISPONIVEL).first()
                if separada:
                    messages.info(request, f'"{separada.livro}" foi separado para {separada.membro} (fila de reserva).')
                return redirect('lista_emprestimos')
    else:
        form = DevolucaoForm(initial={'data_devolucao': timezone.localdate()})
    return render(request, 'acervo/emprestimos/devolver.html', {'form': form, 'emprestimo': emprestimo})


@require_POST
def pagar_multa(request, pk):
    emprestimo = get_object_or_404(Emprestimo, pk=pk)
    try:
        regras.pagar_multa(emprestimo)
    except regras.RegraNegocioErro as erro:
        messages.error(request, str(erro))
    else:
        messages.success(request, f'Multa de R$ {emprestimo.multa} quitada.')
    return redirect(request.POST.get('voltar') or 'lista_emprestimos')


# ---------------------------------------------------------------------------
# Reservas (fila)
# ---------------------------------------------------------------------------

def lista_reservas(request):
    # Vence as retiradas fora do prazo e passa a vez para o próximo da fila
    livros_vencidos = Livro.objects.filter(
        reservas__status=Reserva.DISPONIVEL,
        reservas__data_limite_retirada__lt=timezone.localdate(),
    ).distinct()
    for livro in livros_vencidos:
        regras.processar_fila(livro)

    mostrar_todas = request.GET.get('todas') == '1'
    reservas = Reserva.objects.select_related('livro', 'membro').order_by('livro__titulo', 'data_reserva', 'pk')
    if not mostrar_todas:
        reservas = reservas.filter(status__in=[Reserva.AGUARDANDO, Reserva.DISPONIVEL])
    return render(request, 'acervo/reservas/lista.html', {
        'reservas': reservas, 'mostrar_todas': mostrar_todas,
    })


def nova_reserva(request):
    if request.method == 'POST':
        form = ReservaForm(request.POST)
        if form.is_valid():
            try:
                reserva = regras.criar_reserva(form.cleaned_data['membro'], form.cleaned_data['livro'])
            except regras.RegraNegocioErro as erro:
                form.add_error(None, str(erro))
            else:
                messages.success(
                    request,
                    f'{reserva.membro} entrou na fila de "{reserva.livro}" na posição {reserva.posicao_na_fila()}.',
                )
                return redirect(reserva.livro.get_absolute_url())
    else:
        form = ReservaForm(initial={'livro': request.GET.get('livro'), 'membro': request.GET.get('membro')})
    return render(request, 'acervo/form.html', {'form': form, 'titulo': 'Nova reserva'})


@require_POST
def cancelar_reserva(request, pk):
    reserva = get_object_or_404(Reserva, pk=pk)
    try:
        regras.cancelar_reserva(reserva)
    except regras.RegraNegocioErro as erro:
        messages.error(request, str(erro))
    else:
        messages.success(request, f'Reserva de {reserva.membro} para "{reserva.livro}" cancelada.')
    return redirect(request.POST.get('voltar') or 'lista_reservas')
