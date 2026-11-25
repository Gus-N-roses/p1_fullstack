# Melhorias da P1

Pontos frágeis herdados pela P2, em ordem de prioridade.

## 1. Senhas previsíveis em migração

**Problema:** a migração `0006_organizacoes_e_usuarios` cria dois superusuários cuja senha é
igual ao nome de usuário, e o código fica visível no repositório.

**Correção:** trocar as senhas, deixar de defini-las na migração e criar os usuários de
demonstração sem privilégio de superusuário.

## 2. Unicidade global em um sistema multi-organização

**Problema:** `Livro.isbn`, `Exemplar.codigo`, `Membro.cpf` e `Membro.email` são únicos no banco
inteiro. Uma biblioteca não consegue cadastrar um livro ou um membro que outra já cadastrou.

**Correção:** trocar `unique=True` por `UniqueConstraint` de `organizacao` com o campo, e validar
a duplicidade nos formulários.

## 3. Validações presas aos formulários

**Problema:** as validações de ISBN e CPF existem só em `forms.py`, então não valem no Admin e
não valeriam na API. Elas também são fracas: o CPF confere apenas a quantidade de dígitos, e o
ISBN aceita qualquer caractere na última posição.

**Correção:** mover para validadores usados pelo model e conferir os dígitos verificadores.

## 4. Admin ignora as regras de negócio

**Problema:** pelo Admin é possível criar empréstimos e reservas sem passar por `regras.py`
(multa pendente, limite, fila) e relacionar registros de organizações diferentes, por exemplo
um membro de uma biblioteca com um exemplar de outra.

**Correção:** validar no `clean()` dos models que os registros relacionados são da mesma
organização, e fazer o Admin usar as funções de `regras.py` ou deixar empréstimos e reservas
somente para leitura.

## 5. Exclusão de uma organização em cascata

**Problema:** as chaves para `Organizacao` usam `on_delete=models.CASCADE`. Excluir uma
organização pode apagar de uma vez os perfis e o acervo dela.

**Correção:** usar `on_delete=models.PROTECT`.
