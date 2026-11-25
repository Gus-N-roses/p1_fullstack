from django import forms

from .models import Autor, Emprestimo, Exemplar, Livro, Membro, Reserva
from .validadores import normalizar_cpf, normalizar_isbn


class DataInput(forms.DateInput):
    input_type = 'date'

    def __init__(self, **kwargs):
        super().__init__(format='%Y-%m-%d', **kwargs)


class SemDuplicadoForm(forms.ModelForm):
    """Recusa valores já usados na organização.

    Como `organizacao` fica fora do formulário, o Django não confere sozinho a
    UniqueConstraint e o duplicado só estouraria no banco (IntegrityError).
    """
    campos_unicos = {}  # campo -> mensagem de erro

    def __init__(self, *args, organizacao=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.organizacao = organizacao

    def clean(self):
        dados = super().clean()
        outros = self._meta.model.objects.filter(organizacao=self.organizacao).exclude(pk=self.instance.pk)
        for campo, mensagem in self.campos_unicos.items():
            if dados.get(campo) and outros.filter(**{campo: dados[campo]}).exists():
                self.add_error(campo, mensagem)
        return dados


class AutorForm(forms.ModelForm):
    class Meta:
        model = Autor
        fields = ['nome', 'nacionalidade', 'data_nascimento']
        widgets = {'data_nascimento': DataInput()}

    def __init__(self, *args, organizacao=None, **kwargs):
        super().__init__(*args, **kwargs)


class LivroForm(SemDuplicadoForm):
    campos_unicos = {'isbn': 'Já existe um livro com este ISBN.'}

    class Meta:
        model = Livro
        fields = ['titulo', 'autores', 'isbn', 'editora', 'ano_publicacao', 'sinopse']
        widgets = {
            'autores': forms.CheckboxSelectMultiple(),
            'sinopse': forms.Textarea(attrs={'rows': 4}),
        }

    def __init__(self, *args, organizacao=None, **kwargs):
        super().__init__(*args, organizacao=organizacao, **kwargs)
        self.fields['autores'].queryset = Autor.objects.filter(organizacao=organizacao)

    def clean_isbn(self):
        return normalizar_isbn(self.cleaned_data['isbn'])


class ExemplarForm(SemDuplicadoForm):
    campos_unicos = {'codigo': 'Já existe um exemplar com este código de tombo.'}

    class Meta:
        model = Exemplar
        fields = ['livro', 'codigo', 'data_aquisicao', 'ativo']
        widgets = {'data_aquisicao': DataInput()}

    def __init__(self, *args, organizacao=None, **kwargs):
        super().__init__(*args, organizacao=organizacao, **kwargs)
        self.fields['livro'].queryset = Livro.objects.filter(organizacao=organizacao)


class MembroForm(SemDuplicadoForm):
    campos_unicos = {
        'cpf': 'Já existe um membro com este CPF.',
        'email': 'Já existe um membro com este e-mail.',
    }

    class Meta:
        model = Membro
        fields = ['nome', 'cpf', 'email', 'telefone', 'ativo']

    def __init__(self, *args, organizacao=None, **kwargs):
        super().__init__(*args, organizacao=organizacao, **kwargs)

    def clean_cpf(self):
        return normalizar_cpf(self.cleaned_data['cpf'])


class EmprestimoForm(forms.ModelForm):
    class Meta:
        model = Emprestimo
        fields = ['membro', 'exemplar', 'data_prevista_devolucao']
        widgets = {'data_prevista_devolucao': DataInput()}
        labels = {'data_prevista_devolucao': 'Devolução prevista'}
        help_texts = {
            'exemplar': 'Somente exemplares disponíveis aparecem na lista.',
            'data_prevista_devolucao': 'Deixe em branco para usar o prazo padrão.',
        }

    def __init__(self, *args, organizacao=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['membro'].queryset = Membro.objects.filter(organizacao=organizacao, ativo=True)
        self.fields['exemplar'].queryset = Exemplar.objects.disponiveis().filter(
            organizacao=organizacao,
        ).select_related('livro')
        self.fields['data_prevista_devolucao'].required = False

    def clean_membro(self):
        # Regra de negócio própria do domínio: quem está com um livro atrasado não
        # pode pegar outro. A definição de "atraso" mora só em Membro.tem_atraso() —
        # aqui só reaproveitamos, para não duplicar a regra em dois lugares.
        membro = self.cleaned_data.get('membro')
        if membro and membro.tem_atraso():
            raise forms.ValidationError(
                f'{membro} tem um empréstimo em atraso. É preciso devolvê-lo antes de '
                'pegar outro livro emprestado.'
            )
        return membro


class DevolucaoForm(forms.Form):
    data_devolucao = forms.DateField(label='Data da devolução', widget=DataInput())


class PeriodoForm(forms.Form):
    de = forms.DateField(label='De', widget=DataInput())
    ate = forms.DateField(label='Até', widget=DataInput())

    def clean(self):
        dados = super().clean()
        if dados.get('de') and dados.get('ate') and dados['de'] > dados['ate']:
            raise forms.ValidationError('A data inicial não pode ser depois da final.')
        return dados


class ReservaForm(forms.ModelForm):
    class Meta:
        model = Reserva
        fields = ['livro', 'membro']

    def __init__(self, *args, organizacao=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['livro'].queryset = Livro.objects.filter(organizacao=organizacao)
        self.fields['membro'].queryset = Membro.objects.filter(organizacao=organizacao, ativo=True)
