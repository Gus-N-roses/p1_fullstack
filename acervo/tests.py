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


class BuscaEFiltroLivrosTeste(BaseTeste):
    def setUp(self):
        super().setUp()
        # self.livro/self.exemplar (Dom Casmurro) ficam disponíveis.
        # Criamos um segundo livro e o deixamos totalmente emprestado.
        self.autor = Autor.objects.get()
        self.livro_emprestado = Livro.objects.create(
            titulo='Memórias Póstumas de Brás Cubas', isbn='9788535910664', ano_publicacao=1881,
        )
        self.livro_emprestado.autores.add(self.autor)
        exemplar_emprestado = Exemplar.objects.create(livro=self.livro_emprestado, codigo='MP-001')
        regras.realizar_emprestimo(self.ana, exemplar_emprestado)

    def test_busca_por_titulo_filtra_lista(self):
        resposta = self.client.get(reverse('lista_livros'), {'q': 'casmurro'})
        self.assertContains(resposta, self.livro.titulo)
        self.assertNotContains(resposta, self.livro_emprestado.titulo)

    def test_busca_por_autor_filtra_lista(self):
        resposta = self.client.get(reverse('lista_livros'), {'q': 'Machado de Assis'})
        self.assertContains(resposta, self.livro.titulo)
        self.assertContains(resposta, self.livro_emprestado.titulo)

    def test_busca_sem_resultado_mostra_mensagem(self):
        resposta = self.client.get(reverse('lista_livros'), {'q': 'livro que não existe'})
        self.assertEqual(resposta.status_code, 200)
        self.assertContains(resposta, 'Nenhum livro encontrado com esses filtros.')

    def test_filtro_status_disponivel(self):
        resposta = self.client.get(reverse('lista_livros'), {'status': 'disponivel'})
        self.assertContains(resposta, self.livro.titulo)
        self.assertNotContains(resposta, self.livro_emprestado.titulo)

    def test_filtro_status_emprestado(self):
        resposta = self.client.get(reverse('lista_livros'), {'status': 'emprestado'})
        self.assertContains(resposta, self.livro_emprestado.titulo)
        self.assertNotContains(resposta, self.livro.titulo)

    def test_busca_e_filtro_combinados(self):
        resposta = self.client.get(reverse('lista_livros'), {'q': 'machado', 'status': 'disponivel'})
        self.assertContains(resposta, self.livro.titulo)
        self.assertNotContains(resposta, self.livro_emprestado.titulo)

    def test_disponibilidade_considera_o_mesmo_exemplar_nas_duas_condicoes(self):
        """Um livro só conta como 'disponível' se o MESMO exemplar for ativo e estiver livre.

        Regressão para o erro clássico de "spanning multi-valued relationships" do
        Django: encadear dois .filter()/.exclude() separados sobre `exemplares` deixaria
        cada condição casar com um exemplar diferente do mesmo livro.
        """
        livro_misto = Livro.objects.create(titulo='Livro Misto', isbn='9780000000000', ano_publicacao=2000)
        livro_misto.autores.add(self.autor)
        exemplar_emprestado = Exemplar.objects.create(livro=livro_misto, codigo='LM-001', ativo=True)
        Exemplar.objects.create(livro=livro_misto, codigo='LM-002', ativo=False)  # inativo, nunca emprestado
        regras.realizar_emprestimo(self.bruno, exemplar_emprestado)

        resposta = self.client.get(reverse('lista_livros'), {'status': 'disponivel'})
        self.assertNotContains(resposta, 'Livro Misto')

        resposta = self.client.get(reverse('lista_livros'), {'status': 'emprestado'})
        self.assertContains(resposta, 'Livro Misto')

    def test_disponibilidade_conta_qualquer_exemplar_livre_do_livro(self):
        """Basta UM exemplar disponível para o livro contar como 'disponível', mesmo que
        outro exemplar do mesmo livro esteja emprestado.

        Este é o cenário que de fato separa a implementação correta (Q() combinado em
        uma única consulta) da ingênua (.filter().exclude() encadeados): um .exclude()
        aplicado depois de um .filter() na mesma relação descarta o livro inteiro se
        QUALQUER exemplar bater na condição do exclude — mesmo que outro exemplar do
        mesmo livro devesse tornar o livro disponível. Verificado manualmente no shell
        antes deste teste: a versão ingênua retorna 0 aqui; a correta retorna 1.
        """
        livro_parcial = Livro.objects.create(
            titulo='Livro Parcialmente Emprestado', isbn='9780000000001', ano_publicacao=2001,
        )
        livro_parcial.autores.add(self.autor)
        Exemplar.objects.create(livro=livro_parcial, codigo='LP-001', ativo=True)  # disponível
        exemplar_emprestado = Exemplar.objects.create(livro=livro_parcial, codigo='LP-002', ativo=True)
        regras.realizar_emprestimo(self.bruno, exemplar_emprestado)

        resposta = self.client.get(reverse('lista_livros'), {'status': 'disponivel'})
        self.assertContains(resposta, 'Livro Parcialmente Emprestado')

        resposta = self.client.get(reverse('lista_livros'), {'status': 'emprestado'})
        self.assertNotContains(resposta, 'Livro Parcialmente Emprestado')
