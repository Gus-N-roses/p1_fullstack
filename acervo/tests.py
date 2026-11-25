import csv
from datetime import date, timedelta
from decimal import Decimal
from importlib import import_module
from io import StringIO

from django.apps import apps
from django.contrib.auth.hashers import make_password
from django.contrib.auth.models import User
from django.core.management import CommandError, call_command
from django.db import IntegrityError, connection, transaction
from django.db.models import Prefetch, ProtectedError
from django.test import TestCase, override_settings
from django.test.utils import CaptureQueriesContext
from django.urls import reverse
from django.utils import timezone

from . import regras, relatorios
from .models import Autor, Emprestimo, Exemplar, Livro, Membro, Organizacao, Perfil, Reserva


@override_settings(PRAZO_EMPRESTIMO_DIAS=14, VALOR_MULTA_DIARIA='2.00',
                   LIMITE_EMPRESTIMOS_POR_MEMBRO=3, PRAZO_RETIRADA_RESERVA_DIAS=3)
class BaseTeste(TestCase):
    def setUp(self):
        self.hoje = timezone.localdate()
        self.org = Organizacao.objects.create(nome='Biblioteca de Teste', slug='teste')
        self.usuario = User.objects.create_user('atendente')
        Perfil.objects.create(usuario=self.usuario, organizacao=self.org, papel=Perfil.ADMIN)
        self.client.force_login(self.usuario)
        autor = Autor.objects.create(organizacao=self.org, nome='Machado de Assis')
        self.livro = Livro.objects.create(organizacao=self.org, titulo='Dom Casmurro', isbn='9788535910663', ano_publicacao=1899)
        self.livro.autores.add(autor)
        self.exemplar = Exemplar.objects.create(organizacao=self.org, livro=self.livro, codigo='DC-001')
        self.ana = Membro.objects.create(organizacao=self.org, nome='Ana', cpf='111.111.111-11', email='ana@exemplo.com')
        self.bruno = Membro.objects.create(organizacao=self.org, nome='Bruno', cpf='222.222.222-22', email='bruno@exemplo.com')
        self.carla = Membro.objects.create(organizacao=self.org, nome='Carla', cpf='333.333.333-33', email='carla@exemplo.com')


class MultaTeste(BaseTeste):
    def test_devolucao_no_prazo_nao_gera_multa(self):
        emprestimo = regras.realizar_emprestimo(self.ana, self.exemplar)
        emprestimo = regras.registrar_devolucao(emprestimo, self.hoje)
        self.assertEqual(emprestimo.multa, Decimal('0.00'))
        self.assertTrue(emprestimo.multa_paga)

    def test_devolucao_atrasada_cobra_por_dia(self):
        emprestimo = Emprestimo.objects.create(
            organizacao=self.org, membro=self.ana, exemplar=self.exemplar,
            data_emprestimo=self.hoje - timedelta(days=20),
            data_prevista_devolucao=self.hoje - timedelta(days=5),
        )
        emprestimo = regras.registrar_devolucao(emprestimo, self.hoje)
        self.assertEqual(emprestimo.dias_atraso(), 5)
        self.assertEqual(emprestimo.multa, Decimal('10.00'))
        self.assertFalse(emprestimo.multa_paga)

    def test_multa_pendente_bloqueia_novo_emprestimo(self):
        Emprestimo.objects.create(
            organizacao=self.org, membro=self.ana, exemplar=self.exemplar,
            data_emprestimo=self.hoje - timedelta(days=20),
            data_prevista_devolucao=self.hoje - timedelta(days=2),
            data_devolucao=self.hoje, multa=Decimal('4.00'),
        )
        with self.assertRaisesMessage(regras.RegraNegocioErro, 'multas pendentes'):
            regras.realizar_emprestimo(self.ana, self.exemplar)

        regras.pagar_multa(self.ana.multas_pendentes().get())
        self.assertIsNotNone(regras.realizar_emprestimo(self.ana, self.exemplar).pk)

    def test_emprestimo_atrasado_bloqueia_novo_emprestimo(self):
        outro = Exemplar.objects.create(organizacao=self.org, livro=self.livro, codigo='DC-002')
        Emprestimo.objects.create(
            organizacao=self.org, membro=self.ana, exemplar=self.exemplar,
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
        outro = Exemplar.objects.create(organizacao=self.org, livro=self.livro, codigo='DC-002')
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
            reverse('inicio'), reverse('dashboard'), reverse('lista_livros'), reverse('livro_detalhe', args=[self.livro.pk]),
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
            organizacao=self.org, titulo='Memórias Póstumas de Brás Cubas', isbn='9788535910664', ano_publicacao=1881,
        )
        self.livro_emprestado.autores.add(self.autor)
        exemplar_emprestado = Exemplar.objects.create(organizacao=self.org, livro=self.livro_emprestado, codigo='MP-001')
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
        livro_misto = Livro.objects.create(organizacao=self.org, titulo='Livro Misto', isbn='9780000000000', ano_publicacao=2000)
        livro_misto.autores.add(self.autor)
        exemplar_emprestado = Exemplar.objects.create(organizacao=self.org, livro=livro_misto, codigo='LM-001', ativo=True)
        Exemplar.objects.create(organizacao=self.org, livro=livro_misto, codigo='LM-002', ativo=False)  # inativo, nunca emprestado
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
            organizacao=self.org, titulo='Livro Parcialmente Emprestado', isbn='9780000000001', ano_publicacao=2001,
        )
        livro_parcial.autores.add(self.autor)
        Exemplar.objects.create(organizacao=self.org, livro=livro_parcial, codigo='LP-001', ativo=True)  # disponível
        exemplar_emprestado = Exemplar.objects.create(organizacao=self.org, livro=livro_parcial, codigo='LP-002', ativo=True)
        regras.realizar_emprestimo(self.bruno, exemplar_emprestado)

        resposta = self.client.get(reverse('lista_livros'), {'status': 'disponivel'})
        self.assertContains(resposta, 'Livro Parcialmente Emprestado')

        resposta = self.client.get(reverse('lista_livros'), {'status': 'emprestado'})
        self.assertNotContains(resposta, 'Livro Parcialmente Emprestado')


class ValidacaoDeAtrasoNoFormularioTeste(BaseTeste):
    """Feature 2 do P1: validação customizada em EmprestimoForm.clean_membro()."""

    def test_membro_com_atraso_nao_consegue_pegar_outro_livro_pelo_formulario(self):
        Emprestimo.objects.create(
            organizacao=self.org, membro=self.ana, exemplar=self.exemplar,
            data_emprestimo=self.hoje - timedelta(days=20),
            data_prevista_devolucao=self.hoje - timedelta(days=1),
        )
        outro_livro = Livro.objects.create(organizacao=self.org, titulo='1984', isbn='9788535914849', ano_publicacao=1949)
        outro_exemplar = Exemplar.objects.create(organizacao=self.org, livro=outro_livro, codigo='1984-001')

        resposta = self.client.post(reverse('novo_emprestimo'), {
            'membro': self.ana.pk, 'exemplar': outro_exemplar.pk,
        })

        self.assertEqual(resposta.status_code, 200)  # form inválido: não redireciona
        self.assertContains(resposta, 'atraso')
        self.assertEqual(Emprestimo.objects.filter(membro=self.ana, exemplar=outro_exemplar).count(), 0)


class AcessoEIsolamentoTeste(BaseTeste):
    def setUp(self):
        super().setUp()
        outra = Organizacao.objects.create(nome='Outra Biblioteca', slug='outra')
        self.autor_de_fora = Autor.objects.create(organizacao=outra, nome='Autor de Fora')
        self.livro_de_fora = Livro.objects.create(
            organizacao=outra, titulo='Livro de Fora', isbn='9780000000099', ano_publicacao=2000,
        )

    def test_visitante_e_mandado_para_o_login(self):
        self.client.logout()
        resposta = self.client.get(reverse('inicio'))
        self.assertRedirects(resposta, f"{reverse('login')}?next={reverse('inicio')}")

    def test_login_leva_ao_inicio(self):
        self.client.logout()
        self.usuario.set_password('senha-de-teste')
        self.usuario.save()
        resposta = self.client.post(reverse('login'), {'username': 'atendente', 'password': 'senha-de-teste'})
        self.assertRedirects(resposta, reverse('inicio'))

    def test_usuario_sem_perfil_recebe_403(self):
        self.client.force_login(User.objects.create_user('sem_perfil'))
        resposta = self.client.get(reverse('inicio'))
        self.assertContains(resposta, 'nenhuma organização', status_code=403)

    def test_registro_de_outra_organizacao_nao_aparece(self):
        resposta = self.client.get(reverse('lista_livros'))
        self.assertNotContains(resposta, 'Livro de Fora')
        resposta = self.client.get(reverse('livro_detalhe', args=[self.livro_de_fora.pk]))
        self.assertEqual(resposta.status_code, 404)

    def test_formulario_de_livro_nao_aceita_autor_de_outra_organizacao(self):
        self.assertNotContains(self.client.get(reverse('novo_livro')), 'Autor de Fora')
        self.client.post(reverse('novo_livro'), {
            'titulo': 'Invasor', 'autores': [self.autor_de_fora.pk], 'isbn': '9780000000098',
            'ano_publicacao': 2000,
        })
        self.assertFalse(Livro.objects.filter(titulo='Invasor').exists())


class PopularDadosTeste(TestCase):
    def test_cadastra_tudo_na_organizacao_escolhida(self):
        call_command('popular_dados', organizacao='biblioteca-norte', stdout=StringIO())
        for model in (Autor, Livro, Exemplar, Membro, Emprestimo, Reserva):
            with self.subTest(model=model.__name__):
                self.assertTrue(model.objects.exists())
                self.assertFalse(model.objects.exclude(organizacao__slug='biblioteca-norte').exists())


class ApiLivrosTeste(BaseTeste):
    def setUp(self):
        super().setUp()
        self.autor = Autor.objects.get()
        outra = Organizacao.objects.create(nome='Outra Biblioteca', slug='outra')
        self.autor_de_fora = Autor.objects.create(organizacao=outra, nome='Autor de Fora')
        self.livro_de_fora = Livro.objects.create(
            organizacao=outra, titulo='Livro de Fora', isbn='9780000000099', ano_publicacao=2000,
        )
        self.lista = reverse('api_livros')

    def criar(self, **dados):
        corpo = {'titulo': 'Novo', 'autores': [self.autor.pk], 'isbn': '9780000000011', 'ano_publicacao': 2000}
        return self.client.post(self.lista, {**corpo, **dados}, content_type='application/json')

    def detalhe(self, livro):
        return reverse('api_livro', args=[livro.pk])

    def test_sem_login_responde_403(self):
        self.client.logout()
        self.assertEqual(self.client.get(self.lista).status_code, 403)
        self.assertEqual(self.criar().status_code, 403)

    def test_usuario_sem_perfil_responde_403(self):
        self.client.force_login(User.objects.create_user('sem_perfil'))
        self.assertEqual(self.client.get(self.lista).status_code, 403)

    def test_lista_so_os_livros_da_organizacao(self):
        resposta = self.client.get(self.lista)
        self.assertEqual([livro['titulo'] for livro in resposta.json()], ['Dom Casmurro'])

    def test_livro_de_outra_organizacao_responde_404(self):
        url = self.detalhe(self.livro_de_fora)
        self.assertEqual(self.client.get(url).status_code, 404)
        self.assertEqual(self.client.delete(url).status_code, 404)
        self.assertTrue(Livro.objects.filter(pk=self.livro_de_fora.pk).exists())

    def test_cria_na_organizacao_do_usuario_com_isbn_normalizado(self):
        resposta = self.criar(isbn='978-00-000-0001-1')
        self.assertEqual(resposta.status_code, 201)
        livro = Livro.objects.get(pk=resposta.json()['id'])
        self.assertEqual((livro.organizacao, livro.isbn), (self.org, '9780000000011'))

    def test_dados_invalidos_respondem_400(self):
        self.assertIn('isbn', self.criar(isbn='123').json())
        # mesmo ISBN do Dom Casmurro, só que com hífens
        resposta = self.criar(isbn='978-85-359-1066-3')
        self.assertEqual(resposta.status_code, 400)
        self.assertIn('isbn', resposta.json())
        resposta = self.criar(autores=[self.autor_de_fora.pk])
        self.assertEqual(resposta.status_code, 400)
        self.assertIn('autores', resposta.json())

    def test_atualiza_e_apaga(self):
        url = self.detalhe(self.livro)
        resposta = self.client.patch(url, {'titulo': 'Outro título'}, content_type='application/json')
        self.assertEqual(resposta.status_code, 200)
        self.assertEqual(self.client.delete(url).status_code, 204)

    def test_nao_apaga_livro_com_emprestimo(self):
        regras.realizar_emprestimo(self.ana, self.exemplar)
        self.assertEqual(self.client.delete(self.detalhe(self.livro)).status_code, 400)
        self.assertTrue(Livro.objects.filter(pk=self.livro.pk).exists())

    def test_browsable_api_renderiza_sem_autores_de_fora(self):
        resposta = self.client.get(self.lista, HTTP_ACCEPT='text/html')
        self.assertContains(resposta, 'Machado de Assis')
        self.assertNotContains(resposta, 'Autor de Fora')
        self.client.logout()
        self.assertEqual(self.client.get(reverse('rest_framework:login')).status_code, 200)


class PapeisTeste(BaseTeste):
    def setUp(self):
        super().setUp()
        self.autor = Autor.objects.get()
        self.rotas_do_catalogo = [reverse('novo_autor'), reverse('novo_livro'), reverse('novo_exemplar')] + [
            reverse(f'{acao}_{nome}', args=[objeto.pk])
            for nome, objeto in [('autor', self.autor), ('livro', self.livro), ('exemplar', self.exemplar)]
            for acao in ('editar', 'excluir')
        ]

    def virar_operador(self):
        Perfil.objects.filter(usuario=self.usuario).update(papel=Perfil.OPERADOR)

    def test_operador_nao_altera_o_catalogo_pelas_telas(self):
        self.virar_operador()
        for rota in self.rotas_do_catalogo:
            with self.subTest(rota=rota):
                self.assertEqual(self.client.get(rota).status_code, 403)
                self.assertEqual(self.client.post(rota).status_code, 403)
        self.assertTrue(Livro.objects.filter(pk=self.livro.pk).exists())

    def test_botoes_do_catalogo_so_aparecem_para_o_administrador(self):
        paginas = [reverse('lista_autores'), reverse('lista_livros'), reverse('lista_exemplares'),
                   reverse('livro_detalhe', args=[self.livro.pk])]
        for papel, aparece in [(Perfil.ADMIN, True), (Perfil.OPERADOR, False)]:
            Perfil.objects.filter(usuario=self.usuario).update(papel=papel)
            for pagina in paginas:
                with self.subTest(papel=papel, pagina=pagina):
                    resposta = self.client.get(pagina)
                    self.assertEqual(resposta.status_code, 200)
                    verificar = self.assertContains if aparece else self.assertNotContains
                    verificar(resposta, '/novo/' if pagina != reverse('livro_detalhe', args=[self.livro.pk])
                              else reverse('novo_exemplar'))
                    verificar(resposta, '/editar/')

    def test_operador_continua_atendendo_o_balcao(self):
        self.virar_operador()
        for rota in [reverse('novo_membro'), reverse('novo_emprestimo'), reverse('nova_reserva')]:
            with self.subTest(rota=rota):
                self.assertEqual(self.client.get(rota).status_code, 200)

    def test_operador_so_le_na_api(self):
        self.virar_operador()
        lista, detalhe = reverse('api_livros'), reverse('api_livro', args=[self.livro.pk])
        self.assertEqual(self.client.get(lista).status_code, 200)
        self.assertEqual(self.client.get(detalhe).status_code, 200)
        self.assertEqual(self.client.post(lista, {}).status_code, 403)
        self.assertEqual(self.client.patch(detalhe, {}, content_type='application/json').status_code, 403)
        self.assertEqual(self.client.delete(detalhe).status_code, 403)

    def test_perfil_novo_nasce_operador(self):
        perfil = Perfil.objects.create(usuario=User.objects.create_user('novato'), organizacao=self.org)
        self.assertFalse(perfil.eh_admin)


class ApiRecursosTeste(BaseTeste):
    def setUp(self):
        super().setUp()
        self.autor = Autor.objects.get()
        outra = Organizacao.objects.create(nome='Outra Biblioteca', slug='outra')
        livro = Livro.objects.create(organizacao=outra, titulo='De Fora', isbn='9780000000099', ano_publicacao=2000)
        self.de_fora = {
            'autor': Autor.objects.create(organizacao=outra, nome='Autor de Fora'),
            'livro': livro,
            'exemplar': Exemplar.objects.create(organizacao=outra, livro=livro, codigo='FORA-1'),
            'membro': Membro.objects.create(organizacao=outra, nome='Zeca', cpf='999.999.999-99', email='z@exemplo.com'),
        }
        self.de_fora['emprestimo'] = Emprestimo.objects.create(
            organizacao=outra, membro=self.de_fora['membro'], exemplar=self.de_fora['exemplar'],
        )
        self.de_fora['reserva'] = Reserva.objects.create(organizacao=outra, livro=livro, membro=self.de_fora['membro'])

    def enviar(self, rota, dados=None, pk=None):
        url = reverse(rota, args=[pk] if pk else [])
        return self.client.post(url, dados or {}, content_type='application/json')

    def emprestar(self, membro=None, exemplar=None):
        return self.enviar('api_emprestimos', {
            'membro': (membro or self.ana).pk, 'exemplar': (exemplar or self.exemplar).pk,
        })

    def test_listas_so_trazem_a_organizacao_do_usuario(self):
        for nome, rota in [('autor', 'api_autores'), ('livro', 'api_livros'), ('exemplar', 'api_exemplares'),
                           ('membro', 'api_membros'), ('emprestimo', 'api_emprestimos'),
                           ('reserva', 'api_reservas')]:
            with self.subTest(recurso=nome):
                resposta = self.client.get(reverse(rota))
                self.assertEqual(resposta.status_code, 200)
                self.assertNotIn(self.de_fora[nome].pk, [item['id'] for item in resposta.json()])
                detalhe = reverse(f'api_{nome}', args=[self.de_fora[nome].pk])
                self.assertEqual(self.client.get(detalhe).status_code, 404)

    def test_acoes_em_registro_de_outra_organizacao_respondem_404(self):
        for rota, nome in [('api_devolver', 'emprestimo'), ('api_pagar_multa', 'emprestimo'),
                           ('api_cancelar_reserva', 'reserva')]:
            with self.subTest(rota=rota):
                self.assertEqual(self.enviar(rota, pk=self.de_fora[nome].pk).status_code, 404)

    def test_nao_relaciona_registros_de_outra_organizacao(self):
        self.assertIn('membro', self.emprestar(membro=self.de_fora['membro']).json())
        self.assertIn('exemplar', self.emprestar(exemplar=self.de_fora['exemplar']).json())
        resposta = self.enviar('api_exemplares', {'livro': self.de_fora['livro'].pk, 'codigo': 'X-1'})
        self.assertIn('livro', resposta.json())

    def test_cria_catalogo_e_membro_na_organizacao_do_usuario(self):
        for rota, model, dados in [
            ('api_autores', Autor, {'nome': 'Clarice'}),
            ('api_exemplares', Exemplar, {'livro': self.livro.pk, 'codigo': 'DC-009'}),
            ('api_membros', Membro, {'nome': 'Davi', 'cpf': '44444444444', 'email': 'davi@exemplo.com'}),
        ]:
            with self.subTest(rota=rota):
                resposta = self.enviar(rota, dados)
                self.assertEqual(resposta.status_code, 201, resposta.content)
                self.assertEqual(model.objects.get(pk=resposta.json()['id']).organizacao, self.org)
        self.assertEqual(Membro.objects.get(nome='Davi').cpf, '444.444.444-44')

    def test_cpf_invalido_ou_repetido_responde_400(self):
        for cpf in ['123', '11111111111']:  # o segundo é o da Ana, sem pontuação
            with self.subTest(cpf=cpf):
                resposta = self.enviar('api_membros', {'nome': 'X', 'cpf': cpf, 'email': 'x@exemplo.com'})
                self.assertEqual(resposta.status_code, 400)
                self.assertIn('cpf', resposta.json())

    def test_emprestimo_devolucao_com_multa_e_pagamento(self):
        resposta = self.emprestar()
        self.assertEqual(resposta.status_code, 201, resposta.content)
        emprestimo = Emprestimo.objects.get(pk=resposta.json()['id'])
        self.assertEqual(emprestimo.organizacao, self.org)

        data = (emprestimo.data_prevista_devolucao + timedelta(days=3)).isoformat()
        resposta = self.enviar('api_devolver', {'data_devolucao': data}, pk=emprestimo.pk)
        self.assertEqual((resposta.status_code, resposta.json()['multa']), (200, '6.00'))
        self.assertEqual(self.enviar('api_devolver', pk=emprestimo.pk).status_code, 400)

        # multa pendente bloqueia até o pagamento
        self.assertIn('multas pendentes', self.emprestar().json()['detail'])
        resposta = self.enviar('api_pagar_multa', pk=emprestimo.pk)
        self.assertTrue(resposta.json()['multa_paga'])
        self.assertEqual(self.emprestar().status_code, 201)

    def test_regras_valem_na_api(self):
        self.emprestar()
        resposta = self.emprestar(membro=self.bruno)
        self.assertEqual(resposta.status_code, 400)
        self.assertIn('não está disponível', resposta.json()['detail'])

    def test_reserva_e_cancelamento(self):
        dados = {'livro': self.livro.pk, 'membro': self.bruno.pk}
        self.assertIn('disponível agora', self.enviar('api_reservas', dados).json()['detail'])
        self.emprestar()
        resposta = self.enviar('api_reservas', dados)
        self.assertEqual(resposta.status_code, 201, resposta.content)
        resposta = self.enviar('api_cancelar_reserva', pk=resposta.json()['id'])
        self.assertEqual(resposta.json()['status'], Reserva.CANCELADA)

    def test_historico_nao_e_editado_nem_apagado(self):
        pk = self.emprestar().json()['id']
        url = reverse('api_emprestimo', args=[pk])
        self.assertEqual(self.client.delete(url).status_code, 405)
        self.assertEqual(self.client.patch(url, {}, content_type='application/json').status_code, 405)
        for rota, objeto in [('api_membro', self.ana), ('api_exemplar', self.exemplar)]:
            self.assertEqual(self.client.delete(reverse(rota, args=[objeto.pk])).status_code, 400)

    def test_papeis(self):
        Perfil.objects.filter(usuario=self.usuario).update(papel=Perfil.OPERADOR)
        for rota in ['api_autores', 'api_livros', 'api_exemplares']:
            with self.subTest(rota=rota):
                self.assertEqual(self.client.get(reverse(rota)).status_code, 200)
                self.assertEqual(self.enviar(rota).status_code, 403)
        self.assertEqual(self.emprestar().status_code, 201)

    def test_sem_login_nada_e_acessivel(self):
        self.client.logout()
        for rota in ['api_autores', 'api_livros', 'api_exemplares', 'api_membros', 'api_emprestimos',
                     'api_reservas']:
            with self.subTest(rota=rota):
                self.assertEqual(self.client.get(reverse(rota)).status_code, 403)

    def test_browsable_api_renderiza(self):
        pk = self.emprestar().json()['id']
        for url in [reverse('api_exemplares'), reverse('api_emprestimos'), reverse('api_reservas'),
                    reverse('api_devolver', args=[pk])]:
            with self.subTest(url=url):
                resposta = self.client.get(url, HTTP_ACCEPT='text/html')
                self.assertIn(resposta.status_code, (200, 405))  # ações só aceitam POST
                self.assertNotContains(resposta, 'Zeca', status_code=resposta.status_code)


class PainelTeste(BaseTeste):
    def setUp(self):
        super().setUp()
        self.outro_livro = Livro.objects.create(
            organizacao=self.org, titulo='1984', isbn='9788535914849', ano_publicacao=1949,
        )
        self.outro_exemplar = Exemplar.objects.create(organizacao=self.org, livro=self.outro_livro, codigo='84-1')

    def emprestimo(self, membro, exemplar, dias_atras, multa='0.00', paga=True):
        data = self.hoje - timedelta(days=dias_atras)
        return Emprestimo.objects.create(
            organizacao=exemplar.organizacao, membro=membro, exemplar=exemplar, data_emprestimo=data,
            data_devolucao=data, multa=Decimal(multa), multa_paga=paga,
        )

    def painel(self, **filtro):
        resposta = self.client.get(reverse('dashboard'), filtro)
        self.assertEqual(resposta.status_code, 200)
        return resposta

    def test_totais_multas_e_rankings(self):
        self.emprestimo(self.ana, self.exemplar, 1, multa='4.00', paga=False)
        self.emprestimo(self.ana, self.exemplar, 2, multa='6.00')
        self.emprestimo(self.bruno, self.outro_exemplar, 3)
        dados = self.painel().context['metricas']

        self.assertEqual((dados['emprestimos'], dados['devolucoes']), (3, 3))
        self.assertEqual((dados['multas_geradas'], dados['multas_pendentes']), (Decimal('10.00'), Decimal('4.00')))
        self.assertEqual([(i['exemplar__livro__titulo'], i['total']) for i in dados['livros']],
                         [('Dom Casmurro', 2), ('1984', 1)])
        self.assertEqual([(i['membro__nome'], i['total']) for i in dados['membros']], [('Ana', 2), ('Bruno', 1)])

    def test_filtro_por_periodo(self):
        self.emprestimo(self.ana, self.exemplar, 1)
        self.emprestimo(self.bruno, self.outro_exemplar, 250)
        self.assertEqual(self.painel().context['metricas']['emprestimos'], 1)  # padrão: 6 meses

        antigo = self.hoje - timedelta(days=250)
        dados = self.painel(de=antigo.isoformat(), ate=antigo.isoformat()).context['metricas']
        self.assertEqual([i['membro__nome'] for i in dados['membros']], ['Bruno'])

    def test_periodo_invalido_avisa_e_usa_o_padrao(self):
        self.emprestimo(self.ana, self.exemplar, 1)
        for filtro, aviso in [({'de': '2026-02-01', 'ate': '2026-01-01'}, 'não pode ser depois'),
                              ({'de': 'abc', 'ate': ''}, 'Informe as duas datas')]:
            with self.subTest(filtro=filtro):
                resposta = self.painel(**filtro)
                self.assertContains(resposta, aviso)
                self.assertEqual(resposta.context['metricas']['emprestimos'], 1)

    def test_nao_conta_outra_organizacao(self):
        outra = Organizacao.objects.create(nome='Outra Biblioteca', slug='outra')
        livro = Livro.objects.create(organizacao=outra, titulo='De Fora', isbn='9780000000099', ano_publicacao=2000)
        exemplar = Exemplar.objects.create(organizacao=outra, livro=livro, codigo='FORA-1')
        membro = Membro.objects.create(organizacao=outra, nome='Zeca', cpf='999.999.999-99', email='z@exemplo.com')
        self.emprestimo(membro, exemplar, 1, multa='50.00', paga=False)

        resposta = self.painel()
        self.assertEqual(resposta.context['metricas']['emprestimos'], 0)
        self.assertEqual(resposta.context['metricas']['multas_geradas'], Decimal('0.00'))
        self.assertNotContains(resposta, 'Zeca')

    def test_abertos_e_leitores_ativos(self):
        self.emprestimo(self.ana, self.exemplar, 5)
        self.emprestimo(self.ana, self.exemplar, 4)
        Emprestimo.objects.create(organizacao=self.org, membro=self.bruno, exemplar=self.outro_exemplar)
        dados = self.painel().context['metricas']
        self.assertEqual((dados['emprestimos'], dados['abertos'], dados['leitores']), (3, 1, 2))

    def test_serie_mensal_em_ordem_cronologica(self):
        # meio do mês, para a data não mudar de mês conforme o dia em que o teste roda
        este_mes = self.hoje.replace(day=1)
        mes_passado = (este_mes - timedelta(days=1)).replace(day=1)
        for data in [este_mes, mes_passado, mes_passado]:
            Emprestimo.objects.create(organizacao=self.org, membro=self.ana, exemplar=self.exemplar,
                                      data_emprestimo=data, data_devolucao=data)
        dados = self.painel(de=mes_passado.isoformat(), ate=self.hoje.isoformat()).context['metricas']
        self.assertEqual([(i['mes'], i['total']) for i in dados['por_mes']], [(mes_passado, 2), (este_mes, 1)])

    def test_grafico_recebe_meses_formatados_e_preenche_os_vazios(self):
        for data in [date(2025, 11, 10), date(2026, 1, 5), date(2026, 1, 20)]:
            Emprestimo.objects.create(organizacao=self.org, membro=self.ana, exemplar=self.exemplar,
                                      data_emprestimo=data, data_devolucao=data)
        resposta = self.painel(de='2025-11-01', ate='2026-02-28')
        self.assertEqual(resposta.context['metricas']['grafico_mensal'], [
            {'mes': '11/2025', 'total': 1}, {'mes': '12/2025', 'total': 0},
            {'mes': '01/2026', 'total': 2}, {'mes': '02/2026', 'total': 0},
        ])
        self.assertContains(resposta, '<script id="dados-mes" type="application/json">')
        self.assertContains(resposta, 'id="grafico-mensal"')
        self.assertContains(resposta, 'acervo/js/dashboard.js')

    def test_periodo_padrao_comeca_no_dia_primeiro_de_cinco_meses_atras(self):
        periodo = self.painel().context['periodo']
        meses = (periodo['ate'].year - periodo['de'].year) * 12 + periodo['ate'].month - periodo['de'].month
        self.assertEqual((periodo['de'].day, meses, periodo['ate']), (1, 5, self.hoje))

    def test_sem_dados_nao_cria_o_grafico(self):
        resposta = self.painel()
        self.assertEqual(resposta.context['metricas']['grafico_mensal'], [])
        self.assertNotContains(resposta, 'id="grafico-mensal"')
        self.assertContains(resposta, 'Nenhum empréstimo no período.')

    def test_distribuicao_de_reservas_por_status(self):
        for membro, status in [(self.ana, Reserva.AGUARDANDO), (self.bruno, Reserva.AGUARDANDO),
                               (self.carla, Reserva.CANCELADA)]:
            Reserva.objects.create(organizacao=self.org, livro=self.livro, membro=membro, status=status)
        dados = self.painel().context['metricas']
        self.assertEqual([(i['status'], i['total']) for i in dados['reservas_por_status']],
                         [('Aguardando na fila', 2), ('Cancelada', 1)])


class UnicidadePorOrganizacaoTeste(BaseTeste):
    def setUp(self):
        super().setUp()
        self.autor = Autor.objects.get()
        outra = Organizacao.objects.create(nome='Outra Biblioteca', slug='outra')
        livro = Livro.objects.create(organizacao=outra, titulo='De Fora', isbn='9780000000099', ano_publicacao=2000)
        Exemplar.objects.create(organizacao=outra, livro=livro, codigo='FORA-1')
        Membro.objects.create(organizacao=outra, nome='Zeca', cpf='999.999.999-99', email='zeca@exemplo.com')

    def casos(self, isbn, codigo, cpf, email):
        """(tela, rota da API, model, dados) de cada cadastro com campo único."""
        return [
            ('novo_livro', 'api_livros', Livro,
             {'titulo': 'Novo', 'autores': [self.autor.pk], 'isbn': isbn, 'ano_publicacao': 2000}),
            ('novo_exemplar', 'api_exemplares', Exemplar,
             {'livro': self.livro.pk, 'codigo': codigo, 'data_aquisicao': self.hoje.isoformat(), 'ativo': True}),
            ('novo_membro', 'api_membros', Membro, {'nome': 'Novo', 'cpf': cpf, 'email': email, 'ativo': True}),
        ]

    def test_tela_aceita_valores_usados_por_outra_organizacao(self):
        for tela, _, model, dados in self.casos('9780000000099', 'FORA-1', '99999999999', 'zeca@exemplo.com'):
            with self.subTest(tela=tela):
                antes = model.objects.filter(organizacao=self.org).count()
                self.assertEqual(self.client.post(reverse(tela), dados).status_code, 302)
                self.assertEqual(model.objects.filter(organizacao=self.org).count(), antes + 1)

    def test_api_aceita_valores_usados_por_outra_organizacao(self):
        for _, rota, _, dados in self.casos('9780000000099', 'FORA-1', '99999999999', 'zeca@exemplo.com'):
            with self.subTest(rota=rota):
                resposta = self.client.post(reverse(rota), dados, content_type='application/json')
                self.assertEqual(resposta.status_code, 201, resposta.content)

    def test_repetido_na_mesma_organizacao_e_recusado_na_tela_e_na_api(self):
        repetidos = self.casos('978-85-359-1066-3', 'DC-001', '11111111111', 'ana@exemplo.com')
        esperados = [['isbn'], ['codigo'], ['cpf', 'email']]
        for (tela, rota, model, dados), campos in zip(repetidos, esperados):
            with self.subTest(rota=rota):
                antes = model.objects.count()
                resposta = self.client.post(reverse(tela), dados)
                self.assertEqual(sorted(resposta.context['form'].errors), campos)
                resposta = self.client.post(reverse(rota), dados, content_type='application/json')
                self.assertEqual((resposta.status_code, sorted(resposta.json())), (400, campos))
                self.assertEqual(model.objects.count(), antes)

    def test_editar_mantendo_o_proprio_valor_e_permitido(self):
        dados = {'nome': 'Ana Maria', 'cpf': self.ana.cpf, 'email': self.ana.email, 'ativo': True}
        self.assertEqual(self.client.post(reverse('editar_membro', args=[self.ana.pk]), dados).status_code, 302)
        resposta = self.client.put(reverse('api_membro', args=[self.ana.pk]), dados, content_type='application/json')
        self.assertEqual(resposta.status_code, 200, resposta.content)

    def test_banco_tambem_recusa_repetido(self):
        with self.assertRaises(IntegrityError), transaction.atomic():
            Livro.objects.create(organizacao=self.org, titulo='X', isbn=self.livro.isbn, ano_publicacao=2000)


class AdminOrganizacaoTeste(BaseTeste):
    def test_listas_mostram_e_filtram_por_organizacao(self):
        outra = Organizacao.objects.create(nome='Outra Biblioteca', slug='outra')
        Autor.objects.create(organizacao=outra, nome='Autor de Fora')
        self.client.force_login(User.objects.create_superuser('dono'))
        for model in (Autor, Livro, Exemplar, Membro, Emprestimo, Reserva):
            with self.subTest(model=model.__name__):
                resposta = self.client.get(reverse(f'admin:acervo_{model._meta.model_name}_changelist'))
                lista = resposta.context['cl']
                self.assertIn('organizacao', lista.list_display)
                self.assertIn('organizacao', lista.list_filter)

        url = reverse('admin:acervo_autor_changelist')
        resposta = self.client.get(url, {'organizacao__id__exact': outra.pk})
        self.assertEqual([autor.nome for autor in resposta.context['cl'].result_list], ['Autor de Fora'])


class ExclusaoDeOrganizacaoTeste(BaseTeste):
    def test_organizacao_com_acervo_e_perfis_nao_pode_ser_excluida(self):
        with self.assertRaises(ProtectedError):
            self.org.delete()
        self.assertTrue(Livro.objects.filter(pk=self.livro.pk).exists())

    def test_cada_vinculo_sozinho_ja_protege(self):
        so_perfil = Organizacao.objects.create(nome='Só perfil', slug='so-perfil')
        Perfil.objects.create(usuario=User.objects.create_user('outro'), organizacao=so_perfil)
        so_acervo = Organizacao.objects.create(nome='Só acervo', slug='so-acervo')
        Autor.objects.create(organizacao=so_acervo, nome='Autor')
        for organizacao in (so_perfil, so_acervo):
            with self.subTest(organizacao=organizacao), self.assertRaises(ProtectedError):
                organizacao.delete()

    def test_organizacao_vazia_pode_ser_excluida(self):
        vazia = Organizacao.objects.create(nome='Vazia', slug='vazia')
        vazia.delete()
        self.assertFalse(Organizacao.objects.filter(slug='vazia').exists())


class RoteiroDeIsolamentoTeste(BaseTeste):
    """Os cinco cenários do roteiro anotado no README. A = self.org, B = outra."""

    def setUp(self):
        super().setUp()
        b = Organizacao.objects.create(nome='Biblioteca B', slug='b')
        self.livro_b = Livro.objects.create(organizacao=b, titulo='Livro da B', isbn='9780000000099',
                                            ano_publicacao=2000)
        Autor.objects.create(organizacao=b, nome='Autor da B')
        Exemplar.objects.create(organizacao=b, livro=self.livro_b, codigo='DA-B-1')
        Membro.objects.create(organizacao=b, nome='Membro da B', cpf='999.999.999-99', email='b@exemplo.com')

    def criar_livro(self, isbn):
        return self.client.post(reverse('novo_livro'), {
            'titulo': 'Criado por A', 'autores': [Autor.objects.get(organizacao=self.org).pk],
            'isbn': isbn, 'ano_publicacao': 2000,
        })

    def test_1_lista_so_mostra_livros_de_a(self):
        resposta = self.client.get(reverse('lista_livros'))
        self.assertContains(resposta, 'Dom Casmurro')
        self.assertNotContains(resposta, 'Livro da B')

    def test_2_editar_livro_de_b_responde_404(self):
        self.assertEqual(self.client.get(reverse('editar_livro', args=[self.livro_b.pk])).status_code, 404)

    def test_3_livro_criado_fica_em_a(self):
        self.criar_livro('9780000000011')
        self.assertEqual(Livro.objects.get(titulo='Criado por A').organizacao, self.org)

    def test_4_selects_so_oferecem_opcoes_de_a(self):
        for rota, de_fora in [
            ('novo_livro', ['Autor da B']),
            ('novo_exemplar', ['Livro da B']),
            ('novo_emprestimo', ['Membro da B', 'DA-B-1']),
            ('nova_reserva', ['Livro da B', 'Membro da B']),
        ]:
            resposta = self.client.get(reverse(rota))
            for texto in de_fora:
                with self.subTest(rota=rota, texto=texto):
                    self.assertNotContains(resposta, texto)

    def test_5_isbn_de_b_pode_ser_cadastrado_em_a(self):
        self.assertEqual(self.criar_livro(self.livro_b.isbn).status_code, 302)
        self.assertTrue(Livro.objects.filter(organizacao=self.org, isbn=self.livro_b.isbn).exists())


class OrganizacaoCriadaEmTeste(TestCase):
    def test_data_de_criacao_e_preenchida_automaticamente(self):
        antes = timezone.now()
        organizacao = Organizacao.objects.create(nome='Nova', slug='nova')
        self.assertTrue(antes <= organizacao.criada_em <= timezone.now())
        self.assertFalse(Organizacao.objects.filter(criada_em__isnull=True).exists())


class SenhasPrevisiveisTeste(TestCase):
    def migrar(self):
        import_module('acervo.migrations.0012_remove_senhas_previsiveis').neutralizar_senhas_previsiveis(apps, None)

    def test_usuarios_de_demonstracao_nascem_sem_senha_e_sem_privilegios(self):
        for nome in ('admin_central', 'admin_norte'):
            usuario = User.objects.get(username=nome)
            self.assertFalse(usuario.has_usable_password())
            self.assertFalse(usuario.is_superuser or usuario.is_staff)
            self.assertTrue(usuario.perfil.eh_admin)

    def test_bloqueia_quem_ainda_usa_a_senha_antiga(self):
        User.objects.filter(username='admin_central').update(
            password=make_password('admin_central'), is_superuser=True, is_staff=True,
        )
        self.migrar()
        usuario = User.objects.get(username='admin_central')
        self.assertFalse(usuario.has_usable_password())
        self.assertFalse(usuario.is_superuser or usuario.is_staff)

    def test_nao_mexe_em_quem_ja_trocou_a_senha(self):
        User.objects.filter(username='admin_norte').update(
            password=make_password('outra-senha-de-teste'), is_superuser=True,
        )
        self.migrar()
        usuario = User.objects.get(username='admin_norte')
        self.assertTrue(usuario.check_password('outra-senha-de-teste'))
        self.assertTrue(usuario.is_superuser)


class PrepararDemoTeste(TestCase):
    def preparar(self, **opcoes):
        saida = StringIO()
        call_command('preparar_demo', stdout=saida, **opcoes)
        return saida.getvalue()

    def test_quem_avalia_consegue_entrar_com_a_senha_mostrada(self):
        senha = self.preparar().split('Senha: ')[1].strip()
        for nome, papel in [('admin_central', Perfil.ADMIN), ('operador_central', Perfil.OPERADOR),
                            ('admin_norte', Perfil.ADMIN), ('operador_norte', Perfil.OPERADOR)]:
            with self.subTest(nome=nome):
                resposta = self.client.post(reverse('login'), {'username': nome, 'password': senha})
                self.assertRedirects(resposta, reverse('inicio'))
                self.assertContains(self.client.get(reverse('lista_livros')), 'Dom Casmurro')
                self.assertEqual(User.objects.get(username=nome).perfil.papel, papel)
                self.client.logout()

    def test_aceita_senha_escolhida_e_pode_rodar_de_novo(self):
        self.preparar()
        livros = Livro.objects.count()
        self.preparar(senha='frase-longa-de-teste-42')
        self.assertEqual(Livro.objects.count(), livros)
        self.assertTrue(self.client.login(username='admin_norte', password='frase-longa-de-teste-42'))

    def test_recusa_senha_fraca(self):
        with self.assertRaisesMessage(CommandError, 'Senha fraca'):
            self.preparar(senha='123')


class DashboardPorPapelTeste(BaseTeste):
    def setUp(self):
        super().setUp()
        regras.realizar_emprestimo(self.ana, self.exemplar)

    def abrir(self, papel):
        Perfil.objects.filter(usuario=self.usuario).update(papel=papel)
        resposta = self.client.get(reverse('dashboard'))
        self.assertEqual(resposta.status_code, 200)
        return resposta

    def test_administrador_ve_a_serie(self):
        resposta = self.abrir(Perfil.ADMIN)
        self.assertContains(resposta, 'Empréstimos por mês')
        self.assertContains(resposta, 'id="dados-mes"')

    def test_operador_ve_totais_e_ranking_mas_nao_a_serie(self):
        resposta = self.abrir(Perfil.OPERADOR)
        self.assertContains(resposta, 'empréstimos feitos')
        self.assertContains(resposta, 'Dom Casmurro')
        self.assertContains(resposta, 'Reservas do período por status')
        for escondido in ['Empréstimos por mês', 'dados-mes', 'grafico-mensal', 'chart.umd.js']:
            with self.subTest(escondido=escondido):
                self.assertNotContains(resposta, escondido)
        # nem no contexto da página
        self.assertNotIn('por_mes', resposta.context['metricas'])
        self.assertNotIn('grafico_mensal', resposta.context['metricas'])


class ExportarCsvTeste(BaseTeste):
    def setUp(self):
        super().setUp()
        outra = Organizacao.objects.create(nome='Outra Biblioteca', slug='outra')
        livro = Livro.objects.create(organizacao=outra, titulo='De Fora', isbn='9780000000099', ano_publicacao=2000)
        self.criar(Exemplar.objects.create(organizacao=outra, livro=livro, codigo='FORA-1'),
                   Membro.objects.create(organizacao=outra, nome='Zeca', cpf='999.999.999-99', email='z@x.com'), 1)

    def criar(self, exemplar, membro, dias_atras):
        data = self.hoje - timedelta(days=dias_atras)
        return Emprestimo.objects.create(
            organizacao=exemplar.organizacao, exemplar=exemplar, membro=membro, data_emprestimo=data,
            data_devolucao=data, multa=Decimal('4.50'),
        )

    def linhas(self, **filtro):
        resposta = self.client.get(reverse('exportar_csv'), filtro)
        self.assertEqual(resposta.status_code, 200)
        self.assertIn('attachment; filename="emprestimos_', resposta['Content-Disposition'])
        return list(csv.reader(StringIO(resposta.content.decode('utf-8-sig')), delimiter=';'))

    def test_exporta_so_a_organizacao_do_usuario(self):
        self.criar(self.exemplar, self.ana, 2)
        cabecalho, *linhas = self.linhas()
        self.assertEqual(cabecalho[:3], ['Livro', 'Exemplar', 'Membro'])
        self.assertEqual([linha[:3] for linha in linhas], [['Dom Casmurro', 'DC-001', 'Ana']])
        self.assertEqual(linhas[0][6:], ['4,50', 'não'])

    def test_marca_de_codificacao_aparece_so_no_comeco(self):
        self.criar(self.exemplar, self.ana, 2)
        conteudo = self.client.get(reverse('exportar_csv')).content
        self.assertTrue(conteudo.startswith(b'\xef\xbb\xbf'))
        self.assertEqual(conteudo.count(b'\xef\xbb\xbf'), 1)

    def test_respeita_o_periodo(self):
        self.criar(self.exemplar, self.ana, 2)
        self.criar(self.exemplar, self.bruno, 40)
        dia = (self.hoje - timedelta(days=40)).isoformat()
        self.assertEqual([linha[2] for linha in self.linhas(de=dia, ate=dia)[1:]], ['Bruno'])

    def test_sem_dados_traz_so_o_cabecalho_e_data_invalida_nao_quebra(self):
        self.assertEqual(len(self.linhas()), 1)
        self.assertEqual(len(self.linhas(de='abc', ate='xyz')), 1)

    def test_texto_com_cara_de_formula_e_neutralizado(self):
        for inicio in ['=', '+', '-', '@']:
            with self.subTest(inicio=inicio):
                self.assertEqual(relatorios.celula_segura(f'{inicio}1+1'), f"'{inicio}1+1")
        self.ana.nome = '=HYPERLINK("http://exemplo.com")'
        self.ana.save()
        self.criar(self.exemplar, self.ana, 2)
        self.assertEqual(self.linhas()[1][2], '\'=HYPERLINK("http://exemplo.com")')

    def test_operador_nao_exporta_nem_ve_o_botao(self):
        Perfil.objects.filter(usuario=self.usuario).update(papel=Perfil.OPERADOR)
        self.assertEqual(self.client.get(reverse('exportar_csv')).status_code, 403)
        self.assertNotContains(self.client.get(reverse('dashboard')), 'Exportar CSV')

    def test_administrador_ve_o_botao_e_visitante_vai_para_o_login(self):
        self.assertContains(self.client.get(reverse('dashboard')), 'Exportar CSV')
        self.client.logout()
        self.assertEqual(self.client.get(reverse('exportar_csv')).status_code, 302)


class ApiDashboardTeste(BaseTeste):
    def setUp(self):
        super().setUp()
        outra = Organizacao.objects.create(nome='Outra Biblioteca', slug='outra')
        livro = Livro.objects.create(organizacao=outra, titulo='De Fora', isbn='9780000000099', ano_publicacao=2000)
        Emprestimo.objects.create(
            organizacao=outra, exemplar=Exemplar.objects.create(organizacao=outra, livro=livro, codigo='FORA-1'),
            membro=Membro.objects.create(organizacao=outra, nome='Zeca', cpf='999.999.999-99', email='z@x.com'),
        )
        regras.realizar_emprestimo(self.ana, self.exemplar)
        self.url = reverse('api_dashboard')

    def test_traz_so_os_numeros_da_organizacao(self):
        dados = self.client.get(self.url).json()
        self.assertEqual((dados['emprestimos'], dados['abertos'], dados['leitores']), (1, 1, 1))
        self.assertEqual(dados['multas_geradas'], '0.00')
        self.assertEqual(dados['livros'], [{'id': self.livro.pk, 'titulo': 'Dom Casmurro', 'total': 1}])
        self.assertEqual(dados['membros'], [{'id': self.ana.pk, 'nome': 'Ana', 'total': 1}])
        self.assertEqual(dados['por_mes'][-1], {'mes': self.hoje.strftime('%m/%Y'), 'total': 1})
        self.assertEqual(dados['periodo']['ate'], self.hoje.isoformat())

    def test_filtra_por_periodo(self):
        dados = self.client.get(self.url, {'de': '2020-01-01', 'ate': '2020-01-31'}).json()
        self.assertEqual((dados['emprestimos'], dados['livros'], dados['por_mes']), (0, [], []))

    def test_periodo_invalido_responde_400(self):
        for filtro in [{'de': 'abc', 'ate': '2026-01-01'}, {'de': '2026-01-01'},
                       {'de': '2026-02-01', 'ate': '2026-01-01'}]:
            with self.subTest(filtro=filtro):
                self.assertEqual(self.client.get(self.url, filtro).status_code, 400)

    def test_operador_nao_recebe_a_serie(self):
        Perfil.objects.filter(usuario=self.usuario).update(papel=Perfil.OPERADOR)
        dados = self.client.get(self.url).json()
        self.assertEqual(dados['emprestimos'], 1)
        self.assertNotIn('por_mes', dados)

    def test_exige_login_e_perfil_e_so_aceita_leitura(self):
        self.assertEqual(self.client.post(self.url).status_code, 405)
        self.client.force_login(User.objects.create_user('sem_perfil'))
        self.assertEqual(self.client.get(self.url).status_code, 403)
        self.client.logout()
        self.assertEqual(self.client.get(self.url).status_code, 403)

    def test_browsable_api_renderiza(self):
        self.assertEqual(self.client.get(self.url, HTTP_ACCEPT='text/html').status_code, 200)


class ConsultasTeste(BaseTeste):
    """Trava o N+1: com mais registros, cada página faz o mesmo número de consultas."""

    def criar_registros(self, quantidade):
        for _ in range(quantidade):
            n = Exemplar.objects.count() + 100
            livro = Livro.objects.create(organizacao=self.org, titulo=f'Livro {n}', isbn=f'{n:013d}',
                                         ano_publicacao=2000)
            livro.autores.add(Autor.objects.create(organizacao=self.org, nome=f'Autor {n}'))
            membro = Membro.objects.create(organizacao=self.org, nome=f'M{n}', cpf=str(n), email=f'm{n}@x.com')
            # um exemplar no livro novo e outro no livro de sempre, para o detalhe dele crescer
            for alvo, codigo in [(livro, f'A{n}'), (self.livro, f'B{n}')]:
                exemplar = Exemplar.objects.create(organizacao=self.org, livro=alvo, codigo=codigo)
                Emprestimo.objects.create(organizacao=self.org, exemplar=exemplar, membro=membro)
            Reserva.objects.create(organizacao=self.org, livro=self.livro, membro=membro)

    def contar(self, url):
        with CaptureQueriesContext(connection) as contexto:
            self.assertEqual(self.client.get(url).status_code, 200)
        return len(contexto)

    def test_consultas_nao_crescem_com_os_registros(self):
        urls = [reverse(nome) for nome in [
            'inicio', 'dashboard', 'exportar_csv', 'lista_livros', 'lista_autores', 'lista_exemplares',
            'lista_membros', 'lista_emprestimos', 'lista_reservas', 'api_livros', 'api_autores',
            'api_exemplares', 'api_membros', 'api_emprestimos', 'api_reservas', 'api_dashboard',
        ]]
        urls += [reverse('livro_detalhe', args=[self.livro.pk]), reverse('membro_detalhe', args=[self.ana.pk])]
        self.criar_registros(2)
        antes = {url: self.contar(url) for url in urls}
        self.criar_registros(8)
        for url, consultas in antes.items():
            with self.subTest(url=url), self.assertNumQueries(consultas):
                self.client.get(url)

    def test_dados_em_lote_batem_com_a_consulta_individual(self):
        regras.realizar_emprestimo(self.ana, self.exemplar)
        Exemplar.objects.create(organizacao=self.org, livro=self.livro, codigo='LIVRE')
        Exemplar.objects.create(organizacao=self.org, livro=self.livro, codigo='FORA', ativo=False)
        for lote in Exemplar.objects.com_situacao():
            self.assertEqual(lote.situacao, Exemplar.objects.get(pk=lote.pk).situacao)

        livro = Livro.objects.prefetch_related(Prefetch('exemplares', Exemplar.objects.com_situacao())).get()
        self.assertEqual((livro.total_disponiveis(), livro.total_exemplares()), (1, 3))

        reservas = [Reserva.objects.create(organizacao=self.org, livro=self.livro, membro=membro, status=status)
                    for membro, status in [(self.bruno, Reserva.CANCELADA), (self.carla, Reserva.AGUARDANDO),
                                           (self.ana, Reserva.AGUARDANDO)]]
        carregadas = regras.carregar_posicoes(list(Reserva.objects.order_by('pk')), self.org)
        self.assertEqual([r.posicao_na_fila() for r in carregadas], [None, 1, 2])
        self.assertEqual([Reserva.objects.get(pk=r.pk).posicao_na_fila() for r in reservas], [None, 1, 2])


class ConferenciaDoDashboardTeste(BaseTeste):
    """Aula 17: números pequenos e conhecidos (3 na organização A, 5 na B)."""

    def setUp(self):
        super().setUp()
        self.outra = Organizacao.objects.create(nome='Biblioteca B', slug='b')
        livro = Livro.objects.create(organizacao=self.outra, titulo='Da B', isbn='9780000000099', ano_publicacao=2000)
        self.exemplar_b = Exemplar.objects.create(organizacao=self.outra, livro=livro, codigo='B-1')
        self.membro_b = Membro.objects.create(organizacao=self.outra, nome='Zeca', cpf='999.999.999-99',
                                              email='z@x.com')

    def criar(self, exemplar, membro, quantidade):
        for _ in range(quantidade):
            Emprestimo.objects.create(organizacao=exemplar.organizacao, exemplar=exemplar, membro=membro,
                                      data_devolucao=self.hoje)

    def test_total_do_dashboard_bate_com_a_consulta_feita_a_mao(self):
        self.criar(self.exemplar, self.ana, 3)
        self.criar(self.exemplar_b, self.membro_b, 5)
        with connection.cursor() as cursor:
            cursor.execute('SELECT COUNT(*) FROM acervo_emprestimo WHERE organizacao_id = %s', [self.org.pk])
            na_mao = cursor.fetchone()[0]
        no_painel = self.client.get(reverse('dashboard')).context['metricas']['emprestimos']
        self.assertEqual((no_painel, na_mao), (3, 3))

    def test_dashboard_vazio_abre_sem_erro_mesmo_com_dados_em_outra_organizacao(self):
        self.criar(self.exemplar_b, self.membro_b, 5)
        resposta = self.client.get(reverse('dashboard'))
        self.assertEqual(resposta.status_code, 200)
        dados = resposta.context['metricas']
        for chave in ['emprestimos', 'abertos', 'leitores', 'devolucoes', 'multas_geradas', 'multas_pendentes']:
            with self.subTest(chave=chave):
                self.assertEqual(dados[chave], 0)
        for chave in ['livros', 'membros', 'por_mes', 'grafico_mensal', 'reservas_por_status']:
            with self.subTest(chave=chave):
                self.assertEqual(dados[chave], [])
        self.assertContains(resposta, 'Nenhum empréstimo no período.')
        self.assertContains(resposta, 'Nenhuma reserva no período.')
