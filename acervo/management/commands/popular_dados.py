from datetime import timedelta

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.utils import timezone

from acervo import regras
from acervo.models import Autor, Emprestimo, Exemplar, Livro, Membro, Organizacao


class Command(BaseCommand):
    help = 'Cadastra autores, livros, exemplares, membros, empréstimos e reservas de exemplo.'

    def add_arguments(self, parser):
        parser.add_argument(
            '--organizacao', default='biblioteca-central',
            help='Slug da organização que receberá os dados (padrão: biblioteca-central).',
        )

    @transaction.atomic
    def handle(self, *args, **opcoes):
        try:
            org = Organizacao.objects.get(slug=opcoes['organizacao'])
        except Organizacao.DoesNotExist:
            raise CommandError(f'Não existe organização com o slug "{opcoes["organizacao"]}".')

        if Livro.objects.filter(organizacao=org).exists():
            self.stdout.write(self.style.WARNING(f'{org} já tem livros; nada foi feito.'))
            return

        hoje = timezone.localdate()
        machado = Autor.objects.create(organizacao=org, nome='Machado de Assis', nacionalidade='Brasileira')
        clarice = Autor.objects.create(organizacao=org, nome='Clarice Lispector', nacionalidade='Brasileira')
        orwell = Autor.objects.create(organizacao=org, nome='George Orwell', nacionalidade='Britânica')

        livros = {}
        for titulo, autor, isbn, ano, copias in [
            ('Dom Casmurro', machado, '9788535910663', 1899, 2),
            ('Memórias Póstumas de Brás Cubas', machado, '9788535910664', 1881, 1),
            ('A Hora da Estrela', clarice, '9788532508120', 1977, 1),
            ('1984', orwell, '9788535914849', 1949, 1),
        ]:
            livro = Livro.objects.create(organizacao=org, titulo=titulo, isbn=isbn, ano_publicacao=ano)
            livro.autores.add(autor)
            for numero in range(1, copias + 1):
                Exemplar.objects.create(organizacao=org, livro=livro, codigo=f'{isbn[-4:]}-{numero:02d}')
            livros[titulo] = livro

        ana = Membro.objects.create(organizacao=org, nome='Ana Souza', cpf='111.444.777-35', email='ana@exemplo.com')
        bruno = Membro.objects.create(organizacao=org, nome='Bruno Lima', cpf='222.555.888-46', email='bruno@exemplo.com')
        carla = Membro.objects.create(organizacao=org, nome='Carla Dias', cpf='333.666.999-57', email='carla@exemplo.com')

        # Empréstimo atrasado (gera multa acumulando)
        Emprestimo.objects.create(
            organizacao=org, membro=bruno, exemplar=livros['1984'].exemplares.first(),
            data_emprestimo=hoje - timedelta(days=20), data_prevista_devolucao=hoje - timedelta(days=6),
        )
        # Devolução antiga com multa pendente
        Emprestimo.objects.create(
            organizacao=org, membro=carla, exemplar=livros['Dom Casmurro'].exemplares.last(),
            data_emprestimo=hoje - timedelta(days=40), data_prevista_devolucao=hoje - timedelta(days=26),
            data_devolucao=hoje - timedelta(days=22), multa='8.00',
        )
        # Empréstimo no prazo + fila de reserva no livro que ficou sem exemplar
        regras.realizar_emprestimo(ana, livros['A Hora da Estrela'].exemplares.first())
        regras.criar_reserva(bruno, livros['A Hora da Estrela'])
        regras.criar_reserva(carla, livros['A Hora da Estrela'])

        self.stdout.write(self.style.SUCCESS('Dados de exemplo cadastrados.'))
