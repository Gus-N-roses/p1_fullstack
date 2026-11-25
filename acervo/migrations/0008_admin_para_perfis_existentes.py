from django.db import migrations


def promover_perfis_existentes(apps, schema_editor):
    # Quem já tinha perfil antes dos papéis podia fazer tudo: continua podendo.
    Perfil = apps.get_model('acervo', 'Perfil')
    Perfil.objects.update(papel='admin')


class Migration(migrations.Migration):

    dependencies = [
        ('acervo', '0007_perfil_papel'),
    ]

    operations = [
        migrations.RunPython(promover_perfis_existentes, migrations.RunPython.noop),
    ]
