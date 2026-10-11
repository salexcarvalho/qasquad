---
epic: A01
titulo: Autenticação e acesso
parte: A
atualizado_em: 2026-10-11
personas: [admin, escotista, responsavel]
status_implementacao: Parcial
---

# A01 — Autenticação e acesso

Escopo: entrar no sistema e manter a sessão. Fixture de teste no formato do pacote de histórias.

---

### US-A01-01 — Entrar com e-mail e senha
**Persona:** admin, escotista, responsavel · **Prioridade:** Must · **Status:** Implementado

Como usuário de um grupo, quero entrar com e-mail e senha para acessar a área do meu perfil.

**Critérios de aceite**
```gherkin
Cenário: Login válido
  Dado um usuário ativo com e-mail e senha corretos
  Quando ele envia o formulário de login
  Então ele chega à página inicial
  E a sessão é criada

Cenário: Credenciais inválidas
  Dado um usuário ativo
  Quando ele informa uma senha errada
  Então vê a mensagem "Credenciais inválidas"
  Mas continua na tela de login
```
**Regras de negócio e permissões:** o grupo é descoberto pelo usuário autenticado.
**Testes:** `e2e/01-login.spec.ts`.

---

### US-A01-02 — Recuperar a senha por e-mail
**Persona:** admin, escotista · **Prioridade:** Should · **Status:** Parcial

Como usuário que esqueceu a senha, quero receber um link por e-mail para criar uma nova senha.

**Critérios de aceite**
```gherkin
Cenário: Pedido de link
  Dado um e-mail cadastrado
  Quando o usuário pede o link de recuperação
  Então vê uma confirmação neutra

Esquema do Cenário: Senha curta
  Dado o link de recuperação válido
  Quando ele informa a senha "<senha>"
  Então vê o erro de política de senha

  Exemplos:
    | senha |
    | abc   |
    | 1234  |
```
**Regras de negócio e permissões:** link expira em 1 hora.

---

### US-A01-03 — Sair com segurança
**Persona:** todos · **Prioridade:** Must · **Status:** Implementado

Como usuário, quero encerrar a sessão para que ninguém use meu acesso.

**Critérios de aceite**
- O botão Sair encerra a sessão e volta ao login
- O refresh token anterior deixa de funcionar

**Observações:** sem teste (GAP).

## Perguntas abertas

- Política única de senha: A confirmar.
