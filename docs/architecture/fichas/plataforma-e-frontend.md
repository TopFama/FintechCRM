# Fichas — Plataforma e Frontend

Arquivos compartilhados por todos os domínios. São os que mais mudam, mas quase sempre porque
uma feature de algum domínio precisou de um campo novo: o co-change mais forte do repositório é
`schemas.py` ↔ `api.ts` (39 commits juntos), seguido de `models.py` ↔ `schemas.py` (24).

### `apps/frontend/src/api.ts`
- **Domínio:** Plataforma (frontend)
- **Camada:** infraestrutura (cliente HTTP) + tipos de todos os domínios
- **Responsabilidade (1 frase, sem "e"):** falar com o backend.
- **Motivos para mudar:** qualquer endpoint ou campo novo de qualquer tela.
- **Depende de:** nada interno.
- **É usado por:** todas as páginas e componentes.
- **Violações encontradas:**
  - [x] Mais de uma responsabilidade: `request`/erros/flags de sessão (linhas 1–139), o objeto `api` com todas as chamadas (140–497, ~110 métodos) e os tipos de todos os domínios (498–1269).
  - [ ] demais: não. A regra "só o `api.ts` faz `fetch`" é seguida em todas as telas.
- **Churn:** 70 (o maior do repositório) | **Linhas:** 1269
- **Ação sugerida:** dividir em `api/cliente.ts` (request, `ApiError`, sessão) e um arquivo por domínio com os tipos e as chamadas, mantendo `api.ts` como reexportação para nenhuma página precisar mudar de import (backlog #9).
- **Esforço:** M | **Risco:** baixo (o `tsc` pega qualquer erro; e2e cobre as telas)

### `apps/frontend/src/pages/Relatorios.tsx`
- **Domínio:** Dashboard/Relatórios
- **Camada:** interface
- **Responsabilidade:** mostrar os relatórios.
- **Violações encontradas:**
  - [x] Mais de uma responsabilidade: as cinco abas (Pendentes, Envios, Erros, Telefones inválidos, Quem pagou) com filtros, paginação e ações num arquivo de 871 linhas.
- **Churn:** 21 | **Linhas:** 871
- **Ação sugerida:** um componente por aba em `components/relatorios/`. Baixa prioridade.

### `apps/frontend/src/pages/Configuracoes.tsx`, `CampanhaDetail.tsx`
- **Violações encontradas:** tamanho (626 e 615 linhas); `Configuracoes` já delega para `components/config/*`.
- **Churn:** 23 / 5
- **Ação sugerida:** nenhuma agora.

### `apps/backend/app/schemas.py`
- **Domínio:** Plataforma
- **Camada:** interface (contratos HTTP)
- **Responsabilidade:** declarar request/response da API.
- **Violações encontradas:**
  - [x] Mais de uma responsabilidade: todos os domínios num arquivo (1033 linhas). Já é separado por blocos `# --- Área ---`, o que ameniza.
  - [x] Alguns routers declaram schema próprio dentro do arquivo (`routers/campanhas.py`, `routers/remarketing.py`), fugindo da convenção do AGENTS.md.
- **Churn:** 56 | **Linhas:** 1033
- **Ação sugerida:** pacote `schemas/` com um módulo por domínio reexportado em `schemas/__init__.py` (backlog #5). Baixa prioridade: o custo hoje é conflito de merge, não bug.

### `apps/backend/app/models.py`
- **Domínio:** Plataforma
- **Camada:** infraestrutura
- **Responsabilidade:** declarar as tabelas.
- **Violações encontradas:** tamanho (732 linhas, 32 tabelas), mas é uma lista declarativa sem lógica.
- **Churn:** 34 | **Linhas:** 732
- **Ação sugerida:** nenhuma. Separar em pacote só se `schemas` for separado e fizer sentido espelhar.

### `apps/backend/app/main.py`
- **Domínio:** Plataforma
- **Camada:** interface (bootstrap)
- **Responsabilidade:** montar a aplicação.
- **Violações encontradas:** nenhuma (migrations, checagem de segredos, admin, worker, registro dos routers).
- **Churn:** 23 | **Linhas:** 162

### `apps/backend/app/timezone.py`
- **Domínio:** Plataforma
- **Camada:** domínio (utilitário)
- **Responsabilidade:** dizer que horas são em Brasília.
- **Violações encontradas:**
  - [x] Incompleto: só tem `agora_br` e `hoje_br`. As conversões "dia de Brasília → início em UTC ingênuo" e "UTC ingênuo → dia/hora de Brasília" estão copiadas em 8 arquivos: `routers/reports.py` (`_inicio_utc`, `_hora_br`), `routers/leads.py` (`_inicio_utc`), `routers/dashboard.py` (`_limites_utc`), `services/pagamentos_service.py` (`_inicio_utc`, `_dia_br`), `services/efetividade_service.py` (`_inicio_dia_utc`, `_dia_br`), `services/pagamentos_seta.py` (`_dia_br`), `fila_automatica.py` (`_utc_ingenuo`, `inicio_hoje_utc`), `worker.py` (`_local_now`).
- **Churn:** 1 | **Linhas:** 22
- **Ação sugerida:** `inicio_do_dia_utc(dia)`, `dia_br(dt_utc)`, `hora_br(dt_utc)`, `para_br(dt_utc)` aqui, e as cópias passam a chamar essas (backlog #10). Protege a regra fixa de GMT-3.
- **Esforço:** P | **Risco:** baixo

### `apps/backend/app/utils/*`, `cache.py`, `config.py`, `database.py`
- **Violações encontradas:** nenhuma. `utils/` não importa `models` nem FastAPI (a regra 5 já vale; só falta travar no CI).
