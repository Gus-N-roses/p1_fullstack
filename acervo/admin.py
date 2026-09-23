from django.contrib import admin

from .models import Autor, Emprestimo, Exemplar, Livro, Membro, Reserva


class ExemplarInline(admin.TabularInline):
    model = Exemplar
    extra = 1


@admin.register(Autor)
class AutorAdmin(admin.ModelAdmin):
    list_display = ['nome', 'nacionalidade', 'data_nascimento']
    search_fields = ['nome']


@admin.register(Livro)
class LivroAdmin(admin.ModelAdmin):
    list_display = ['titulo', 'isbn', 'editora', 'ano_publicacao']
    search_fields = ['titulo', 'isbn', 'autores__nome']
    filter_horizontal = ['autores']
    inlines = [ExemplarInline]


@admin.register(Exemplar)
class ExemplarAdmin(admin.ModelAdmin):
    list_display = ['codigo', 'livro', 'ativo', 'situacao']
    list_filter = ['ativo']
    search_fields = ['codigo', 'livro__titulo']


@admin.register(Membro)
class MembroAdmin(admin.ModelAdmin):
    list_display = ['nome', 'cpf', 'email', 'ativo']
    list_filter = ['ativo']
    search_fields = ['nome', 'cpf', 'email']


@admin.register(Emprestimo)
class EmprestimoAdmin(admin.ModelAdmin):
    list_display = ['exemplar', 'membro', 'data_emprestimo', 'data_prevista_devolucao',
                    'data_devolucao', 'multa', 'multa_paga']
    list_filter = ['multa_paga', 'data_devolucao']
    search_fields = ['membro__nome', 'exemplar__codigo', 'exemplar__livro__titulo']


@admin.register(Reserva)
class ReservaAdmin(admin.ModelAdmin):
    list_display = ['livro', 'membro', 'data_reserva', 'status', 'data_limite_retirada']
    list_filter = ['status']
    search_fields = ['livro__titulo', 'membro__nome']
