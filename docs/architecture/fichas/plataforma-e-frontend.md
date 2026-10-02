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
  - [x] Mais de uma responsabilidade: `request`/erros/flags de sessão (linhas 1–139), o objeto `api` com todas as chamadas (140–499, ~110 métodos) e os tipos de todos os domínios (500–1272).
  - [ ] demais: não. A regra "só o `api.ts` faz `fetch`" é seguida em todas as telas.
- **Churn:** 70 (o maior do repositório) | **Linhas:** 1272
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
- **Violações encontradas:** tamanho (761 linhas, 34 tabelas), mas é uma lista declarativa sem lógica.
- **Churn:** 34 | **Linhas:** 761
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
- **Violações encontradas:** nenhuma. Em 26/09 só tinha `agora_br` e `hoje_br`, com as conversões de fuso copiadas em 8 arquivos; o backlog #10 (PR #5) trouxe `para_br`, `dia_br`, `hora_br`, `utc_ingenuo`, `inicio_do_dia_utc` e `inicio_hoje_utc` para cá, e as cópias saíram (inclusive `services/compras_seta._dia_br`, criada depois e removida em 27/09).
- **Churn:** 1 | **Linhas:** 62

### `apps/backend/app/utils/*`, `cache.py`, `config.py`, `database.py`
- **`cache.py` (proteção do SETA):** dono de duas regras: um cálculo por chave (single-flight, trava com dono + batimento, fila limitada, quarentena de erro) e o formato do *snapshot* (`gerado_em`, `velho`). Não conhece relatório nenhum: quem chama passa a chave (`cache.chave`) e a função que calcula. O limite global de consultas pesadas fica em `seta_client.consulta_pesada` (config `SETA_MAX_CONSULTAS_PESADAS`). Teste: `tests/test_protecao_seta.py` (13 cenários que contam as chamadas ao SETA).
- **Violações encontradas:** nenhuma. `utils/` não importa `models` nem FastAPI (a regra 5 está travada no CI pelo contrato `regras-puras` do `.importlinter`).
