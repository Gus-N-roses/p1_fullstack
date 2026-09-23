from datetime import timedelta
from decimal import Decimal

from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from . import regras
from .models import Autor, Emprestimo, Exemplar, Livro, Membro, Reserva


@override_settings(PRAZO_EMPRESTIMO_DIAS=14, VALOR_MULTA_DIARIA='2.00',
                   LIMITE_EMPRESTIMOS_POR_MEMBRO=3, PRAZO_RETIRADA_RESERVA_DIAS=3)
class BaseTeste(TestCase):
    def setUp(self):
        self.hoje = timezone.localdate()
        autor = Autor.objects.create(nome='Machado de Assis')
        self.livro = Livro.objects.create(titulo='Dom Casmurro', isbn='9788535910663', ano_publicacao=1899)
        self.livro.autores.add(autor)
        self.exemplar = Exemplar.objects.create(livro=self.livro, codigo='DC-001')
        self.ana = Membro.objects.create(nome='Ana', cpf='111.111.111-11', email='ana@exemplo.com')
        self.bruno = Membro.objects.create(nome='Bruno', cpf='222.222.222-22', email='bruno@exemplo.com')
        self.carla = Membro.objects.create(nome='Carla', cpf='333.333.333-33', email='carla@exemplo.com')


class MultaTeste(BaseTeste):
    def test_devolucao_no_prazo_nao_gera_multa(self):
        emprestimo = regras.realizar_emprestimo(self.ana, self.exemplar)
        emprestimo = regras.registrar_devolucao(emprestimo, self.hoje)
        self.assertEqual(emprestimo.multa, Decimal('0.00'))
        self.assertTrue(emprestimo.multa_paga)

    def test_devolucao_atrasada_cobra_por_dia(self):
        emprestimo = Emprestimo.objects.create(
            membro=self.ana, exemplar=self.exemplar,
            data_emprestimo=self.hoje - timedelta(days=20),
            data_prevista_devolucao=self.hoje - timedelta(days=5),
        )
        emprestimo = regras.registrar_devolucao(emprestimo, self.hoje)
        self.assertEqual(emprestimo.dias_atraso(), 5)
        self.assertEqual(emprestimo.multa, Decimal('10.00'))
        self.assertFalse(emprestimo.multa_paga)

    def test_multa_pendente_bloqueia_novo_emprestimo(self):
        Emprestimo.objects.create(
            membro=self.ana, exemplar=self.exemplar,
            data_emprestimo=self.hoje - timedelta(days=20),
            data_prevista_devolucao=self.hoje - timedelta(days=2),
            data_devolucao=self.hoje, multa=Decimal('4.00'),
        )
        with self.assertRaisesMessage(regras.RegraNegocioErro, 'multas pendentes'):
            regras.realizar_emprestimo(self.ana, self.exemplar)

        regras.pagar_multa(self.ana.multas_pendentes().get())
        self.assertIsNotNone(regras.realizar_emprestimo(self.ana, self.exemplar).pk)

    def test_emprestimo_atrasado_bloqueia_novo_emprestimo(self):
        outro = Exemplar.objects.create(livro=self.livro, codigo='DC-002')
        Emprestimo.objects.create(
            membro=self.ana, exemplar=self.exemplar,
            data_emprestimo=self.hoje - timedelta(days=20),
            data_prevista_devolucao=self.hoje - timedelta(days=1),
        )
        with self.assertRaisesMessage(regras.RegraNegocioErro, 'atraso'):
            regras.realizar_emprestimo(self.ana, outro)


class EmprestimoTeste(BaseTeste):
    def test_exemplar_emprestado_nao_pode_ser_emprestado_de_novo(self):
        regras.realizar_emprestimo(self.ana, self.exemplar)
        with self.assertRaisesMessage(regras.RegraNegocioErro, 'não está disponível'):
            regras.realizar_emprestimo(self.bruno, self.exemplar)

    @override_settings(LIMITE_EMPRESTIMOS_POR_MEMBRO=1)
    def test_limite_de_emprestimos(self):
        outro = Exemplar.objects.create(livro=self.livro, codigo='DC-002')
        regras.realizar_emprestimo(self.ana, self.exemplar)
        with self.assertRaisesMessage(regras.RegraNegocioErro, 'limite'):
            regras.realizar_emprestimo(self.ana, outro)

    def test_membro_inativo_nao_empresta(self):
        self.ana.ativo = False
        self.ana.save()
        with self.assertRaisesMessage(regras.RegraNegocioErro, 'inativo'):
            regras.realizar_emprestimo(self.ana, self.exemplar)


class FilaReservaTeste(BaseTeste):
    def test_nao_reserva_quando_ha_exemplar_livre(self):
        with self.assertRaisesMessage(regras.RegraNegocioErro, 'disponível agora'):
            regras.criar_reserva(self.ana, self.livro)

    def test_fila_respeita_ordem_de_chegada(self):
        emprestimo = regras.realizar_emprestimo(self.ana, self.exemplar)
        reserva_bruno = regras.criar_reserva(self.bruno, self.livro)
        reserva_carla = regras.criar_reserva(self.carla, self.livro)
        self.assertEqual(reserva_bruno.posicao_na_fila(), 1)
        self.assertEqual(reserva_carla.posicao_na_fila(), 2)

        regras.registrar_devolucao(emprestimo)
        reserva_bruno.refresh_from_db()
        reserva_carla.refresh_from_db()
        self.assertEqual(reserva_bruno.status, Reserva.DISPONIVEL)
        self.assertEqual(reserva_bruno.data_limite_retirada, self.hoje + timedelta(days=3))
        self.assertEqual(reserva_carla.status, Reserva.AGUARDANDO)

        # O exemplar está separado para o Bruno: a Carla não pode furar a fila
        with self.assertRaisesMessage(regras.RegraNegocioErro, 'fila de reserva'):
            regras.realizar_emprestimo(self.carla, self.exemplar)

        regras.realizar_emprestimo(self.bruno, self.exemplar)
        reserva_bruno.refresh_from_db()
        self.assertEqual(reserva_bruno.status, Reserva.ATENDIDA)

    def test_reserva_expirada_passa_a_vez(self):
        emprestimo = regras.realizar_emprestimo(self.ana, self.exemplar)
        reserva_bruno = regras.criar_reserva(self.bruno, self.livro)
        reserva_carla = regras.criar_reserva(self.carla, self.livro)
        regras.registrar_devolucao(emprestimo)

        Reserva.objects.filter(pk=reserva_bruno.pk).update(data_limite_retirada=self.hoje - timedelta(days=1))
        regras.processar_fila(self.livro)

        reserva_bruno.refresh_from_db()
        reserva_carla.refresh_from_db()
        self.assertEqual(reserva_bruno.status, Reserva.EXPIRADA)
        self.assertEqual(reserva_carla.status, Reserva.DISPONIVEL)

    def test_cancelar_reserva_separada_libera_para_o_proximo(self):
        emprestimo = regras.realizar_emprestimo(self.ana, self.exemplar)
        reserva_bruno = regras.criar_reserva(self.bruno, self.livro)
        reserva_carla = regras.criar_reserva(self.carla, self.livro)
        regras.registrar_devolucao(emprestimo)

        regras.cancelar_reserva(Reserva.objects.get(pk=reserva_bruno.pk))
        reserva_carla.refresh_from_db()
        self.assertEqual(reserva_carla.status, Reserva.DISPONIVEL)

    def test_nao_entra_duas_vezes_na_fila(self):
        regras.realizar_emprestimo(self.ana, self.exemplar)
        regras.criar_reserva(self.bruno, self.livro)
        with self.assertRaisesMessage(regras.RegraNegocioErro, 'já está na fila'):
            regras.criar_reserva(self.bruno, self.livro)


class TelasTeste(BaseTeste):
    def test_paginas_principais_respondem(self):
        regras.realizar_emprestimo(self.ana, self.exemplar)
        regras.criar_reserva(self.bruno, self.livro)
        rotas = [
            reverse('inicio'), reverse('lista_livros'), reverse('livro_detalhe', args=[self.livro.pk]),
            reverse('lista_autores'), reverse('lista_exemplares'), reverse('lista_membros'),
            reverse('membro_detalhe', args=[self.ana.pk]), reverse('lista_emprestimos'),
            reverse('lista_emprestimos') + '?filtro=todos', reverse('lista_reservas'),
            reverse('novo_livro'), reverse('novo_emprestimo'), reverse('nova_reserva'),
        ]
        for rota in rotas:
            with self.subTest(rota=rota):
                self.assertEqual(self.client.get(rota).status_code, 200)

    def test_fluxo_de_emprestimo_e_devolucao_pela_tela(self):
        resposta = self.client.post(reverse('novo_emprestimo'), {
            'membro': self.ana.pk, 'exemplar': self.exemplar.pk,
        })
        self.assertRedirects(resposta, reverse('lista_emprestimos'))
        emprestimo = Emprestimo.objects.get()

        self.client.post(reverse('devolver_emprestimo', args=[emprestimo.pk]), {
            'data_devolucao': (emprestimo.data_prevista_devolucao + timedelta(days=3)).isoformat(),
        })
        emprestimo.refresh_from_db()
        self.assertEqual(emprestimo.multa, Decimal('6.00'))

    def test_cadastro_de_livro_normaliza_isbn(self):
        autor = Autor.objects.get()
        self.client.post(reverse('novo_livro'), {
            'titulo': 'Memórias Póstumas', 'autores': [autor.pk], 'isbn': '978-85-359-1066-4',
            'ano_publicacao': 1881,
        })
        self.assertTrue(Livro.objects.filter(isbn='9788535910664').exists())
