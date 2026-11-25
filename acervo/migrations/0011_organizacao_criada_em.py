import django.utils.timezone
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('acervo', '0010_protege_organizacao'),
    ]

    operations = [
        migrations.AddField(
            model_name='organizacao',
            name='criada_em',
            # As organizações que já existem recebem a data em que a migração rodar
            field=models.DateTimeField(auto_now_add=True, default=django.utils.timezone.now, verbose_name='criada em'),
            preserve_default=False,
        ),
    ]
