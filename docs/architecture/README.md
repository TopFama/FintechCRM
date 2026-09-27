# Arquitetura do FintechCRM

Pasta do review de responsabilidade por arquivo: o que cada arquivo faz hoje, onde ele deveria
morar e o roteiro para chegar lá sem mudar comportamento. Fotografia inicial tirada em 26/09/2026
sobre `main` no commit `f0a3726`; `churn.txt`, `tamanho.txt`, `co-change.txt`, `deps.svg` e os
números de cobertura são dessa data. O texto (estrutura, fichas e backlog) é mantido em dia com o
código a cada PR (ver AGENTS.md → "Documentação").

| Arquivo | O que tem |
|---|---|
| [`dominios-e-camadas.md`](./dominios-e-camadas.md) | Mapa-alvo: domínios, camadas e regras de dependência (a régua do review) |
| [`churn.txt`](./churn.txt) | Os 30 arquivos que mais mudaram (commits) |
| [`tamanho.txt`](./tamanho.txt) | Os 30 maiores arquivos de código (linhas) |
| [`co-change.txt`](./co-change.txt) | Os 30 pares de arquivos que mais mudam juntos |
| [`deps.svg`](./deps.svg) | Grafo de imports do backend agrupado por domínio (vermelho = viola camada) |
| [`fichas/`](./fichas/) | Ficha de responsabilidade por arquivo, um arquivo por domínio |
| [`backlog-refatoracao.md`](./backlog-refatoracao.md) | Backlog priorizado, um item por PR |
| [`scripts/grafo_dependencias.py`](./scripts/grafo_dependencias.py) | Regera o `deps.svg` |

## Stack

**Backend** (`apps/backend`), Python 3.12:

- FastAPI 0.141 / Starlette 1.7 com Uvicorn; rotas em `app/routers/`, uma por área.
- SQLAlchemy 2.0 (ORM, `Mapped[...]`) sobre Postgres 16, via psycopg 3. Migrations com Alembic.
- Pydantic 2 para request/response (`app/schemas.py`) e pydantic-settings para o `.env`.
- APScheduler dentro do mesmo processo da API (`app/worker.py`): ciclo de disparo a cada
  `DISPATCH_WORKER_INTERVAL_SECONDS`, conferência dos pagamentos do SETA a cada minuto (lê o SETA
  só com alguém usando o CRM e no máximo a cada `PAGAMENTOS_SYNC_INTERVAL_SECONDS`) e cópia das
  compras do SETA às 03:00 (GMT-3). Não há fila externa (Celery, RQ): a "fila" é a tabela
  `cobranca_fila` (modelo `QueueItem`).
- Redis: cache das consultas pesadas ao SETA e do Dashboard (`app/cache.py`).
- Autenticação por JWT em cookie httpOnly (python-jose), senha com bcrypt (passlib), tokens
  revogados em tabela e limite de tentativas por conta e por dispositivo.
- Segredos no banco cifrados com Fernet (`app/crypto.py`, `ENCRYPTION_KEY`).
- Planilhas só em .xlsx, com openpyxl (sem pandas, sem CSV).
- Imagem de cabeçalho de template conferida/comprimida com Pillow (`app/utils/imagem.py`).

**Frontend** (`apps/frontend`): React 18 + TypeScript + Vite, React Router 7, CSS próprio com
variáveis (`styles.css`), sem biblioteca de UI nem de ícones.

**Integrações de envio e dados**:

| Integração | Módulo | Para quê |
|---|---|---|
| Meta WhatsApp Cloud API (Graph API) | `meta_client.py` | Templates, números, envio de template, mídia, pricing analytics |
| Chatwoot | `chatwoot_client.py` | Envio pelo inbox do Chatwoot quando o número tem inbox vinculada |
| SETA (ERP, Postgres de produção) | `seta_client.py` | Base de cobrança, parcelas, SPC, baixas e compras (faixa de compra). Só `SELECT`, conexão read-only |
| TopFamaRenegocie (HTTP interno) | `remarketing.py` (inline; `routers/remarketing.py` só captura `httpx.HTTPError`) | Clientes do remarketing |
| Google Sheets (OAuth2) | `google_client.py` | Planilha de lojas |
| Câmbio USD→BRL | `cambio.py` | AwesomeAPI, PTAX do BCB e open.er-api, com fallback |

Não há e-mail nem SMS: o único canal de envio é WhatsApp (Meta direta ou via Chatwoot).

## Estrutura de pastas atual

```
apps/backend/app/
  main.py, config.py, database.py        bootstrap, settings, engine
  models.py (761 linhas)                 todas as tabelas
  schemas.py (1033 linhas)               todos os modelos Pydantic
  deps.py, security.py, rate_limit.py    autenticação
  routers/        20 routers + comum.py   uma área por arquivo (reports.py tem 858 linhas);
                                          comum.py = peças HTTP compartilhadas, sem rota
  services/       6 arquivos              pagamentos, compras, efetividade, custo do WhatsApp
  utils/          7 arquivos              telefone, documento, planilhas, xlsx, leads, SPC, imagem
  *.py na raiz    38 módulos              serviços informais: fila_automatica, dispatch_service,
                                          elegibilidade, itens_fila, upload_service, consultas_fila,
                                          blacklist, pausas, campanhas, remarketing, cobranca_base,
                                          lojas, variaveis_template, clientes das integrações…
  alembic/                               migrations
apps/backend/tests/   14 scripts de validação + rodar_todos.sh (não é pytest: cada um imprime OK)
apps/frontend/src/
  api.ts (1272 linhas)                   todo o acesso ao backend e todos os tipos
  pages/          10 páginas              Relatorios.tsx tem 871 linhas
  components/     config/, dashboard/ e componentes soltos
e2e/                                     Playwright: 174 cenários (+ login de setup) contra ambiente de teste
```

A camada de serviço existe, mas de forma informal: parte está em `services/`, a maior parte em
módulos soltos na raiz de `app/`. Não existe camada de repositório: routers e serviços usam a
`Session` do SQLAlchemy direto.

## Como os testes rodam hoje

**Backend**: 14 scripts em `apps/backend/tests/`, cada um sobe o app de verdade (migrations
incluídas) contra um Postgres local e imprime `OK`. Precisam de Postgres UTF-8 em
`localhost:15432` com senha `t`, e cada script usa o próprio banco (nome no `DATABASE_URL` do
arquivo), que deve ser recriado antes:

```bash
cd apps/backend
PYTHONPATH=. .venv/bin/python tests/test_regras.py
```

Todos de uma vez, recriando cada banco: `./tests/rodar_todos.sh` (é o que o CI roda).

Em 26/09/2026 os 10 scripts que existiam passavam. **Cobertura de linhas do pacote `app` só com esses scripts: 60%**
(6896 instruções, 2728 não executadas; medido com `coverage run -p --source=app` em cada script
e `coverage combine`). Os pontos mais descobertos são justamente os de maior risco:

| Módulo | Cobertura |
|---|---|
| `campanhas.py` | 18% |
| `remarketing.py` | 20% |
| `routers/dashboard.py` | 24% |
| `routers/pausas.py` | 27% |
| `routers/campanhas.py` | 30% |
| `fila_automatica.py` | 37% |
| `worker.py` | 48% |
| `routers/reports.py` | 61% |
| `dispatch_service.py` | 80% |

**E2E**: `e2e/` com Playwright, 174 cenários (mais o login de setup) que cobrem essas telas pelo navegador (ver
`e2e/README.md`). Não entram na medição de cobertura acima.

**CI**: no momento da análise só existia `security-scan.yml` (npm audit e pip-audit). A Fase 5
(PR #2) acrescentou `testes.yml` (scripts do backend, build do frontend e e2e em todo PR) e a
Fase 7 (PR #9) o job de regras de import (`apps/backend/.importlinter`).

## Como regerar os números

Da raiz do repositório:

```bash
# churn (arquivos que mais mudam)
git log --since="1 year ago" --name-only --format="" | grep -v '^$' | sort | uniq -c | sort -rn | head -30 > docs/architecture/churn.txt

# tamanho
find apps e2e/ambiente e2e/tests -path '*/node_modules' -prune -o -path '*/.venv' -prune \
  -o -path '*/alembic/versions' -prune -o -type f \( -name "*.py" -o -name "*.ts" -o -name "*.tsx" \) -print \
  | xargs wc -l | sort -rn | head -31 > docs/architecture/tamanho.txt

# co-change (README/AGENTS/.env.example fora: mudam junto com tudo)
git log --since="1 year ago" --name-only --format="tformat:---" \
  | awk '/^---$/{if(n>1)for(i in f)for(j in f)if(i<j)print i" <-> "j; delete f; n=0; next} NF{f[$0]; n++} END{if(n>1)for(i in f)for(j in f)if(i<j)print i" <-> "j}' \
  | grep -v "README.md\|AGENTS.md\|\.env.example" | sort | uniq -c | sort -rn | head -30 > docs/architecture/co-change.txt

# grafo (precisa do Graphviz)
python3 docs/architecture/scripts/grafo_dependencias.py
```

Observação: o histórico do repositório começa em 18/09/2026, então "1 ano" é o histórico
inteiro (181 commits). O comando de co-change do plano original usava `--format="---"`, que o
git recusa; aqui vai `tformat:---`. Pastas `src/` do plano viraram `apps/`, que é onde o código
mora.

## Manutenção (Fase 8)

**Em todo PR**: o modelo `.github/pull_request_template.md` traz o checklist (arquivo com uma
responsabilidade só, domínio e camada certos, regra fixa preservada, refatoração sem mudança de
comportamento). O CI confere o que dá para conferir sozinho: testes, caracterização do envio e
regras de import.

**Uma vez por mês**:

1. Regerar `churn.txt`, `tamanho.txt`, `co-change.txt` e `deps.svg` com os comandos acima.
2. Comparar os 10 primeiros do churn com o backlog: arquivo novo no topo ganha ficha e item; item
   que saiu do topo desce na prioridade.
3. Recalcular os pontos da tabela do backlog com o churn novo e atualizar a tabela "Estado".
4. Rever as exceções em `apps/backend/.importlinter` (`ignore_imports`): exceção cujo item do
   backlog já foi feito sai do arquivo.
5. Tudo isso num PR só, `docs: revisão mensal de hotspots (mês/ano)`.
