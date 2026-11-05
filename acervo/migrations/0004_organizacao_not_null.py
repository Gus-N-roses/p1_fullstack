import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('acervo', '0003_popula_organizacao'),
    ]

    operations = [
        migrations.AlterField(
            model_name='autor',
            name='organizacao',
            field=models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, to='acervo.organizacao'),
        ),
        migrations.AlterField(
            model_name='livro',
            name='organizacao',
            field=models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, to='acervo.organizacao'),
        ),
        migrations.AlterField(
            model_name='exemplar',
            name='organizacao',
            field=models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, to='acervo.organizacao'),
        ),
        migrations.AlterField(
            model_name='membro',
            name='organizacao',
            field=models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, to='acervo.organizacao'),
        ),
        migrations.AlterField(
            model_name='emprestimo',
            name='organizacao',
            field=models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, to='acervo.organizacao'),
        ),
        migrations.AlterField(
            model_name='reserva',
            name='organizacao',
            field=models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, to='acervo.organizacao'),
        ),
    ]
