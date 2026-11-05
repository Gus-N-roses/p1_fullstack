from django.conf import settings
from django.contrib.auth.hashers import make_password
from django.db import migrations


def criar_organizacoes_e_usuarios(apps, schema_editor):
    Organizacao = apps.get_model('acervo', 'Organizacao')
    Perfil = apps.get_model('acervo', 'Perfil')
    User = apps.get_model(settings.AUTH_USER_MODEL)

    biblioteca_central, _ = Organizacao.objects.get_or_create(
        slug='biblioteca-central', defaults={'nome': 'Biblioteca Central'},
    )
    biblioteca_norte, _ = Organizacao.objects.get_or_create(
        slug='biblioteca-norte', defaults={'nome': 'Biblioteca Norte'},
    )

    for username, organizacao in [
        ('admin_central', biblioteca_central),
        ('admin_norte', biblioteca_norte),
    ]:
        usuario, criado = User.objects.get_or_create(
            username=username,
            defaults={
                'is_staff': True,
                'is_superuser': True,
                'password': make_password(username),
            },
        )
        Perfil.objects.get_or_create(usuario=usuario, defaults={'organizacao': organizacao})


def reverter(apps, schema_editor):
    pass


class Migration(migrations.Migration):

    dependencies = [
        ('acervo', '0005_perfil'),
    ]

    operations = [
        migrations.RunPython(criar_organizacoes_e_usuarios, reverter),
    ]
