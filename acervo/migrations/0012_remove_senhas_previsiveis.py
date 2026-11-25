from django.conf import settings
from django.contrib.auth.hashers import check_password
from django.db import migrations


def neutralizar_senhas_previsiveis(apps, schema_editor):
    """Versões antigas da 0006 criavam superusuários com a senha igual ao nome.

    Só mexe em quem ainda está com essa senha: o login é bloqueado até alguém definir
    outra (`changepassword`), e a conta deixa de ser superusuário. O Perfil não muda.
    """
    User = apps.get_model(settings.AUTH_USER_MODEL)
    for usuario in User.objects.filter(username__in=['admin_central', 'admin_norte']):
        if check_password(usuario.username, usuario.password):
            usuario.password = '!'  # marca do Django para "sem senha utilizável"
            usuario.is_superuser = False
            usuario.is_staff = False
            usuario.save(update_fields=['password', 'is_superuser', 'is_staff'])


class Migration(migrations.Migration):

    dependencies = [
        ('acervo', '0011_organizacao_criada_em'),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.RunPython(neutralizar_senhas_previsiveis, migrations.RunPython.noop),
    ]
