from django.contrib.auth.models import User
from django.contrib.auth.password_validation import validate_password
from django.core.exceptions import ValidationError
from django.core.management import call_command
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from acervo.models import Organizacao, Perfil

# Pública de propósito: só serve para avaliar o projeto rodando na própria máquina
SENHA_DEMO = 'biblioteca-demo-2026'

CONTAS = [
    ('admin_central', 'biblioteca-central', Perfil.ADMIN),
    ('operador_central', 'biblioteca-central', Perfil.OPERADOR),
    ('admin_norte', 'biblioteca-norte', Perfil.ADMIN),
    ('operador_norte', 'biblioteca-norte', Perfil.OPERADOR),
]


class Command(BaseCommand):
    help = 'Deixa o sistema pronto para avaliação: contas dos dois papéis e dados nas duas bibliotecas.'

    def add_arguments(self, parser):
        parser.add_argument('--senha', default=SENHA_DEMO, help=f'Senha das contas (padrão: {SENHA_DEMO}).')

    @transaction.atomic
    def handle(self, *args, **opcoes):
        senha = opcoes['senha']
        try:
            validate_password(senha)
        except ValidationError as erro:
            raise CommandError('Senha fraca: ' + ' '.join(erro.messages))

        for nome, slug, papel in CONTAS:
            organizacao = Organizacao.objects.get(slug=slug)
            usuario, _ = User.objects.get_or_create(username=nome)
            usuario.set_password(senha)
            usuario.is_active = True
            usuario.save()
            Perfil.objects.update_or_create(usuario=usuario, defaults={'organizacao': organizacao, 'papel': papel})

        for slug in ('biblioteca-central', 'biblioteca-norte'):
            call_command('popular_dados', organizacao=slug, stdout=self.stdout)

        self.stdout.write(self.style.SUCCESS('\nContas de demonstração (todas com a mesma senha):'))
        for nome, slug, papel in CONTAS:
            self.stdout.write(f'  {nome:<18} {papel:<9} {slug}')
        self.stdout.write(f'\nSenha: {senha}')
