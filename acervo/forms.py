from django import forms

from .models import Autor, Exemplar, Livro, Membro, Reserva


class DataInput(forms.DateInput):
    input_type = 'date'

    def __init__(self, **kwargs):
        super().__init__(format='%Y-%m-%d', **kwargs)


class AutorForm(forms.ModelForm):
    class Meta:
        model = Autor
        fields = ['nome', 'nacionalidade', 'data_nascimento']
        widgets = {'data_nascimento': DataInput()}


class LivroForm(forms.ModelForm):
    class Meta:
        model = Livro
        fields = ['titulo', 'autores', 'isbn', 'editora', 'ano_publicacao', 'sinopse']
        widgets = {
            'autores': forms.CheckboxSelectMultiple(),
            'sinopse': forms.Textarea(attrs={'rows': 4}),
        }

    def clean_isbn(self):
        # Guarda só dígitos (e X do ISBN-10), aceitando o usuário digitar com hífens
        isbn = self.cleaned_data['isbn'].replace('-', '').replace(' ', '').upper()
        if len(isbn) not in (10, 13) or not isbn[:-1].isdigit():
            raise forms.ValidationError('Informe um ISBN com 10 ou 13 dígitos.')
        return isbn


class ExemplarForm(forms.ModelForm):
    class Meta:
        model = Exemplar
        fields = ['livro', 'codigo', 'data_aquisicao', 'ativo']
        widgets = {'data_aquisicao': DataInput()}


class MembroForm(forms.ModelForm):
    class Meta:
        model = Membro
        fields = ['nome', 'cpf', 'email', 'telefone', 'ativo']

    def clean_cpf(self):
        cpf = ''.join(c for c in self.cleaned_data['cpf'] if c.isdigit())
        if len(cpf) != 11:
            raise forms.ValidationError('O CPF deve ter 11 dígitos.')
        return f'{cpf[:3]}.{cpf[3:6]}.{cpf[6:9]}-{cpf[9:]}'


class EmprestimoForm(forms.Form):
    membro = forms.ModelChoiceField(queryset=Membro.objects.filter(ativo=True))
    exemplar = forms.ModelChoiceField(
        queryset=Exemplar.objects.disponiveis().select_related('livro'),
        help_text='Somente exemplares disponíveis aparecem na lista.',
    )
    data_prevista_devolucao = forms.DateField(
        label='Devolução prevista', required=False, widget=DataInput(),
        help_text='Deixe em branco para usar o prazo padrão.',
    )


class DevolucaoForm(forms.Form):
    data_devolucao = forms.DateField(label='Data da devolução', widget=DataInput())


class ReservaForm(forms.ModelForm):
    class Meta:
        model = Reserva
        fields = ['livro', 'membro']

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['membro'].queryset = Membro.objects.filter(ativo=True)
