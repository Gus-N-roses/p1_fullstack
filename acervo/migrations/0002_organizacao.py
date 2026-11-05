import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('acervo', '0001_initial'),
    ]

    operations = [
        migrations.CreateModel(
            name='Organizacao',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('nome', models.CharField(max_length=150)),
                ('slug', models.SlugField(max_length=150, unique=True)),
            ],
            options={
                'verbose_name_plural': 'organizações',
                'ordering': ['nome'],
            },
        ),
        migrations.AddField(
            model_name='autor',
            name='organizacao',
            field=models.ForeignKey(null=True, on_delete=django.db.models.deletion.CASCADE, to='acervo.organizacao'),
        ),
        migrations.AddField(
            model_name='livro',
            name='organizacao',
            field=models.ForeignKey(null=True, on_delete=django.db.models.deletion.CASCADE, to='acervo.organizacao'),
        ),
        migrations.AddField(
            model_name='exemplar',
            name='organizacao',
            field=models.ForeignKey(null=True, on_delete=django.db.models.deletion.CASCADE, to='acervo.organizacao'),
        ),
        migrations.AddField(
            model_name='membro',
            name='organizacao',
            field=models.ForeignKey(null=True, on_delete=django.db.models.deletion.CASCADE, to='acervo.organizacao'),
        ),
        migrations.AddField(
            model_name='emprestimo',
            name='organizacao',
            field=models.ForeignKey(null=True, on_delete=django.db.models.deletion.CASCADE, to='acervo.organizacao'),
        ),
        migrations.AddField(
            model_name='reserva',
            name='organizacao',
            field=models.ForeignKey(null=True, on_delete=django.db.models.deletion.CASCADE, to='acervo.organizacao'),
        ),
    ]
