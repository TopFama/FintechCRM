# GEMINI.md — instruções para agentes delegados (Antigravity / Gemini)

Você foi acionado pelo **project owner** para executar **uma tarefa delimitada** neste repositório. O
owner especifica, você implementa, e o owner revisa e integra o que você entregar. Leia este arquivo
inteiro, depois o [`AGENTS.md`](./AGENTS.md) (convenções do projeto) e o `TAREFA.md` da raiz do seu
workspace (a tarefa em si).

## 1. Regras de operação (não negociáveis)

1. **Seu workspace é só o diretório onde este arquivo está** (um git worktree próprio). Não leia,
   liste nem escreva em nenhum outro diretório do computador — em especial nunca abra o `.env` do
   repositório principal nem qualquer arquivo de credenciais.
2. **Segredos**: você não tem (e não deve procurar) credenciais do ERP SETA, do Google ou da Meta. Não
   invente valores reais, não imprima variáveis de ambiente e não coloque segredo em código, log ou
   commit. Nada da sua tarefa exige acessar o ERP: teste com dados simulados.
3. **Não faça `git commit`, `git push`, `git rebase`, `git reset` nem troque de branch.** Deixe as
   alterações no working tree; o owner revisa o diff e faz o commit. Pode usar `git status`,
   `git diff` e `git log` para conferir o que mudou.
4. **Não instale dependências novas** (nada em `requirements.txt` / `package.json` além do que a
   tarefa disser explicitamente). Rodar `npm install` para instalar o que já está no
   `package.json` é permitido.
5. **Fique no escopo**: altere só os arquivos que a tarefa cita ou que ela obriga a tocar. Sem
   refactor "de passagem", sem renomear o que já existe, sem reformatar arquivos inteiros. Se achar
   que algo fora do escopo está errado, **não corrija — anote no relatório final**.
6. **Não altere** `GEMINI.md`, `AGENTS.md`, `TAREFA.md`, `.env*`, `docker-compose.yml` nem os `Dockerfile`.
7. **Não ignore erro**: se um passo de validação falhar e você não conseguir resolver, pare e diga
   no relatório o comando, a saída do erro e o que já tentou. Nunca declare "pronto" sem ter
   rodado a validação pedida.
8. **Ambiente**: Windows com Git Bash. Use sintaxe POSIX, barras `/`. Comandos longos podem ser
   rodados normalmente; não use `sleep` para "esperar" algo.

## 2. Convenções de código (resumo — detalhes no AGENTS.md)

- **Domínio em português**, sempre: nomes de tabela/coluna, variáveis de domínio, textos de tela,
  mensagens de erro. Infra genérica (`request`, `session`, `router`) continua em inglês.
- Comentários em português, curtos, **só quando explicam um porquê não óbvio**. Sem docstring que
  repete o nome da função. Sem `TODO`, sem código morto, sem `console.log`/`print` de depuração.
- Backend (FastAPI + SQLAlchemy 2.0 `Mapped[...]` + Pydantic v2): schemas em `schemas.py` sob
  comentário `# --- Área ---`; uma rota nova entra no router da área; integração com sistema externo
  fica **num único módulo cliente** (`seta_client.py`, `google_client.py`, `meta_client.py`).
- Frontend (React 18 + TypeScript + Vite + react-router 6): **sem framework de UI, sem lib de
  ícones, sem lib de tabela/gráfico/data**. Estilo só em `src/styles.css` (tokens em `:root`, classes
  reaproveitadas: `.card`, `.page-header`, `.form-row`, `.field`, `.table-wrap`, `.badge`,
  `.empty-state`, `.error-box`, `.success-box`, `.stat-grid`…). Ícones novos entram em `src/icons.tsx`
  no mesmo estilo dos existentes. **Toda chamada HTTP passa por `src/api.ts`** (método novo + tipos
  TypeScript espelhando o schema do backend) — nunca `fetch` direto numa página.
- Valores monetários chegam do backend como **string decimal** (`"1234.50"`); formate no cliente com
  `Intl.NumberFormat("pt-BR", { style: "currency", currency: "BRL" })`. Datas chegam como
  `YYYY-MM-DD`; exiba `dd/mm/aaaa`.

## 3. Glossário do domínio (evita confusão de nomes)

- **SETA**: ERP da TopFama (Postgres externo, **somente leitura**). Só o owner acessa. Colunas são
  `character(N)` (com espaços à direita — sempre `trim`).
- **Cliente / pessoa**: `pessoas.codigo` de 8 dígitos (com zeros à esquerda, ex. `00123456`).
- **Título / parcela**: linha de `financeiro_titulos` (`ft`). "Em aberto" = `ft.status = 'A'`.
- **Faixa de atraso**: intervalo de dias de atraso da **parcela em aberto mais antiga** do cliente
  (ex. `"11 A 20"`, `"151+"`; `"-1"` = lembrete, vence amanhã). **Não confundir** com a entidade
  `Faixa` do sistema (`models.Faixa`, uma "campanha" de disparo com template + números).
- **Primeiro dia da faixa**: cliente exatamente no dia inicial da faixa (ex. 21 dias na faixa
  `21 A 30`). É um filtro (ligado por padrão) porque hoje só se cobra nesse dia.
- **Cluster**: segmento do cliente pela **soma paga em vendas** — `ESPECIAL`, `POTENCIAL`,
  `EM POTENCIAL`, `ALTO POTENCIAL`, `BEST SELLER`, `HEAVY USER`. **Não confundir** com o status do
  cadastro `E/A/B` (`pessoas.status`: E = Especial, A = Ativo, B = Bloqueado).
- **Regra WhatsApp**: matriz cluster × faixa que diz quem recebe cobrança por WhatsApp.
- **Lead**: retrato de um cliente da base de cobrança (tabela `leads`), com status `novo`/`cobrado`.
- **Blacklist**: clientes (por código de 8 dígitos ou CPF) que nunca entram na cobrança.
- **Salário**: como o sistema chama `pessoas.faturamento` (gera o limite do cliente). Sempre exiba
  e nomeie como `salario`, nunca "faturamento".
- **Valor a cobrar** (`valor_cobrar`): valor com multa e juros por parcela — vai no template do
  WhatsApp. **Valor em aberto** (`valor_em_aberto`): soma pura de `ft.valor`, sem juros — é o que
  aparece nos visuais/relatórios.

## 4. Como validar

### Backend (Python 3.12)

O ambiente virtual com todas as dependências já existe e é **compartilhado (somente leitura)**:

```
PY="C:/Users/TopFama/Documents/ProjetosDEV/FintechCRM/apps/backend/.venv/Scripts/python.exe"
cd <seu-workspace>/apps/backend
PYTHONPATH=. "$PY" <script.py>
```

- Não existe suíte de testes formal. Valide exercitando o código: funções puras com `assert` em
  script, e endpoints com `fastapi.testclient.TestClient` (ele roda o `lifespan` de verdade:
  migrations + criação do admin). Variáveis mínimas para subir o app num script de teste:
  `DATABASE_URL`, `JWT_SECRET` (qualquer texto longo, ≠ `change-me-too`), `ADMIN_PASSWORD` (≠
  `change-me-admin`), `MEDIA_DIR` (um diretório temporário existente). Login de teste:
  `POST /auth/login` com `admin@topfama.com.br` e o `ADMIN_PASSWORD` que você definiu.
- **Banco para testes**: há um Postgres descartável já rodando em `localhost:15432`
  (usuário `postgres`, senha `t`). **Use um banco só seu**, criado pelo owner e citado no
  `TAREFA.md`, no formato `postgresql+psycopg://postgres:t@localhost:15432/<banco>`. Nunca use o
  banco `migtest`, nem crie/apague outros bancos. Para checagem rápida sem Postgres vale SQLite
  (`sqlite:///<arquivo-temporario>`), mas coisas com `Enum`/tipos do Postgres exigem o Postgres.
- Integrações externas (SETA, Google, Meta) **não são acessíveis**: teste com dados simulados
  (`unittest.mock`, `httpx.MockTransport`, ou substituindo a função do módulo cliente).

### Migrations (Alembic) — regra de cabeça única

- Mudou `models.py`? `alembic revision --autogenerate -m "..."` dentro de `apps/backend`, **revise o
  arquivo gerado à mão** e valide o ciclo `upgrade head` → `downgrade base` → `upgrade head` e
  `alembic check` (sem diff) contra o Postgres do seu banco. Ver AGENTS.md sobre o ENUM do Postgres.
- Outros agentes geram migrations em paralelo. **Anote no relatório o `revision` e o
  `down_revision` da sua migration**: o owner reencadeia se houver duas cabeças. Nunca edite migration
  existente.
- Se a tarefa pede dados iniciais (seed), faça **dentro da migration** (`op.bulk_insert` com
  `sa.table(...)`), sem importar código de `app/` (a migration precisa continuar funcionando mesmo
  se o código mudar).

### Frontend

```
cd <seu-workspace>/apps/frontend
npm install
npm run build        # tsc -b && vite build — qualquer erro é bloqueante
```

- Não há backend rodando para a sua tarefa: a validação é o **build sem erros e sem warnings de
  tipo**, mais revisão do seu próprio código contra o contrato de API do `TAREFA.md`.
- Ao terminar, apague `dist/`, `node_modules/` e `tsconfig.tsbuildinfo` **do seu workspace** (já
  estão no `.gitignore`, mas confira com `git status`).

## 5. Formato do relatório final (obrigatório)

Termine sempre com estas seções, curtas e factuais:

1. **Resumo**: o que foi entregue, em 3–6 linhas.
2. **Arquivos**: lista de arquivos criados/alterados (uma linha cada, com o porquê).
3. **Validação**: cada comando que você rodou e o resultado real (cole o trecho relevante da
   saída). O que **não** foi possível validar e por quê.
4. **Decisões e suposições**: tudo que a tarefa não especificava e você decidiu por conta própria.
5. **Fora do escopo / problemas encontrados**: coisas erradas que você viu e **não** mexeu.
6. **Migration** (se houver): `revision`, `down_revision`.

O owner vai conferir o que você declarou rodando as validações por conta própria — declarar como
feito algo que não foi rodado é o pior resultado possível.
