from django.db import migrations


def criar_organizacao_padrao(apps, schema_editor):
    Organizacao = apps.get_model('acervo', 'Organizacao')
    organizacao, _ = Organizacao.objects.get_or_create(
        slug='padrao', defaults={'nome': 'Organização padrão'},
    )

    for nome_model in ['Autor', 'Livro', 'Exemplar', 'Membro', 'Emprestimo', 'Reserva']:
        Model = apps.get_model('acervo', nome_model)
        Model.objects.filter(organizacao__isnull=True).update(organizacao=organizacao)


def reverter(apps, schema_editor):
    pass


class Migration(migrations.Migration):

    dependencies = [
        ('acervo', '0002_organizacao'),
    ]

    operations = [
        migrations.RunPython(criar_organizacao_padrao, reverter),
    ]
