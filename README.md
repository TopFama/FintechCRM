# FintechCRM — CRM de Cobrança via WhatsApp

Portal web da TopFama para gerir cobrança via WhatsApp (API oficial da Meta) sem depender do n8n:
o próprio backend fala diretamente com a Graph API da Meta para listar/criar templates, listar
números, enviar mensagens e controlar agendamento/lote de disparo. Os dados vivem num Postgres
próprio, rodando em container — não há dependência do Supabase.

## Estrutura (monorepo)

```
FintechCRM/
  apps/
    backend/                    # FastAPI + SQLAlchemy + APScheduler + cliente Graph API
      app/
        main.py                 # cria o app, roda migrations e cria o admin na subida
        config.py                # Settings (pydantic-settings, lê o .env)
        database.py              # engine/Session/Base do SQLAlchemy
        models.py                 # todas as tabelas
        schemas.py                # modelos Pydantic de request/response
        security.py / deps.py     # hash de senha, JWT, dependência de usuário autenticado
        meta_client.py             # único ponto de integração com a Graph API da Meta
        seta_client.py             # único ponto de integração com o ERP SETA (Postgres, só leitura)
        worker.py                  # worker de disparo (APScheduler, dentro do próprio processo)
        routers/                   # um arquivo por área: auth, numbers, templates, faixas,
                                    # uploads, dashboard, reports
        utils/
          phone.py                 # normalização/validação de telefone (formato 55DD9XXXXXXXX)
          document.py               # normalização de código SETA, CPF e nome do cliente
          spreadsheet.py             # leitura de .xlsx e geração do modelo de planilha
      alembic/                    # migrations do schema (ver seção Migrations abaixo)
      requirements.txt
      Dockerfile
    frontend/                   # React + TypeScript + Vite
      src/
        api.ts                   # único lugar que fala com o backend (fetch + tipos)
        pages/                    # uma página por rota (Login, Dashboard, Numbers, Templates,
                                   # Faixas, FaixaWizard, FaixaDetail, Relatorios)
        styles.css                 # design tokens (CSS vars) e classes utilitárias
        icons.tsx                   # ícones inline SVG, sem lib externa
      public/topfama-logo.png       # logo oficial da marca
      Dockerfile / nginx.conf
  docker-compose.yml
  .env.example
```

## Pré-requisitos

- **Docker** e **Docker Compose** — forma recomendada de rodar tudo (backend, frontend e Postgres
  em containers, sem instalar nada além do Docker).
- Alternativa sem Docker, para desenvolvimento: **Python 3.12** + **Node.js 20** e um Postgres
  acessível (local ou remoto) — ver [Rodando sem Docker](#rodando-sem-docker) mais abaixo.

## Configuração do ambiente (`.env`)

Copie `.env.example` para `.env` na raiz do repositório e preencha. Todas as variáveis abaixo são
lidas pelo backend via `app/config.py` (com esses mesmos defaults quando a variável não é
definida) ou pelo `docker-compose.yml`/build do frontend.

| Variável | Usada por | Obrigatória | Default | Descrição |
|---|---|---|---|---|
| `POSTGRES_USER` | container `db` | não | `fintechcrm` | Usuário do Postgres criado pelo container oficial. |
| `POSTGRES_PASSWORD` | container `db` | **sim**, em produção | `change-me` | Senha do Postgres — troque antes de expor o sistema. |
| `POSTGRES_DB` | container `db` | não | `fintechcrm` | Nome do banco criado na primeira subida do container. |
| `DATABASE_URL` | backend | não | `postgresql+psycopg://fintechcrm:change-me@db:5432/fintechcrm` | String de conexão completa (SQLAlchemy + psycopg 3). Se mudar usuário/senha/banco acima, ajuste aqui também — o backend usa esta variável, não as três de cima diretamente. |
| `JWT_SECRET` | backend | **sim** | `change-me-too` | Chave usada para assinar o JWT de login — o backend **recusa subir** se este valor continuar igual ao default do `.env.example`. |
| `ADMIN_EMAIL` / `ADMIN_PASSWORD` | backend | `ADMIN_PASSWORD` **sim** | `admin@topfama.com.br` / `change-me-admin` | Credenciais do usuário admin criado automaticamente na primeira subida (só se ainda não existir um usuário com esse email). O backend também recusa subir se `ADMIN_PASSWORD` continuar com o valor default. |
| `ENCRYPTION_KEY` | backend | **sim** | *(vazio)* | Chave Fernet (32 bytes em base64 url-safe) dedicada para criptografia de segredos no banco (tokens da Meta e refresh token do Google). O backend **recusa subir** se vazia, inválida ou igual ao exemplo do `.env.example`. Gere com: `python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"`. Guarde junto ao backup do banco: sem ela os segredos salvos não abrem. |
| `META_GRAPH_API_VERSION` | backend | não | `v21.0` | Versão da Graph API usada em todas as chamadas (`app/meta_client.py`). |
| `SETA_DB_HOST` / `SETA_DB_PORT` / `SETA_DB_NAME` | backend | não | *(vazio)* / `5432` / `seta` | Postgres do ERP SETA, usado **só para leitura** (a conexão abre com `default_transaction_read_only=on`). Vazio = integração desligada: o backend sobe normalmente e `GET /seta/status` responde `configurado: false`. |
| `SETA_DB_USER` / `SETA_DB_PASSWORD` | backend | não | *(vazio)* | Credenciais do SETA. O ideal é um usuário do banco só com `SELECT`. |
| `SETA_DB_CONNECT_TIMEOUT_SECONDS` / `SETA_DB_STATEMENT_TIMEOUT_SECONDS` | backend | não | `10` / `120` | Tempo máximo para conectar e para cada consulta (o ERP é produção e a tabela de títulos passa de 27 milhões de linhas). |
| `GOOGLE_CLIENT_ID` / `GOOGLE_CLIENT_SECRET` | backend | não | *(vazio)* | Cliente OAuth2 (aplicativo da Web) do Google Cloud, com a Google Sheets API ativada. Vazio = integração desligada; sem ela só não dá para filtrar por regional/estado/cluster de loja. Depois de preenchido, conecte a conta em **Configurações** (o refresh token fica cifrado no banco com a `ENCRYPTION_KEY`). |
| `GOOGLE_REDIRECT_URI` / `GOOGLE_FRONTEND_URL` | backend | não | `http://localhost:8000/google/oauth/callback` / `http://localhost:5173` | A primeira precisa estar cadastrada, idêntica, nas URIs de redirecionamento autorizadas do cliente OAuth; a segunda é para onde o navegador volta depois do consentimento. |
| `GOOGLE_SHEET_LOJAS_ID` / `GOOGLE_SHEET_LOJAS_GID` | backend | não | planilha de lojas da TopFama | ID da planilha (trecho da URL entre `/d/` e `/edit`) e `gid` da aba (`#gid=…`). Colunas lidas: FILIAL, NOME COM COD, REGIONAL, ESTADO, CLUSTER INAD e CLUSTER POPULAÇÃO. |
| `VITE_API_URL` | frontend (build) | não | `http://localhost:8000` | URL base da API que o frontend chama — usada só no build do Vite (fica embutida no bundle). |

WABA ID, `phone_number_id` e os **tokens de acesso da Meta** **não** vão no `.env` — são cadastrados dentro do
próprio portal, na tela **Números**, depois que o sistema estiver no ar (ficam guardados cifrados no
Postgres).

## Configurando a API da Meta (WhatsApp Business)

Passo a passo para gerar o token da Meta e cadastrá-lo na tela **Números** do portal:

1. **Crie (ou use) um app Meta for Developers** em https://developers.facebook.com/apps, com o
   produto **WhatsApp** adicionado a ele.
2. Em **WhatsApp → Configuração da API** (ou **Business Settings** do seu Business Manager),
   anote:
   - o **WABA ID** (ID da conta do WhatsApp Business) — usado ao cadastrar os números na tela **Números**.
   - o **phone_number_id** de cada número que vai disparar mensagens (não é o número de telefone
     em si, é o ID interno da Meta para aquele número).
3. **Gere um token de acesso de longa duração** (o token temporário que aparece na tela de teste
   expira em 24h e não serve para produção):
   - Em **Business Settings → Usuários → Usuários do sistema**, crie um **System User** (ou use um
     existente) com papel de Admin.
   - Em **Adicionar ativos**, dê a esse System User acesso total ao WABA do passo 2.
   - Gere um novo token para o System User com as permissões `whatsapp_business_messaging` e
     `whatsapp_business_management`. Tokens de System User podem ser gerados sem expiração.
4. **Cadastre o token no portal**:
   - Suba o sistema (`docker compose up --build`).
   - Dentro do portal, na tela **Números**, localize o card **Tokens da Meta**.
   - Cadastre o token com um nome identificador. Ele é cifrado e salvo no banco com `ENCRYPTION_KEY`.
     Você pode testar a conexão com a Meta diretamente no botão "Testar".
5. **Cadastre e vincule os números**:
   - Na mesma tela **Números**, cadastre cada número com WABA ID + `phone_number_id` + número exibido
     e selecione o token da Meta cadastrado no passo anterior.
6. Tela **Templates**: use **"Sincronizar templates da Meta"** para puxar os templates já aprovados,
   ou crie um novo template pelo próprio portal (com a opção de já submeter para aprovação).

Sem um token ativo cadastrado e vinculado ao número ou à sua WABA, sincronizar templates, criar template
na Meta e disparar mensagens vão falhar com aviso de token não configurado.

## Como rodar localmente

1. Copie `.env.example` para `.env` e preencha pelo menos `ENCRYPTION_KEY` (ver seção acima).
2. Suba tudo:

   ```bash
   docker compose up --build
   ```

3. Acesse:
   - Portal: http://localhost:5173
   - API (docs interativas): http://localhost:8000/docs
   - Postgres, se precisar inspecionar direto: `localhost:5432` (usuário/senha do `.env`).

4. Login inicial: o backend cria automaticamente um usuário admin na primeira subida, com
   `ADMIN_EMAIL` / `ADMIN_PASSWORD` definidos no `.env`.

Para parar tudo: `docker compose down` (os dados do Postgres e os arquivos de mídia ficam nos
volumes `postgres-data`/`media-data`, então sobrevivem a um `down`/`up`; use `docker compose down
-v` para apagar tudo do zero).

### Rodando sem Docker

Útil para iterar mais rápido no backend ou no frontend isoladamente.

**Backend** (precisa de um Postgres acessível — pode ser o do `docker compose up db` sozinho, ou
qualquer outro):

```bash
cd apps/backend
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
export $(grep -v '^#' ../../.env | xargs)   # ou exporte as variáveis manualmente
uvicorn app.main:app --reload --port 8000
```

**Frontend**:

```bash
cd apps/frontend
npm install
npm run dev       # sobe em http://localhost:5173, apontando para VITE_API_URL (padrão :8000)
npm run build     # build de produção (tsc -b && vite build) — bom smoke test de tipos quebrados
```

Os scripts `npm run dev:frontend` / `npm run build:frontend` no `package.json` da raiz fazem o
mesmo via npm workspaces, se preferir rodar da raiz do repo.

## Migrations (Alembic)

O schema do banco é versionado com [Alembic](https://alembic.sqlalchemy.org/) — o backend roda
`alembic upgrade head` automaticamente a cada subida (dentro do `lifespan` do FastAPI, em
`app/main.py`), então `docker compose up` continua sendo o único passo necessário em
desenvolvimento; não existe mais `Base.metadata.create_all()`.

- **Criar uma migration nova** depois de alterar `app/models.py`:

  ```bash
  cd apps/backend
  alembic revision --autogenerate -m "descreva a mudança"
  ```

  Sempre **revise o arquivo gerado** em `alembic/versions/` antes de commitar — o autogenerate não
  detecta tudo (ex. mudança só de `nullable`/default em alguns casos) e, no Postgres, colunas
  `Enum` exigem que o `downgrade()` derrube também o tipo nativo (`sa.Enum(name=...).drop(bind)`),
  senão um `upgrade` seguinte falha com "type already exists".
- **Aplicar manualmente** (o backend já faz isso sozinho na subida, mas é útil para depurar):

  ```bash
  alembic upgrade head      # aplica todas as migrations pendentes
  alembic downgrade -1      # desfaz a última
  alembic check             # confere se o models.py bate com o schema do banco (sem diffs pendentes)
  ```
- **Banco já existente antes desta versão** (schema criado via `create_all()`, sem histórico do
  Alembic): a migration `3bd1d89aa92f` (baseline) cria tudo do zero e vai falhar em cima de tabelas
  que já existem. Se o schema já bate com `app/models.py` atual, marque o banco como já estando na
  baseline **sem rodar a migration**:

  ```bash
  alembic stamp head
  ```

  Se o schema estiver desatualizado (schema anterior à faixa de mapeamento de planilha/código do
  cliente/telefones inválidos), aplique manualmente o `ALTER TABLE`/tabela nova equivalente ao
  diff antes do `stamp head` — ou, em ambiente sem dados que valha a pena preservar, derrube e
  recrie o banco e deixe o `upgrade head` automático cuidar do resto.

## Fluxo do sistema

1. **Números** — cadastre os números de WhatsApp (WABA ID + phone number ID) conectados à Meta.
2. **Templates** — sincronize os templates já aprovados na Meta (por WABA ID) ou crie um novo
   template pelo portal (com opção de já submeter para análise da Meta e acompanhar o status de
   aprovação depois). Templates com cabeçalho de imagem permitem subir a imagem, reaproveitada em
   todo envio daquele template.
3. **Faixas de cobrança** — wizard guiado: nome da faixa (texto livre, ex. "21 A 30" ou
   "RENEGOCIE") → template aprovado → número(s) de envio (com rotação automática quando mais de
   um) → nomes de coluna sugeridos para o modelo de planilha (o mapeamento de verdade acontece no
   upload, veja o próximo passo).
4. Dentro da faixa: baixe o **modelo de planilha** (sugestão de colunas: Codigo, Nome, CPF,
   Celular, Valor) ou suba direto a planilha que já tiver. O sistema lê o cabeçalho (primeira
   linha) e mostra um mapeamento em lista suspensa — você escolhe qual coluna real vira cada
   variável do template e cada um dos campos obrigatórios de toda planilha:
   - **Código** — SETA de até 8 dígitos; se vier com menos, completa com zero à esquerda.
   - **Nome** — se vier o nome completo, usa só o primeiro nome.
   - **CPF** — formata com pontos e traço (`000.000.000-00`); se faltar dígito, completa com zero
     à esquerda.
   - **Celular** — normalizado para `55DD9XXXXXXXX` (ver validação por linha abaixo).

   O valor cobrado é opcional. Só depois de confirmar o mapeamento a planilha é importada para a
   fila.
5. Validação por linha: telefone é normalizado para `55DD9XXXXXXXX` (detecta se falta o DDI `55`
   ou o 9º dígito e completa; se tiver menos dígitos que o padrão, a linha vai para o **relatório
   de telefones inválidos**, com código do cliente e telefone informado). Linhas sem código,
   nome ou CPF válidos, ou com telefone duplicado na fila, são rejeitadas e listadas no resultado
   do upload.
6. Configure **intervalo entre rodadas de envio**, **quantidade de cobranças por rodada** e a
   **janela de agendamento** (dias/horário) — ou dispare **"Cobrar esta base agora"** para rodar
   imediatamente, sem esperar o agendamento. A fila da faixa é acompanhada quase em tempo real
   (atualização automática a cada poucos segundos).
7. O **worker interno** (APScheduler, dentro do próprio processo do backend) varre periodicamente
   as faixas ativas/marcadas para rodar agora, reserva um lote de clientes pendentes, envia via
   Graph API alternando entre os números configurados, e atualiza o status de cada envio
   (enviado/erro), com log de erro consultável no dashboard.
8. **Dashboard** — pendentes, enviados, erros, telefones inválidos, por faixa, e os erros mais
   recentes — tudo lido direto do Postgres do próprio sistema.
9. **Relatórios** — telefones inválidos (código do cliente + telefone) e envios realizados (código
   do cliente, faixa de atraso, nome, valor cobrado, telefone que cobrou e data/hora), com filtro
   por faixa e exportação em Excel (.xlsx) já formatado.

## Testes / validação de mudanças

Não existe suíte de testes automatizados formal ainda. Para validar uma mudança antes de subir:

- **Backend**: suba um ambiente virtual (`pip install -r requirements.txt`), aponte `DATABASE_URL`
  para um Postgres (ou SQLite, para checagens rápidas sem Postgres) e exercite os endpoints
  relevantes com o `TestClient` do FastAPI (`from fastapi.testclient import TestClient`), que já
  passa pelo `lifespan` (migrations + criação do admin) igual à aplicação real.
- **Mudança em `app/models.py`**: gere a migration (`alembic revision --autogenerate`) e valide o
  ciclo `upgrade head` → `downgrade base` → `upgrade head` contra um Postgres real antes de
  commitar — ver seção Migrations acima.
- **Frontend**: `npm run build` (roda `tsc -b && vite build`) já pega a maioria dos erros de tipo
  e import quebrado.

## Limitações conhecidas / próximos passos

- **Imagem de header em produção**: a Cloud API da Meta busca a imagem do header por uma URL
  pública (`link`). Em ambiente local (`localhost`), essa URL não é alcançável pela Meta — para
  enviar templates com imagem em produção, exponha `/media` publicamente (ex. atrás de um domínio
  com HTTPS) ou evolua o envio para usar upload de mídia (`media_id`) em vez de link.
- **Submissão de template para aprovação**: o endpoint de criação já está implementado
  (`POST /templates`, com `submit_to_meta=true`), mas os requisitos exatos de formatação de
  componentes variam por categoria — revise o payload em `app/routers/templates.py` contra a
  documentação oficial antes de depender disso em produção.
- **Retry de envio**: hoje, uma falha de envio marca o item como `error` e fica visível no
  dashboard; reprocessamento automático (retry com backoff) ainda não está implementado — é o
  próximo incremento natural do worker (`app/worker.py`).
- **Fila em "tempo real"**: o acompanhamento da fila no portal usa polling (nova consulta a cada
  poucos segundos), não WebSocket — simples e suficiente para o volume atual, mas vale revisar se
  o volume de faixas abertas simultaneamente crescer muito.
- **Autenticação e segurança**: login simples (usuário/senha + JWT), sem papéis granulares, conforme escopo
  combinado para a v1. Segredos sensíveis guardados no banco (tokens de acesso da Meta e refresh token do
  Google OAuth) são cifrados simetricamente com a chave dedicada `ENCRYPTION_KEY`. A perda dessa chave
  impede a leitura desses segredos e exige cadastrar novamente os tokens da Meta e reconectar a conta Google.

## Migração a partir do n8n

Este sistema foi desenhado a partir do fluxo `FINTECH - FLUXO DE COBRANÇA` que rodava no n8n:
- `templates_wpp` (Supabase) → tabelas `templates` + `template_variables` (Postgres próprio).
- `cobranca_wpp` (fila) → tabela `cobranca_fila`.
- Regras de normalização/validação de telefone → `app/utils/phone.py` (mesma lógica do Code node).
- Rotação de números por faixa e reserva antes do envio → `app/worker.py`.
- Schedule Trigger (cron fixo) → `dispatch_configs` (intervalo/lote/janela configuráveis por
  faixa, editáveis pela própria interface, sem precisar editar workflow nenhum).

## Para agentes de IA

Se você é um agente de codificação (Claude Code, Codex, etc.) alterando este repositório, leia
também o [`AGENTS.md`](./AGENTS.md) na raiz — convenções do projeto, onde fica cada coisa e como
validar uma mudança antes de considerá-la pronta.
