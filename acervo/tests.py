from datetime import timedelta
from decimal import Decimal
from io import StringIO

from django.contrib.auth.models import User
from django.core.management import call_command
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from . import regras
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
