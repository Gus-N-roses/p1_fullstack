# Biblioteca / Acervo — P1

Projeto da disciplina **Laboratório de Programação Full Stack** (Universidade de Vassouras).
Opção 1 do catálogo: **Biblioteca / Acervo**, com empréstimos, fila de reserva e cálculo de multa.

**Stack:** Python + Django (templates, sem framework de front-end separado) + PostgreSQL.

## Entidades

| Model | O que representa |
|---|---|
| `Autor` | quem escreveu os livros |
| `Livro` | o título (ISBN, editora, ano); tem vários autores |
| `Exemplar` | cada cópia física de um livro, com código de tombo |
| `Membro` | quem pega livros emprestados |
| `Emprestimo` | um exemplar emprestado a um membro, com prazo, devolução e multa |
| `Reserva` | a posição de um membro na fila de espera de um livro |

## Regras de negócio (P1)

Estão todas em [`acervo/regras.py`](acervo/regras.py) e os valores ficam no `.env`:

- **Prazo de empréstimo:** 14 dias (`PRAZO_EMPRESTIMO_DIAS`).
- **Multa por atraso:** R$ 2,00 por dia (`VALOR_MULTA_DIARIA`), calculada na devolução.
  Enquanto o empréstimo está aberto, as telas mostram a multa acumulada até hoje.
- **Bloqueios:** o membro não pega livro se estiver inativo, tiver multa pendente, tiver
  empréstimo atrasado ou já estiver no limite de 3 empréstimos (`LIMITE_EMPRESTIMOS_POR_MEMBRO`).
- **Fila de reserva:**
  - só dá para reservar quando não há exemplar livre;
  - a fila segue a ordem de chegada;
  - quando um exemplar é devolvido, ele fica **separado** para o primeiro da fila,
    que tem 3 dias para retirar (`PRAZO_RETIRADA_RESERVA_DIAS`);
  - ninguém fura a fila: enquanto o exemplar está separado, só quem reservou pode pegá-lo;
  - se o prazo de retirada vencer, a reserva expira e o próximo da fila é chamado;
  - cancelar uma reserva separada também passa a vez para o próximo.

## Para avaliar o projeto

Depois de instalar (passos 1 a 3 de "Como rodar"):

```bash
python manage.py migrate
python manage.py preparar_demo     # mostra a senha no terminal
python manage.py runserver
```

O `preparar_demo` cria dados nas duas bibliotecas (se ainda não tiverem livros) e estas contas,
todas com a senha exibida. Nenhuma senha fica gravada no repositório; para escolher a sua, use
`--senha`. Rodar de novo troca a senha dessas contas.

| Usuário | Papel | Organização |
|---|---|---|
| `admin_central` | administrador | Biblioteca Central |
| `operador_central` | operador | Biblioteca Central |
| `admin_norte` | administrador | Biblioteca Norte |
| `operador_norte` | operador | Biblioteca Norte |

Para o Django Admin (`/admin`), crie um superusuário com `python manage.py createsuperuser`.

## Como rodar

```bash
# 1. ambiente virtual
python3 -m venv venv
source venv/bin/activate          # Windows: venv\Scripts\activate
pip install -r requirements.txt

# 2. banco PostgreSQL
createdb biblioteca_db            # ou crie pelo pgAdmin

# 3. variáveis de ambiente
cp .env.example .env              # e preencha DB_PASSWORD, SECRET_KEY...

# 4. tabelas, admin e dados de exemplo
python manage.py migrate
python manage.py createsuperuser
python manage.py popular_dados    # opcional: livros, membros, um atraso e uma fila
                                  # (na Biblioteca Central; troque com --organizacao <slug>)

# 5. servidor
python manage.py runserver
```

Todas as telas exigem login, e cada usuário só vê os dados da própria organização.
Um usuário novo (inclusive o do `createsuperuser`) precisa de um **Perfil** ligado a uma
organização, definido no Admin, na edição do usuário.

Acesse http://127.0.0.1:8000 (sistema) e http://127.0.0.1:8000/admin (Django Admin).

## Início e dashboard

A tela inicial mostra o que pede ação hoje: totais do acervo, empréstimos em atraso e reservas
para retirada. O **dashboard** (`/dashboard/`) mostra o movimento de um período (padrão: últimos
6 meses) e responde a quatro perguntas de quem administra a biblioteca, com as consultas em
[`acervo/metricas.py`](acervo/metricas.py):

| Pergunta da semana | Tipo | Onde aparece |
|---|---|---|
| Quanto a biblioteca movimentou e quanto há de multa a receber? | total (KPI) | cartões |
| Quais livros mais saem, e quem mais pega? | ranking | top 5 de livros e de membros |
| A procura está subindo ou caindo? | série no tempo | gráfico de empréstimos por mês (Chart.js) |
| O que aconteceu com as reservas? | distribuição | reservas por status |

## Roteiro de isolamento (Aula 14)

Duas organizações, A e B, com um usuário logado em A. Executado em 25/11/2026 por testes
automatizados (não é um registro de teste manual no navegador):

| Cenário | Esperado | Resultado |
|---|---|---|
| Usuário A abre a lista de livros | vê só os livros de A | passou |
| Usuário A abre `/livros/<id de B>/editar/` | 404 | passou |
| Usuário A cria um livro | gravado em A | passou |
| Formulários de livro, exemplar, empréstimo e reserva | selects só com opções de A | passou |
| Usuário A cadastra um ISBN que B já usa | permitido | passou |

Para repetir:

```bash
python manage.py test acervo.tests.RoteiroDeIsolamentoTeste
```

O Django Admin fica fora do isolamento: o superusuário enxerga todas as organizações.

## Papéis

| Ação | Administrador | Operador |
|---|---|---|
| Empréstimos, devoluções, multas, reservas e membros | sim | sim |
| Consultar autores, livros e exemplares | sim | sim |
| Cadastrar, editar e excluir autores, livros e exemplares | sim | não |
| Dashboard: totais, rankings e reservas por status | sim | sim |
| Dashboard: série de empréstimos por mês | sim | não |
| Exportar os empréstimos do período em CSV | sim | não |

O papel é definido no **Perfil** do usuário (padrão: operador) e vale nas telas e na API.

## API (Django REST Framework)

| Recurso | Lista e criação (GET, POST) | Um registro |
|---|---|---|
| Autores | `/api/autores/` | `/api/autores/<id>/` (GET, PUT, PATCH, DELETE) |
| Livros | `/api/livros/` | `/api/livros/<id>/` (GET, PUT, PATCH, DELETE) |
| Exemplares | `/api/exemplares/` | `/api/exemplares/<id>/` (GET, PUT, PATCH, DELETE) |
| Membros | `/api/membros/` | `/api/membros/<id>/` (GET, PUT, PATCH, DELETE) |
| Empréstimos | `/api/emprestimos/` | `/api/emprestimos/<id>/` (GET) |
| Reservas | `/api/reservas/` | `/api/reservas/<id>/` (GET) |

Empréstimos e reservas não são editados nem apagados; mudam por ações (POST), que seguem
as mesmas regras das telas:

- `/api/emprestimos/<id>/devolver/` (aceita `data_devolucao`; em branco, hoje)
- `/api/emprestimos/<id>/pagar-multa/`
- `/api/reservas/<id>/cancelar/`

O dashboard também sai em JSON, em `/api/dashboard/` (GET), com período opcional
(`?de=AAAA-MM-DD&ate=AAAA-MM-DD`, as duas datas). A série `por_mes` só vem para o administrador.

Exige login (sessão ou autenticação básica) e só enxerga os dados da organização do usuário.
No navegador, entre pelo próprio sistema ou por `/api-auth/login/`. No terminal:

```bash
curl -u SEU_USUARIO http://127.0.0.1:8000/api/livros/   # o curl pede a senha
```

## Testes

```bash
python manage.py test acervo
```

Cobrem multa, bloqueios de empréstimo, ordem da fila, expiração/cancelamento de reserva e as telas principais.

## Estrutura

```
biblioteca/          configurações do projeto (settings, urls)
acervo/
  models.py          as 6 entidades
  regras.py          regras de empréstimo, multa e fila de reserva
  forms.py           ModelForms
  views.py           uma view por tela (lista, detalhe, novo, editar, excluir...)
  urls.py            rotas do app (criado à mão, o startapp não gera)
  templates/acervo/  base.html + telas (herança de templates)
  static/acervo/     estilo.css
  management/        comando popular_dados
  tests.py
```
