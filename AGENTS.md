# AGENTS.md — guia para agentes de IA neste repositório

Este arquivo é para agentes de codificação (Claude Code, Codex, Copilot, etc.) que forem alterar
este repositório. Ele não substitui o [`README.md`](./README.md) — que explica o produto, como
rodar e como configurar — só complementa com convenções e checagens específicas para quem vai
editar o código.

## O que é o projeto

CRM de cobrança via WhatsApp da TopFama: importa planilha de clientes em atraso, manda mensagens
de template pela API oficial da Meta (WhatsApp Business Cloud API), e acompanha fila/relatórios de
envio. Backend em FastAPI + SQLAlchemy + Postgres, frontend em React + TypeScript + Vite. Veja
`README.md` → "Fluxo do sistema" para o funcionamento fim a fim antes de mexer em qualquer coisa.

## Onde fica cada coisa

**Backend** (`apps/backend/app/`):
- `models.py` — todas as tabelas (SQLAlchemy 2.0, `Mapped[...]`). Mudou aqui? Precisa de migration
  (ver "Antes de considerar uma mudança pronta" abaixo).
- `schemas.py` — modelos Pydantic de request/response, um bloco por área (comentários `# --- Área
  ---` separam).
- `routers/` — um arquivo por área: `auth`, `users`, `meta_tokens`, `numbers`, `templates`,
  `faixas`, `uploads`, `dashboard`, `reports` (montado em `/relatorios` e `/reports`), `seta`,
  `blacklist`, `cobranca`, `config_cobranca`, `leads`, `google`, `lojas`, `chatwoot`,
  `remarketing`, `campanhas`, `pausas`; `comum.py` não é router, só peças HTTP compartilhadas.
  Rotas novas de uma área existente entram no arquivo dela; router novo precisa ser registrado em
  `main.py` e entrar nas listas de `apps/backend/.importlinter`.
- Regras de domínio ficam em módulos soltos de `app/` e em `app/services/` (mapa completo em
  `docs/architecture/dominios-e-camadas.md`); os mais tocados: `elegibilidade.py` (quem entra/sai
  da fila, uma cobrança por cliente por dia), `dispatch_service.py` (envio de um item),
  `upload_service.py` (import da planilha), `fila_automatica.py`, `campanhas.py`,
  `campanhas_fixas.py`, `remarketing.py`, `pausas.py`, `blacklist.py`, `cobranca_base.py`/
  `cobranca_regras.py`.
- `meta_client.py` — **único** ponto de integração com a Graph API da Meta. Qualquer chamada nova
  à Meta entra aqui, nunca direto num router. Mesma regra para `seta_client.py` (ERP SETA, só
  leitura), `google_client.py` (OAuth2 + Sheets) e `chatwoot_client.py` (envio pelo Chatwoot).
- `worker.py` — agendamento do disparo e das rotinas diárias, roda com APScheduler **dentro do
  mesmo processo** do backend (não é um serviço/container separado); o envio de cada item em si
  fica em `dispatch_service.py`.
- `utils/phone.py` — normalização/validação de telefone (formato final `55DD9XXXXXXXX`).
- `utils/document.py` — normalização dos campos obrigatórios de identificação do cliente:
  código SETA (até 8 dígitos, completa com zero à esquerda), CPF (formata com pontos/traço,
  completa com zero à esquerda) e nome (reduz para o primeiro nome).
- `utils/spreadsheet.py` — leitura de .xlsx (sem pandas, usa `openpyxl`) e geração do modelo de
  planilha para download. `utils/xlsx.py` gera os .xlsx exportáveis (relatórios, cobrança,
  dashboard) com proteção contra injeção de fórmula; `utils/leads_xlsx.py` exporta leads e
  formata código/CPF/nome/celular. Não há CSV em lugar nenhum do sistema — todo upload/download
  de planilha é em Excel (.xlsx).
- `utils/spc.py` — leitura do texto da consulta SPC guardado no SETA.
- `alembic/` — migrations. Ver seção própria abaixo.

**Frontend** (`apps/frontend/src/`):
- `api.ts` — único lugar que fala com o backend: wrapper de `fetch` + todos os tipos TypeScript
  espelhando os schemas do backend. Endpoint novo no backend → método novo aqui, não `fetch` direto
  numa página.
- `pages/` — uma página por rota (`Login`, `Dashboard`, `Cobranca`, `Campanhas`, `CampanhaDetail`,
  `Relatorios`, `Configuracoes`, `FaixaWizard`, `FaixaDetail`); `Faixas` é renderizada dentro da
  aba Faixas de Configurações. Templates, Blacklist, Usuários, Lojas, Horário etc. são abas de
  `Configuracoes` (`?aba=...`), com os cards em `components/config/`; as rotas antigas
  (`/templates`, `/blacklist`, `/usuarios`, `/faixas`, `/leads`, `/remarketing`) só redirecionam
  (ver `App.tsx`).
- `components/` — peças reaproveitadas entre páginas; `components/dashboard/` tem os cards do
  Dashboard.
- `styles.css` — todo o design vive aqui: tokens em `:root` (cores, espaçamento, sombra) e classes
  utilitárias reaproveitadas entre páginas (`.card`, `.badge`, `.form-row`, `.stat`, etc.). Não é
  CSS Modules nem styled-components.
- `icons.tsx` — ícones inline SVG feitos à mão, sem lib de ícones externa.
- `public/topfama-logo.png` — logo oficial da marca (fundo transparente); é o que aparece na
  sidebar e no login.

## Convenções

- **Domínio em português**, sempre: nomes de tabela/coluna, nomes de variável no código de
  domínio, texto de UI, mensagens de erro para o usuário. Não traduza para inglês (`faixa`,
  `cobranca_fila`, `codigo_cliente`, "faixa de atraso" continuam em português mesmo em código
  novo). Nomes genéricos de infraestrutura (`request`, `session`, `router`) seguem em inglês, como
  já está.
- Comentários de código em português, curtos, só quando explicam uma decisão não óbvia (o *por
  quê*, não o *o quê* — o código já diz o quê).
- Sem framework de UI novo (não introduza Tailwind, MUI, Chakra, styled-components etc.) — segue o
  `styles.css` existente com CSS vars. Sem lib de ícones (`lucide-react`, `react-icons`) — adicione
  em `icons.tsx` no mesmo estilo dos existentes.
- Sem dependência nova de frontend ou backend a menos que o pedido realmente precise — este é um
  projeto pequeno de propósito único, prefira resolver com o que já está instalado.
- PRs/commits: mensagens em português. Quando a mudança altera comportamento visível, o padrão
  usado no histórico é um parágrafo "Antes" e um "Depois" descrevendo o efeito, não a
  implementação — veja `git log` para exemplos.

## Antes de considerar uma mudança pronta

**Backend:**
1. Ambiente: `cd apps/backend && python3 -m venv .venv && .venv/bin/pip install -r requirements.txt`.
2. Os scripts de `tests/` rodam todos com `./tests/rodar_todos.sh` (Postgres em
   `localhost:15432`, senha `t`) e rodam no CI em todo PR (`.github/workflows/testes.yml`,
   junto com o build do frontend e o e2e). `tests/test_caracterizacao_envios.py` fotografa o
   fluxo de envio (fila, pausa, blacklist, uma mensagem por cliente por dia): se ele falhar
   depois de uma mudança que não devia mexer em comportamento, investigue antes de ajustar o
   teste. As regras de import entre camadas (nenhum módulo importa router, router não importa
   router, regras puras sem infraestrutura, `deps.py` só autentica, HTTP externo só nos clientes)
   estão em `apps/backend/.importlinter` e rodam no CI: `pip install import-linter && lint-imports`
   dentro de `apps/backend`. Há também a suíte e2e com Playwright em `e2e/` (ver
   `e2e/README.md`), que roda no CI. Fora isso, a validação é exercitar os endpoints tocados via
   `fastapi.testclient.TestClient` (ele passa pelo `lifespan` de verdade: roda as migrations e cria
   o admin, igual a produção). SQLite (`DATABASE_URL=sqlite:///...`) serve para uma checagem rápida
   de que nada quebrou; para qualquer coisa envolvendo `Enum` ou tipos específicos do Postgres,
   valide contra Postgres de verdade antes de dar por encerrado.
3. **Mudou `models.py`?** Gere a migration (`alembic revision --autogenerate -m "..."` dentro de
   `apps/backend`) e **revise o arquivo gerado à mão** — autogenerate não pega tudo. Valide o ciclo
   `alembic upgrade head` → `alembic downgrade base` → `alembic upgrade head` contra um Postgres
   real e rode `alembic check` para confirmar que não sobrou diff nenhum contra `models.py`. Ver
   `README.md` → "Migrations (Alembic)" para o passo a passo completo e a pegadinha do ENUM do
   Postgres (próxima seção).

**Frontend:**
1. `cd apps/frontend && npm install && npm run build` (roda `tsc -b && vite build`) — pega a
   maioria dos erros de tipo/import quebrado. Trate qualquer erro do build como bloqueante.
2. Mudança visual: rodar `npx vite preview` sobre o `dist/` e tirar um screenshot (Playwright com
   Chromium já instalado no ambiente do agente, ver `PLAYWRIGHT_BROWSERS_PATH`) é a forma mais
   confiável de confirmar que ficou como esperado antes de reportar como pronto.
3. Delete `dist/`, `node_modules/` e `tsconfig.tsbuildinfo` do working tree antes de commitar
   (já estão no `.gitignore`, mas confira `git status` mesmo assim).

**Documentação (obrigatório, em toda task e antes de todo commit):**

Ao finalizar **qualquer** task e **antes de qualquer commit**, confira se a mudança deixou algum
documento desatualizado e atualize-o **no mesmo commit** do código. A documentação tem que
continuar 100% condizente com o código — documento que descreve algo que não existe mais é bug.

1. Rode `git diff --name-only` (ou `git diff --cached --name-only`) e, para cada área tocada,
   revise os documentos que falam dela:
   - `README.md` — estrutura do monorepo, tabela de variáveis de ambiente (compare com
     `app/config.py`, `.env.example` e `docker-compose.yml`), fluxo do sistema, rotas citadas,
     testes/CI e limitações conhecidas.
   - `AGENTS.md` (este arquivo) — "Onde fica cada coisa" (routers, módulos, utils, páginas,
     componentes), convenções, validação e cuidados conhecidos.
   - `.env.example` — toda variável nova/renomeada/removida em `app/config.py` ou no
     `docker-compose.yml`, com comentário coerente com o README.
   - `docs/architecture/` — `dominios-e-camadas.md` e a ficha da área em `fichas/` quando mudar
     módulo, dono de regra ou dependência entre camadas; `backlog-refatoracao.md` quando um item
     for feito (marque como feito) ou surgir um novo.
   - `apps/backend/.importlinter` — módulo ou router novo entra nas listas dos contratos.
   - `e2e/README.md` e `GEMINI.md` — quando mudar como rodar a suíte e2e ou os comandos de
     validação e convenções que eles repetem.
2. Procure referências ao que você renomeou/removeu (`grep -rn "nome_antigo" README.md AGENTS.md
   GEMINI.md .env.example docs e2e/README.md`) e corrija todas.
3. Não documente o que não existe: toda afirmação nova sobre o código (arquivo, rota, tabela,
   variável, default, intervalo) tem que ser conferida no código antes de escrever.
4. Se a mudança não afeta nenhum documento, diga isso explicitamente no resumo final da task.

## Cuidados conhecidos

- **Enum + Postgres + Alembic**: o `downgrade()` gerado por autogenerate não derruba o tipo ENUM
  nativo por trás de uma coluna `Enum` (`drop_table` não faz isso sozinho) — sem o
  `sa.Enum(name=...).drop(bind, checkfirst=True)` explícito, um `upgrade` seguinte falha com "type
  already exists". Ver `alembic/versions/3bd1d89aa92f_baseline_schema_atual.py` como referência.
- **Não reintroduza `Base.metadata.create_all()`** — foi substituído por Alembic de propósito; toda
  mudança de schema passa por migration.
- O worker de disparo roda no mesmo processo do backend; não assuma um serviço/fila separada.
- Imagem de header de template: pela Meta vai como `media_id` (não precisa de URL pública); pelo
  Chatwoot precisa de link público (ver `README.md` → "Limitações conhecidas"). Teste:
  `tests/test_imagem_template.py`.
- Upload de planilha (`POST /faixas/{id}/uploads`) é em duas etapas: primeiro lê só o cabeçalho
  (`/uploads/columns`), o frontend monta o mapeamento variável→coluna real e só então confirma o
  import — não assuma nomes de coluna fixos como "nome"/"celular".
- **ENCRYPTION_KEY e segredos no banco**: tokens da Meta e refresh token do Google são cifrados
  com Fernet usando `ENCRYPTION_KEY` (e chave legada derivada de `JWT_SECRET` para transição).
  Na subida do backend, `app/segredos.py` re-cifra automaticamente segredos pendentes. Token da Meta
  **nunca** vem do ambiente: só da tabela `meta_tokens` (tela Configurações). A `ENCRYPTION_KEY` é obrigatória e deve ser
  mantida junto com o backup do banco.

## Referências

- Visão funcional completa, variáveis de ambiente e como configurar a API da Meta: `README.md`.
- Migrations: `README.md` → "Migrations (Alembic)".
- Limitações conhecidas e próximos passos combinados: `README.md` → "Limitações conhecidas /
  próximos passos".
