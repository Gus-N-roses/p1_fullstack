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


class Exemplar(models.Model):
    livro = models.ForeignKey(Livro, on_delete=models.CASCADE, related_name='exemplares')
    codigo = models.CharField('código de tombo', max_length=30, unique=True)
    data_aquisicao = models.DateField('data de aquisição', default=timezone.localdate)
    ativo = models.BooleanField(
        'em circulação', default=True,
        help_text='Desmarque para exemplares perdidos, danificados ou em manutenção.',
    )

    class Meta:
        ordering = ['livro__titulo', 'codigo']
        verbose_name_plural = 'exemplares'

    def __str__(self):
        return f'{self.codigo} — {self.livro.titulo}'

    def emprestimo_atual(self):
        return self.emprestimos.filter(data_devolucao__isnull=True).first()

    @property
    def esta_disponivel(self):
        return self.ativo and self.emprestimo_atual() is None

    @property
    def situacao(self):
        if not self.ativo:
            return 'Fora de circulação'
        return 'Emprestado' if self.emprestimo_atual() else 'Disponível'


class Membro(models.Model):
    nome = models.CharField(max_length=150)
    cpf = models.CharField('CPF', max_length=14, unique=True)
    email = models.EmailField('e-mail', unique=True)
    telefone = models.CharField(max_length=20, blank=True)
    data_cadastro = models.DateField('data de cadastro', auto_now_add=True)
    ativo = models.BooleanField(default=True)

    class Meta:
        ordering = ['nome']

    def __str__(self):
        return self.nome

    def get_absolute_url(self):
        return reverse('membro_detalhe', args=[self.pk])

    def emprestimos_em_aberto(self):
        return self.emprestimos.filter(data_devolucao__isnull=True)

    def multas_pendentes(self):
        return self.emprestimos.filter(multa__gt=0, multa_paga=False, data_devolucao__isnull=False)

    def total_multas_pendentes(self):
        total = self.multas_pendentes().aggregate(total=models.Sum('multa'))['total']
        return total or Decimal('0.00')

    def tem_atraso(self):
        return self.emprestimos_em_aberto().filter(
            data_prevista_devolucao__lt=timezone.localdate(),
        ).exists()


def data_prevista_padrao():
    return timezone.localdate() + timedelta(days=settings.PRAZO_EMPRESTIMO_DIAS)


class Emprestimo(models.Model):
    exemplar = models.ForeignKey(Exemplar, on_delete=models.PROTECT, related_name='emprestimos')
    membro = models.ForeignKey(Membro, on_delete=models.PROTECT, related_name='emprestimos')
    data_emprestimo = models.DateField('data do empréstimo', default=timezone.localdate)
    data_prevista_devolucao = models.DateField('devolução prevista', default=data_prevista_padrao)
    data_devolucao = models.DateField('data da devolução', null=True, blank=True)
    multa = models.DecimalField(max_digits=8, decimal_places=2, default=Decimal('0.00'))
    multa_paga = models.BooleanField('multa paga', default=False)

    class Meta:
        ordering = ['-data_emprestimo', '-pk']
        verbose_name = 'empréstimo'
        constraints = [
            # Um exemplar não pode ter dois empréstimos em aberto ao mesmo tempo
            models.UniqueConstraint(
                fields=['exemplar'],
                condition=models.Q(data_devolucao__isnull=True),
                name='um_emprestimo_aberto_por_exemplar',
            ),
        ]

    def __str__(self):
        return f'{self.exemplar} → {self.membro}'

    @property
    def em_aberto(self):
        return self.data_devolucao is None

    def dias_atraso(self, data_referencia=None):
        """Dias de atraso até a devolução (ou até hoje, se ainda em aberto)."""
        data_final = self.data_devolucao or data_referencia or timezone.localdate()
        return max((data_final - self.data_prevista_devolucao).days, 0)

    @property
    def esta_atrasado(self):
        return self.dias_atraso() > 0

    def calcular_multa(self, data_referencia=None):
        return self.dias_atraso(data_referencia) * Decimal(settings.VALOR_MULTA_DIARIA)

    @property
    def multa_estimada(self):
        """Multa já registrada (devolvido) ou acumulada até hoje (em aberto)."""
        return self.calcular_multa() if self.em_aberto else self.multa


class Reserva(models.Model):
    AGUARDANDO = 'aguardando'
    DISPONIVEL = 'disponivel'
    ATENDIDA = 'atendida'
    CANCELADA = 'cancelada'
    EXPIRADA = 'expirada'
    STATUS_CHOICES = [
        (AGUARDANDO, 'Aguardando na fila'),
        (DISPONIVEL, 'Disponível para retirada'),
        (ATENDIDA, 'Atendida'),
        (CANCELADA, 'Cancelada'),
        (EXPIRADA, 'Expirada'),
    ]

    livro = models.ForeignKey(Livro, on_delete=models.CASCADE, related_name='reservas')
    membro = models.ForeignKey(Membro, on_delete=models.CASCADE, related_name='reservas')
    data_reserva = models.DateTimeField('data da reserva', default=timezone.now)
    status = models.CharField(max_length=12, choices=STATUS_CHOICES, default=AGUARDANDO)
    data_limite_retirada = models.DateField('retirar até', null=True, blank=True)

    class Meta:
        ordering = ['data_reserva', 'pk']

    def __str__(self):
        return f'{self.membro} aguarda "{self.livro}"'

    @property
    def ativa(self):
        return self.status in (self.AGUARDANDO, self.DISPONIVEL)

    def posicao_na_fila(self):
        if not self.ativa:
            return None
        return list(self.livro.reservas_ativas().values_list('pk', flat=True)).index(self.pk) + 1
