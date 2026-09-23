from datetime import timedelta
from decimal import Decimal

from django.conf import settings
from django.db import models
from django.urls import reverse
from django.utils import timezone


class Autor(models.Model):
    nome = models.CharField(max_length=150)
    nacionalidade = models.CharField(max_length=80, blank=True)
    data_nascimento = models.DateField('data de nascimento', null=True, blank=True)

    class Meta:
        ordering = ['nome']
        verbose_name_plural = 'autores'

    def __str__(self):
        return self.nome


class Livro(models.Model):
    titulo = models.CharField('título', max_length=200)
    autores = models.ManyToManyField(Autor, related_name='livros')
    isbn = models.CharField('ISBN', max_length=17, unique=True)
    editora = models.CharField(max_length=100, blank=True)
    ano_publicacao = models.PositiveIntegerField('ano de publicação')
    sinopse = models.TextField(blank=True)

    class Meta:
        ordering = ['titulo']

    def __str__(self):
        return self.titulo

    def get_absolute_url(self):
        return reverse('livro_detalhe', args=[self.pk])

    def nomes_autores(self):
        return ', '.join(autor.nome for autor in self.autores.all())

    def exemplares_disponiveis(self):
        """Exemplares ativos e sem empréstimo em aberto."""
        return self.exemplares.filter(ativo=True).exclude(
            emprestimos__data_devolucao__isnull=True,
        )

    def reservas_ativas(self):
        """A fila de reserva: aguardando + separadas para retirada, por ordem de chegada."""
        return self.reservas.filter(
            status__in=[Reserva.AGUARDANDO, Reserva.DISPONIVEL],
        ).order_by('data_reserva', 'pk')

    def quantidade_livre(self):
        """Exemplares disponíveis que NÃO estão separados para alguém da fila."""
        separados = self.reservas.filter(status=Reserva.DISPONIVEL).count()
        return max(self.exemplares_disponiveis().count() - separados, 0)
