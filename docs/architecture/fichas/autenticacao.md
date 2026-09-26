# Fichas — Autenticação

**Autorização:** a regra "qualquer usuário logado pode pausar/parar envios" está num lugar só:
todas as rotas usam a dependência `get_current_user` (ou `require_admin`, só para conexão, segmentos e
execução manual do remarketing e para usuários). Não há checagem de permissão duplicada dentro
das rotas.

### `apps/backend/app/deps.py`
- **Domínio:** Autenticação
- **Camada:** interface (dependência do FastAPI)
- **Responsabilidade:** identificar o usuário da requisição.
- **Depende de:** `database`, `models`, `security`, `services.pagamentos_seta` (!).
- **Violações encontradas:**
  - [x] Acesso a outro domínio: chama `pagamentos_seta.registrar_atividade()` em toda requisição (é o que faz a cópia do SETA só rodar com alguém usando o CRM).
- **Churn:** 5 | **Linhas:** 45
- **Ação sugerida:** mover o registro de atividade para um middleware HTTP em `main.py`, com a mesma regra de ignorar `?auto=true` (backlog #16). Atenção: hoje só conta requisição autenticada; o middleware tem que manter isso.
- **Esforço:** P | **Risco:** baixo

### `apps/backend/app/routers/auth.py`, `routers/users.py`, `security.py`, `rate_limit.py`
- **Domínio:** Autenticação
- **Camada:** interface / infraestrutura
- **Violações encontradas:** nenhuma relevante. `rate_limit` guarda tentativas em memória do processo (um processo só, como hoje).
- **Churn:** 5 / 2 / 3 / 2 | **Linhas:** 100 / 59 / 78 / 37
