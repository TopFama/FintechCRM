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
- `routers/` — um arquivo por área: `auth`, `numbers`, `templates`, `faixas`, `uploads`,
  `dashboard`, `reports`. Rotas novas de uma área existente entram no arquivo dela.
- `meta_client.py` — **único** ponto de integração com a Graph API da Meta. Qualquer chamada nova
  à Meta entra aqui, nunca direto num router.
- `worker.py` — worker de disparo, roda com APScheduler **dentro do mesmo processo** do backend
  (não é um serviço/container separado).
- `utils/phone.py` — normalização/validação de telefone (formato final `55DD9XXXXXXXX`).
- `utils/document.py` — validação de código do cliente (SETA de 8 dígitos ou CPF com dígito
  verificador).
- `utils/spreadsheet.py` — leitura de CSV/XLSX (sem pandas, usa `openpyxl` + `csv` da stdlib) e
  geração do modelo de planilha para download.
- `alembic/` — migrations. Ver seção própria abaixo.

**Frontend** (`apps/frontend/src/`):
- `api.ts` — único lugar que fala com o backend: wrapper de `fetch` + todos os tipos TypeScript
  espelhando os schemas do backend. Endpoint novo no backend → método novo aqui, não `fetch` direto
  numa página.
- `pages/` — uma página por rota (`Login`, `Dashboard`, `Numbers`, `Templates`, `Faixas`,
  `FaixaWizard`, `FaixaDetail`, `Relatorios`).
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
2. Não existe suíte de testes formal ainda — a validação é exercitar os endpoints tocados via
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

## Cuidados conhecidos

- **Enum + Postgres + Alembic**: o `downgrade()` gerado por autogenerate não derruba o tipo ENUM
  nativo por trás de uma coluna `Enum` (`drop_table` não faz isso sozinho) — sem o
  `sa.Enum(name=...).drop(bind, checkfirst=True)` explícito, um `upgrade` seguinte falha com "type
  already exists". Ver `alembic/versions/3bd1d89aa92f_baseline_schema_atual.py` como referência.
- **Não reintroduza `Base.metadata.create_all()`** — foi substituído por Alembic de propósito; toda
  mudança de schema passa por migration.
- O worker de disparo roda no mesmo processo do backend; não assuma um serviço/fila separada.
- Envio de imagem de header de template depende de URL pública (`/media`) — não funciona contra
  `localhost` (ver `README.md` → "Limitações conhecidas").
- Upload de planilha (`POST /faixas/{id}/uploads`) é em duas etapas: primeiro lê só o cabeçalho
  (`/uploads/columns`), o frontend monta o mapeamento variável→coluna real e só então confirma o
  import — não assuma nomes de coluna fixos como "nome"/"celular".

## Referências

- Visão funcional completa, variáveis de ambiente e como configurar a API da Meta: `README.md`.
- Migrations: `README.md` → "Migrations (Alembic)".
- Limitações conhecidas e próximos passos combinados: `README.md` → "Limitações conhecidas /
  próximos passos".
