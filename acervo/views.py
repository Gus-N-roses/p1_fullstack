from django.contrib import messages
from django.db.models import Count, ProtectedError, Q
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone

from .forms import AutorForm, LivroForm
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

def _formulario(request, classe_form, titulo, destino, instancia=None, mensagem='Registro salvo.'):
    if request.method == 'POST':
        form = classe_form(request.POST, instance=instancia)
        if form.is_valid():
            objeto = form.save()
            messages.success(request, mensagem)
            return redirect(destino(objeto) if callable(destino) else destino)
    else:
        form = classe_form(instance=instancia)
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
