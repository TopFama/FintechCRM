# GEMINI.md — instructions for delegated agents (Antigravity / Gemini)

You were called by the **project owner** to do **one bounded task** in this repo. The owner writes the
spec, you implement, the owner reviews and integrates. Read this whole file, then `AGENTS.md`
(project conventions, in Portuguese), then `TAREFA.md` at your workspace root (your task). If a
`REVISAO.md` exists, it lists fixes the owner wants after reviewing your previous delivery.

Instructions are in English to save tokens; **code, identifiers, UI text, error messages and code
comments stay in Portuguese** (see §2).

## 1. Operating rules (non-negotiable)

1. **Your workspace is only the directory containing this file** (your own git worktree). Never read,
   list or write any other directory — above all never open the main repo's `.env` or any credentials file.
2. **Secrets**: you have no credentials for the SETA ERP, Google, Meta or Chatwoot, and must not look for
   them. Do not print environment variables; never put a secret in code, logs or docs. No task needs the
   real services: test with simulated data.
3. **No `git commit`, `git push`, `git rebase`, `git reset`, no branch switching.** Leave changes in the
   working tree; the owner reviews the diff and commits. `git status/diff/log` are fine.
4. **No new dependencies** (nothing new in `requirements.txt` / `package.json` unless the task says so).
   `npm install` of what is already in `package.json` is fine.
5. **Stay in scope**: touch only files the task names or forces you to touch. No drive-by refactors, no
   renames, no whole-file reformatting. Spotted something wrong outside scope? **Report it, don't fix it.**
6. **Do not edit** `GEMINI.md`, `AGENTS.md`, `TAREFA.md`, `REVISAO.md`, `.env*`, `docker-compose.yml`, `Dockerfile`s.
7. **Never fake validation**: if a check fails and you can't fix it, stop and report the command, the
   error output and what you tried. Never claim "done" without running the requested validation.
8. **Environment**: Windows + Git Bash → POSIX syntax, `/` separators. Don't use `sleep` to wait.

## 2. Code conventions (summary — details in AGENTS.md)

- **Domain in Portuguese** always: table/column names, domain variables, screen text, error messages.
  Generic infra names (`request`, `session`, `router`) stay English. Code comments in Portuguese, short,
  **only for a non-obvious "why"**. No docstring that just repeats the name, no `TODO`, no dead code, no
  debug `print`/`console.log`, no decorative separator comments.
- Backend (FastAPI, SQLAlchemy 2.0 `Mapped[...]`, Pydantic v2): schemas in `schemas.py` under a
  `# --- Área ---` comment; new routes go in the existing router of the area; each external system is
  reached through **one client module** (`seta_client.py`, `google_client.py`, `meta_client.py`,
  `chatwoot_client.py`).
  Inside `app/`, use **relative imports** (`from .phone import ...`, `from ..utils.x import ...`).
- Frontend (React 18 + TypeScript + Vite + react-router 7): **no UI framework, no icon/table/chart/date
  library**. Styling only in `src/styles.css` (tokens in `:root`, reuse `.card`, `.page-header`,
  `.form-row`, `.field`, `.table-wrap`, `.badge`, `.empty-state`, `.error-box`, `.success-box`, …). New icons go
  in `src/icons.tsx` in the existing style. **Every HTTP call goes through `src/api.ts`** (new method +
  TypeScript types mirroring the backend schema) — never `fetch` inside a page.
- Money arrives from the backend as a **decimal string** (`"1234.50"`): format on the client with
  `Intl.NumberFormat("pt-BR", { style: "currency", currency: "BRL" })`. Dates arrive as `YYYY-MM-DD`; show
  `dd/mm/aaaa` (never via `new Date(str)`, which shifts the day by timezone).

## 3. Domain glossary (avoids name clashes)

- **SETA**: TopFama's ERP (external Postgres, **read-only**; only the owner can reach it). Columns are
  `character(N)` (trailing spaces — always `trim`).
- **Cliente / pessoa**: `pessoas.codigo`, 8 digits with leading zeros (`00123456`).
- **Título / parcela**: a `financeiro_titulos` (`ft`) row. "Open" = `ft.status = 'A'`.
- **Faixa de atraso**: interval of days late of the client's **oldest open parcel** (e.g. `"11 A 20"`,
  `"151+"`; `"-1"` = reminder, due tomorrow). **Not** the `Faixa` entity (`models.Faixa`), which is a
  dispatch "campaign" (template + numbers + schedule + queue).
- **Primeiro dia da faixa**: client exactly on the faixa's first day (21 days late in faixa `21 A 30`).
  A filter, on by default, because collection currently happens only on that day.
- **Cluster**: client segment by **amount paid in sales** — `ESPECIAL`, `POTENCIAL`, `EM POTENCIAL`,
  `ALTO POTENCIAL`, `BEST SELLER`, `HEAVY USER`. **Not** the registration status `E/A/B` of `pessoas.status`.
- **Regra WhatsApp**: cluster × faixa matrix saying who gets WhatsApp collection.
- **Lead**: snapshot of a client in the collection base (`leads` table), status `novo`/`cobrado`.
- **Blacklist**: clients (by 8-digit code or CPF) that never enter collection.
- **Salário**: what the system calls `pessoas.faturamento` (it generates the client's limit). Always name
  and show it as `salario`, never "faturamento".
- **`valor_cobrar`**: amount with fine and interest per parcel — goes in the WhatsApp template.
  **`valor_em_aberto`**: plain sum of `ft.valor`, no interest — shown in reports/visuals.
- **Chatwoot**: customer-chat platform; numbers linked to a Chatwoot inbox send collection through it
  (`chatwoot_client.py`) instead of the Meta API.

## 4. How to validate

### Backend (Python 3.12)

A shared, read-only venv already has every dependency:

```
PY="C:/Users/TopFama/Documents/ProjetosDEV/FintechCRM/apps/backend/.venv/Scripts/python.exe"
cd <your-workspace>/apps/backend
PYTHONPATH=. "$PY" <script.py>
```

- Test scripts live in `apps/backend/tests/` (all run by `./tests/rodar_todos.sh` and in CI). Validate by
  exercising code: pure functions with `assert` scripts (put them in `apps/backend/tests/`, runnable as
  `PYTHONPATH=. "$PY" tests/<file>.py`, printing `OK` at the end)
  and endpoints with `fastapi.testclient.TestClient` (it runs the real `lifespan`: migrations + admin
  creation). Minimum env to boot the app in a test script: `DATABASE_URL`, `JWT_SECRET` (any long text ≠
  `change-me-too`), `ADMIN_PASSWORD` (≠ `change-me-admin`), `MEDIA_DIR` (an existing temp dir). Test login:
  `POST /auth/login` with `admin@topfama.com.br` and your `ADMIN_PASSWORD`.
- **Test database**: a throwaway Postgres runs on `localhost:15432` (user `postgres`, password `t`). **Use
  only the database named in your `TAREFA.md`**: `postgresql+psycopg://postgres:t@localhost:15432/<db>`.
  Never touch `migtest`, never create/drop other databases. SQLite (`sqlite:///<temp-file>`) is OK for quick
  checks, but anything with `Enum`/Postgres types needs Postgres.
- External systems (SETA, Google, Meta, Chatwoot) are **unreachable**: use simulated data (`unittest.mock`,
  `httpx.MockTransport`, or replacing the client module's function).

### Migrations (Alembic) — single-head rule

- Changed `models.py`? Run `alembic revision --autogenerate -m "..."` inside `apps/backend`, **review the
  generated file by hand**, then validate `upgrade head` → `downgrade base` → `upgrade head` and `alembic check`
  (no diff) against your database. See AGENTS.md about Postgres ENUMs.
- Other agents generate migrations in parallel. **Report your migration's `revision` and `down_revision`**;
  the owner re-chains if there are two heads. Never edit an existing migration.
- Seed data belongs **inside the migration** (`op.bulk_insert` with `sa.table(...)`), without importing
  anything from `app/`.

### Frontend

```
cd <your-workspace>/apps/frontend
npm install
npm run build        # tsc -b && vite build — any error is blocking
```

No backend runs for you: validation is a clean build plus reviewing your code against the task's API
contract. When done, delete `dist/`, `node_modules/` and `tsconfig.tsbuildinfo` from your workspace.

## 5. Final report format (mandatory)

End every run with these short, factual sections:

1. **Summary** — what was delivered, 3–6 lines.
2. **Files** — created/changed files, one line each with the why.
3. **Validation** — every command you ran and its real result (paste the relevant output). What you
   could **not** validate and why.
4. **Decisions and assumptions** — anything the task left open and you decided.
5. **Out of scope / problems found** — wrong things you saw and did **not** touch.
6. **Migration** (if any) — `revision`, `down_revision`.

The owner re-runs your validations. Claiming something ran when it didn't is the worst possible outcome.
