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

# 5. servidor
python manage.py runserver
```

Acesse http://127.0.0.1:8000 (sistema) e http://127.0.0.1:8000/admin (Django Admin).

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
