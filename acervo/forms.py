from django import forms

from .models import Autor, Emprestimo, Exemplar, Livro, Membro, Reserva
from .validadores import normalizar_cpf, normalizar_isbn


class DataInput(forms.DateInput):
    input_type = 'date'

    def __init__(self, **kwargs):
        super().__init__(format='%Y-%m-%d', **kwargs)


class AutorForm(forms.ModelForm):
    class Meta:
        model = Autor
        fields = ['nome', 'nacionalidade', 'data_nascimento']
        widgets = {'data_nascimento': DataInput()}

    def __init__(self, *args, organizacao=None, **kwargs):
        super().__init__(*args, **kwargs)


class LivroForm(forms.ModelForm):
    class Meta:
        model = Livro
        fields = ['titulo', 'autores', 'isbn', 'editora', 'ano_publicacao', 'sinopse']
        widgets = {
            'autores': forms.CheckboxSelectMultiple(),
            'sinopse': forms.Textarea(attrs={'rows': 4}),
        }

    def __init__(self, *args, organizacao=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['autores'].queryset = Autor.objects.filter(organizacao=organizacao)

    def clean_isbn(self):
        return normalizar_isbn(self.cleaned_data['isbn'])


class ExemplarForm(forms.ModelForm):
    class Meta:
        model = Exemplar
        fields = ['livro', 'codigo', 'data_aquisicao', 'ativo']
        widgets = {'data_aquisicao': DataInput()}

    def __init__(self, *args, organizacao=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['livro'].queryset = Livro.objects.filter(organizacao=organizacao)


class MembroForm(forms.ModelForm):
    class Meta:
        model = Membro
        fields = ['nome', 'cpf', 'email', 'telefone', 'ativo']

    def __init__(self, *args, organizacao=None, **kwargs):
        super().__init__(*args, **kwargs)

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


class ReservaForm(forms.ModelForm):
    class Meta:
        model = Reserva
        fields = ['livro', 'membro']

    def __init__(self, *args, organizacao=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['livro'].queryset = Livro.objects.filter(organizacao=organizacao)
        self.fields['membro'].queryset = Membro.objects.filter(organizacao=organizacao, ativo=True)
