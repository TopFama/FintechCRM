# FintechCRM — CRM de Cobrança via WhatsApp

Portal web da TopFama para gerir cobrança via WhatsApp (API oficial da Meta) sem depender do n8n:
o próprio backend fala diretamente com a Graph API da Meta para listar/criar templates, listar
números, enviar mensagens e controlar agendamento/lote de disparo. Os dados vivem num Postgres
próprio, rodando em container — não há dependência do Supabase.

## Estrutura (monorepo)

```
FintechCRM/
  apps/
    backend/                    # FastAPI + SQLAlchemy + APScheduler + clientes das integrações
      app/
        main.py                 # cria o app, roda migrations, cria o admin e sobe o worker
        config.py               # Settings (pydantic-settings, lê o .env)
        database.py             # engine/Session/Base do SQLAlchemy
        models.py               # todas as tabelas
        schemas.py              # modelos Pydantic de request/response
        security.py / deps.py   # hash de senha, JWT, dependência de usuário autenticado
        crypto.py / segredos.py # cifra Fernet dos segredos no banco e re-cifra na subida
        meta_client.py          # único ponto de integração com a Graph API da Meta
        chatwoot_client.py      # único ponto de integração com o Chatwoot (envio pela inbox)
        seta_client.py          # único ponto de integração com o ERP SETA (Postgres, só leitura)
        google_client.py        # único ponto de integração com o Google (OAuth2 + Sheets)
        worker.py               # agendamento do disparo e das rotinas diárias (APScheduler, no mesmo processo)
        dispatch_service.py     # envio de um item da fila (Meta ou Chatwoot)
        elegibilidade.py        # quem entra/sai da fila (uma cobrança por cliente por dia)
        cobranca_*.py, regras_db.py, leads_service.py, fila_automatica.py, campanhas*.py,
        remarketing.py, pausas.py, blacklist.py, lojas*.py, upload_service.py, itens_fila.py,
        consultas_fila.py, ...  # regras de domínio (ver docs/architecture/dominios-e-camadas.md)
        services/               # pagamentos/compras do SETA, efetividade, custo do WhatsApp
        routers/                # um arquivo por área: auth, users, meta_tokens, numbers, templates,
                                # faixas, uploads, dashboard, reports, seta, blacklist, cobranca,
                                # config_cobranca, leads, google, lojas, chatwoot, remarketing,
                                # campanhas, pausas (+ comum.py, peças HTTP compartilhadas)
        utils/
          phone.py              # normalização/validação de telefone (55DD9XXXXXXXX) e ordem dos telefones do cadastro
          document.py           # normalização de código SETA, CPF e nome do cliente
          spreadsheet.py        # leitura de .xlsx e geração do modelo de planilha
          imagem.py             # imagem de cabeçalho de template dentro do limite da Meta (Pillow)
          xlsx.py               # geração dos .xlsx exportáveis (relatórios, cobrança, dashboard)
          leads_xlsx.py         # exportação de leads e formatação de código/CPF/nome/celular
          spc.py                # leitura do texto da consulta SPC guardado no SETA
      alembic/                  # migrations do schema (ver seção Migrations abaixo)
      tests/                    # scripts de teste (rodar_todos.sh), rodam no CI
      .importlinter             # regras de import entre camadas (lint-imports, roda no CI)
      requirements.txt
      Dockerfile
    frontend/                   # React + TypeScript + Vite
      src/
        api.ts                  # único lugar que fala com o backend (fetch + tipos)
        pages/                  # uma página por rota (Login, Dashboard, Cobranca, Campanhas,
                                # CampanhaDetail, Relatorios, Configuracoes, Faixas, FaixaWizard,
                                # FaixaDetail)
        components/             # peças reaproveitadas; config/ = cards das abas de Configurações,
                                # dashboard/ = cards do Dashboard
        styles.css              # design tokens (CSS vars) e classes utilitárias
        icons.tsx               # ícones inline SVG, sem lib externa
      public/topfama-logo.png   # logo oficial da marca
      Dockerfile / nginx.conf
  .github/workflows/            # CI (testes, e2e-mapa, security-scan) e deploy automático na VPS
  e2e/                          # suíte Playwright ponta a ponta (ver e2e/README.md)
  docs/architecture/            # mapa de domínios/camadas, fichas por área e backlog de refatoração
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
| `SETA_MAX_CONSULTAS_PESADAS` | backend | não | `2` | Quantas consultas pesadas ao SETA (base de cobrança, efetividade, pagamentos, compras) rodam ao mesmo tempo no processo; as demais esperam na vez (`seta_client.consulta_pesada`). **Não** aumente junto com o pool nem os timeouts para "resolver" lentidão: o limite existe para o ERP de produção não receber rajada. |
| `GOOGLE_CLIENT_ID` / `GOOGLE_CLIENT_SECRET` | backend | não | *(vazio)* | Cliente OAuth2 (aplicativo da Web) do Google Cloud, com a Google Sheets API ativada. Vazio = integração desligada; sem ela só não dá para filtrar por regional/estado/cluster de loja. Depois de preenchido, conecte a conta em **Configurações** (o refresh token fica cifrado no banco com a `ENCRYPTION_KEY`). |
| `GOOGLE_REDIRECT_URI` / `GOOGLE_FRONTEND_URL` | backend | não | `http://localhost:8000/google/oauth/callback` / `http://localhost:5173` | A primeira precisa estar cadastrada, idêntica, nas URIs de redirecionamento autorizadas do cliente OAuth; a segunda é para onde o navegador volta depois do consentimento. |
| `GOOGLE_SHEET_LOJAS_ID` / `GOOGLE_SHEET_LOJAS_GID` | backend | não | planilha de lojas da TopFama | ID da planilha (trecho da URL entre `/d/` e `/edit`) e `gid` da aba (`#gid=…`). Colunas lidas: FILIAL, NOME COM COD, REGIONAL, ESTADO, CLUSTER INAD e CLUSTER POPULAÇÃO. |
| `REDIS_URL` | backend | não | `redis://redis:6379/0` | Cache e trava das consultas pesadas ao SETA (base de cobrança, efetividade, Quem pagou, card de pagamentos, resumo e orçamento do Dashboard — a tabela de títulos tem mais de 27 milhões de linhas). Redis fora do ar = essas telas respondem 503 "cache indisponível"; o backend **não** cai para consulta direta ao SETA. Ver `app/cache.py`. |
| `CORS_ALLOWED_ORIGINS` | backend | não | `*` | Origens liberadas no CORS, separadas por vírgula (ex: `https://crm.topfama.com.br`). O padrão `*` mantém o comportamento anterior; em produção, restrinja ao(s) domínio(s) real(is) do frontend. |
| `ALLOWED_HOSTS` | backend | não | `lojastopfama.com.br,*.lojastopfama.com.br,localhost,127.0.0.1,testserver` | Domínios aceitos no cabeçalho `Host` e, quando o navegador manda, no `Origin`; qualquer outro recebe **403 Forbidden** (`security.origem_permitida`, usada pelo middleware de `main.py` e pelo WebSocket do Dashboard). `*.dominio` libera os subdomínios. Sem `Origin` passa (webhook do Chatwoot, `/media`, healthcheck). O proxy reverso precisa repassar o `Host` do domínio (padrão do Nginx/Caddy) ou chamar o backend pelo endereço interno (`127.0.0.1:porta`); um `Host` interno de outro nome (ex. `backend:8000`) precisa entrar nesta lista. |
| `COOKIE_SECURE` | backend | não | `true` | Atributo `Secure` do cookie httpOnly de sessão (ver "Limitações conhecidas / próximos passos" abaixo). Exige `https`; em desenvolvimento local sobre `http` puro, defina como `false`, senão o navegador descarta o cookie. |
| `ACCESS_TOKEN_EXPIRE_MINUTES` | backend | não | `720` | Validade do JWT de login (12 h). |
| `PUBLIC_BASE_URL` | backend | não | *(vazio)* | Endereço público deste backend (sem barra final). Usado pelo envio via **Chatwoot** para montar o link da imagem de cabeçalho do template e no registro de webhooks (`/chatwoot/webhook`); pela Meta a imagem vai como `media_id`. |
| `CHATWOOT_WEBHOOK_SECRET` | backend | não | *(vazio)* | Segredo HMAC configurado para validação de assinatura (`X-Chatwoot-Signature`) dos webhooks recebidos do Chatwoot (`POST /chatwoot/webhook`). Quando vazio, a validação de assinatura é ignorada. |
| `MEDIA_DIR` | backend | não | `/app/media` | Pasta onde ficam as imagens de cabeçalho subidas em Templates (volume `media-data` no Docker; servida em `/media`). Precisa existir. |
| `DISPATCH_WORKER_INTERVAL_SECONDS` | backend | não | `5` | De quanto em quanto tempo o worker roda o ciclo de disparo. O ritmo real (intervalo entre rodadas e quantidade por rodada) é configurado na tela, em **Configurações → Horário**. |
| `PAGAMENTOS_SYNC_INTERVAL_SECONDS` | backend | não | `1800` | Intervalo mínimo entre as releituras das baixas do SETA para `pagamentos_seta` (ver "Fluxo do sistema" → Dashboard). |
| `BUSINESS_TIMEZONE` | backend | não | `America/Sao_Paulo` | Fuso usado para a janela de disparo e para decidir "que dia é hoje" (o banco guarda tudo em UTC). |
| `DB_BIND` / `BACKEND_BIND` / `FRONTEND_BIND` | `docker-compose.yml` | não | `127.0.0.1:5432` / `127.0.0.1:8000` / `127.0.0.1:5173` | Onde cada container publica a porta no host. O padrão nunca expõe para a internet; atrás de proxy reverso, aponte para a porta que o proxy chama. |
| `VITE_API_URL` | frontend (build) | não | `http://localhost:8000` | URL base da API que o frontend chama — usada só no build do Vite (fica embutida no bundle). |

WABA ID, `phone_number_id` e os **tokens de acesso da Meta** **não** vão no `.env` — são cadastrados dentro do
próprio portal depois que o sistema estiver no ar: os tokens em **Configurações → Tokens da Meta** (guardados
cifrados no Postgres), e os números são importados da WABA de cada token no card **Números de WhatsApp**,
na mesma tela, onde também se informa a inbox do Chatwoot de cada um.

## Configurando a API da Meta (WhatsApp Business)

Passo a passo para gerar o token da Meta e cadastrá-lo no portal. O token **nunca** vai no `.env`:
ele é cadastrado em **Configurações → Tokens da Meta** e guardado cifrado no banco.

1. **Crie (ou use) um app Meta for Developers** em https://developers.facebook.com/apps, com o
   produto **WhatsApp** adicionado a ele.
2. Em **WhatsApp → Configuração da API** (ou **Business Settings** do seu Business Manager),
   anote:
   - o **WABA ID** (ID da conta do WhatsApp Business) — informado junto com o token em **Configurações**.
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
   - Dentro do portal, na tela **Configurações**, localize o card **Tokens da Meta**.
   - Cadastre o token com um nome identificador. Ele é cifrado e salvo no banco com `ENCRYPTION_KEY`.
     Você pode testar a conexão com a Meta diretamente no botão "Testar".
5. **Cadastre e vincule os números**:
   - Ao salvar o token (com o WABA ID), o portal lista os números da WABA direto da Meta: marque os que
     vão disparar e clique em **Importar selecionados**. No card **Números de WhatsApp** informe a inbox do
     Chatwoot de cada número e desative os que não devem enviar.
6. **Configurações → Templates**: use **"Sincronizar templates da Meta"** para puxar os templates já aprovados,
   ou crie um novo template pelo próprio portal (salvo como rascunho e enviado pelo botão "Enviar para aprovação").

Sem um token ativo cadastrado e vinculado ao número ou à sua WABA, sincronizar templates, criar template
na Meta e disparar mensagens vão falhar com aviso de token não configurado.

## Como rodar localmente

1. Copie `.env.example` para `.env` e preencha pelo menos `ENCRYPTION_KEY`, `JWT_SECRET` e
   `ADMIN_PASSWORD` (o backend recusa subir com os valores de exemplo; ver seção acima).
2. Crie uma vez a rede Docker compartilhada com o TopFamaRenegocie (o backend a declara como
   `external`, então o `compose up` falha sem ela — o remarketing chama `http://renegocie-api:8000`
   por essa rede):

   ```bash
   docker network create topfama-interno
   ```
3. Suba tudo (Postgres, Redis, backend e frontend):

   ```bash
   docker compose up --build
   ```

4. Acesse:
   - Portal: http://localhost:5173
   - API (docs interativas): http://localhost:8000/docs
   - Postgres, se precisar inspecionar direto: `localhost:5432` (usuário/senha do `.env`). A porta só abre na própria máquina (`127.0.0.1`); de fora, use um túnel SSH: `ssh -L 5432:127.0.0.1:5432 usuario@vps`.

5. Login inicial: o backend cria automaticamente um usuário admin na primeira subida, com
   `ADMIN_EMAIL` / `ADMIN_PASSWORD` definidos no `.env`.

Para parar tudo: `docker compose down` (os dados do Postgres e os arquivos de mídia ficam nos
volumes `postgres-data`/`media-data`/`redis-data`, então sobrevivem a um `down`/`up`; use `docker compose down
-v` para apagar tudo do zero).

### Rodando sem Docker

Útil para iterar mais rápido no backend ou no frontend isoladamente.

**Backend** (precisa de um Postgres acessível — pode ser o do `docker compose up db` sozinho, ou
qualquer outro — e de um Redis, ex. `docker compose up db redis`: sem Redis as telas que usam o
cache, como Cobrança e Dashboard, respondem erro de cache indisponível). Aponte `DATABASE_URL` e
`REDIS_URL` para `localhost` (no `.env` eles apontam para os nomes dos containers, `db`/`redis`) e
`MEDIA_DIR` para uma pasta que exista:

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

1. **Números** — em **Configurações → Conexões**, cadastre o token da Meta (com o WABA ID) e
   importe os números da WABA (ver "Configurando a API da Meta" acima).
2. **Templates** — sincronize os templates já aprovados na Meta (por WABA ID) ou crie um novo
   template pelo portal. O cadastro é sempre em português (pt_BR, sem edição), com categoria
   Utilidade ou Marketing, nome na Meta formatado em snake_case enquanto se digita, exemplo de cada
   variável (como na tela da Meta) e prévia com a formatação do WhatsApp (*negrito*, _itálico_,
   ~tachado~, ```mono```, listas e citação). Botões como no portal da Meta: link fixo, link variável
   (o valor do cliente entra no fim do link e é mapeado como as variáveis do corpo) e resposta
   rápida, com a prévia embaixo do balão. O template nasce rascunho, que pode ser salvo incompleto
   (só o nome interno é obrigatório) e editado pelo botão "Editar"; o botão "Enviar para
   aprovação" da tabela confere as regras da Meta e manda com os exemplos e, se tiver cabeçalho, a
   imagem já subida (por isso a imagem vem antes do envio), e o status é acompanhado depois.
   Template já enviado também edita e volta para reanálise, nas regras da Meta (só aprovado,
   reprovado ou pausado; nome e idioma fixos; categoria fixa depois de aprovado; aprovado edita
   1 vez a cada 24 h e 10 a cada 30 dias) e, se estiver em uso numa faixa, sem mudar as variáveis;
   fora disso, "Cadastrar como novo template" copia o conteúdo para um rascunho novo. Templates sincronizados
   da Meta continuam valendo em qualquer idioma. Templates com cabeçalho de imagem permitem subir a imagem, reaproveitada em
   todo envio daquele template; se ela passar do limite do WhatsApp, o sistema mostra a versão
   otimizada para o usuário aprovar (ver "Limitações conhecidas").
3. **Faixas de cobrança** (**Configurações → Faixas**) — as faixas da régua (faixas de atraso)
   podem ser sincronizadas a partir das faixas de atraso configuradas
   (`POST /faixas/sincronizar-faixas-atraso`) ou criadas pelo wizard em três passos: nome e
   template → número(s) de envio → variáveis (nomes de coluna sugeridos para o modelo de planilha;
   o mapeamento de verdade acontece no upload, veja o próximo passo). Cada faixa tem um ou mais
   **envios** (par número + template, `faixa_envios`); todos os envios ativos da faixa disputam a
   mesma fila, então cada cliente é reservado por um só número.
4. Dentro da faixa: baixe o **modelo de planilha** (sugestão de colunas: Codigo, Nome, CPF,
   Celular, Valor) ou suba direto a planilha que já tiver. O sistema lê o cabeçalho (primeira
   linha) e mostra um mapeamento em lista suspensa — você escolhe qual coluna real vira cada
   variável do template e cada um dos campos obrigatórios de toda planilha:
   - **Código** — SETA de até 8 dígitos; se vier com menos, completa com zero à esquerda.
   - **Nome** — se vier o nome completo, usa só o primeiro nome.
   - **CPF** — formata com pontos e traço (`000.000.000-00`); se faltar dígito, completa com zero
     à esquerda.
   - **Celular** — normalizado para `55DD9XXXXXXXX` (ver validação por linha abaixo).

   A coluna de valor é opcional no mapeamento. Só depois de confirmar o mapeamento a planilha é
   importada para a fila (`app/upload_service.py`).
5. Validação por linha: telefone é normalizado para `55DD9XXXXXXXX` (detecta se falta o DDI `55`
   ou o 9º dígito e completa; se tiver menos dígitos que o padrão, a linha vai para o **relatório
   de telefones inválidos**, com código do cliente e telefone informado). Linhas sem código,
   nome ou CPF válidos são rejeitadas e listadas no resultado do upload, assim como clientes da
   **blacklist**. Também é rejeitado quem já está pendente/reservado na fila de **qualquer** faixa
   ou já foi cobrado **hoje** (horário de Brasília) em qualquer caminho — a regra fixa é no máximo
   uma cobrança por cliente por dia (`app/elegibilidade.py`); em outro dia o cliente pode voltar. A
   única exceção é a campanha com "Incluir quem já recebeu mensagem hoje" (ver Campanhas).
   O valor pode vir escrito de vários jeitos ("1.500,00", "1 500,00", "10,00 reais", "US$ 50"):
   vale o primeiro número. Linha com valor zerado não entra direto: o resultado do upload lista
   essas linhas com os valores que o sistema tem do cliente (valor em atraso com juros, em aberto,
   a cobrar), e o usuário escolhe um deles, digita outro ou descarta
   (`POST /faixas/{id}/uploads/valores-zerados`).
6. O ritmo e a janela de disparo são **globais** (**Configurações → Horário**,
   `global_dispatch_config`): **intervalo entre rodadas**, **quantidade de cobranças por rodada** e
   **janela de agendamento** (dias/horário, em horário de Brasília), valendo para todas as faixas e
   envios. Na mesma aba, **"Cobrar esta base agora"** (`POST /faixas/{id}/dispatch-now`) roda a
   faixa imediatamente, sem esperar o agendamento. A fila da faixa é acompanhada quase em tempo
   real (atualização automática a cada poucos segundos).
7. O **worker interno** (`app/worker.py`, APScheduler dentro do próprio processo do backend) roda o
   ciclo de disparo a cada `DISPATCH_WORKER_INTERVAL_SECONDS`: para cada envio ativo e devido,
   reserva um lote de pendentes da fila da faixa, confere de novo pausa/blacklist/uma-por-dia antes
   de cada item e envia (`app/dispatch_service.py`) pela Graph API da Meta ou pela inbox do
   Chatwoot, conforme o número, atualizando o status (enviado/erro), com log de erro consultável.
   Mensagens de erro (Meta ou Chatwoot) são traduzidas para português claro (`app/utils/erros.py`).
   No Chatwoot, respostas assíncronas de rejeição da Meta/WhatsApp chegam via webhook
   (`POST /chatwoot/webhook`), revertendo o item para status de erro, registrando o motivo traduzido
   no log de erros e liberando o lead para nova cobrança. Número desativado em Configurações não
   envia (os itens ficam pendentes). Recusa 4xx da Meta ou do Chatwoot libera o cliente para outra
   base no dia; 5xx, timeout ou queda de rede ocupam o cliente no dia, porque a mensagem pode ter saído. Item com variável sem valor para o template
   do envio vira erro sem chamar a Meta. Falha no meio de um lote devolve a pendente os itens que
   nem foram tentados.
   O mesmo worker roda as rotinas do dia (extração automática de leads a partir de N min antes da
   janela, ou mais tarde no mesmo dia se o backend estava fora,
   remarketing, régua de quem recebeu campanha, campanhas e expiração da fila no fim do dia), a
   cópia das baixas do SETA e, às 3h, a cópia das compras do SETA.
   O erro `131026: Message undeliverable` tenta outro telefone do SETA, na ordem
   `telefone2`, `telefone4`, `telefone3`, `telefone1`, sem repetir números recusados.
   Reaproveita o mesmo item da fila e respeita pausas, blacklist e o limite por cliente/dia.
   Havendo alternativa, volta à fila sem log de erro; só entra em **Telefones inválidos**
   quando as opções se esgotam. Retornos são recebidos pelo webhook e consultados pelo ID
   exato da mensagem. Erros 131026 já gravados no CRM são reprocessados após a atualização.
   O relatório e o Excel de telefones inválidos incluem CPF após o código do cliente.
8. **Dashboard** — pendentes (e quantos estão pausados), enviados, erros, telefones inválidos,
   "Pagaram em até N dias" (via SETA; a janela vem de Configurações → Indicadores, padrão 7,
   e "Qualquer data após a cobrança" vira "Pagaram após a cobrança") e por faixa. Cada card abre o
   relatório dele com o mesmo período (`/relatorios?aba=…&de=…&ate=…`). A tela se atualiza
   sozinha sem F5: resumo da fila a cada 30 s, leads a cada 60 s e orçamento a cada 15 min,
   parando enquanto a aba está oculta. O card de pagamentos (SETA) e a efetividade não se
   atualizam sozinhos, só ao abrir, trocar o filtro ou em "Atualizar agora". Os pedidos
   automáticos (`auto=true`) leem do cache compartilhado no Redis (15 s o resumo, 10 min o
   orçamento).
   **Tempo real** (`app/painel_tempo_real.py`, WebSocket `/dashboard/ws?de=&ate=`): os cards
   Pendentes (e pausados), Cobranças, Erros e Telefones inválidos mudam na hora. Triggers do
   Postgres (migration `a3d5f7b9c1e2`) avisam no canal `painel` o saldo de cada comando em
   `cobranca_fila`, `telefones_invalidos` e `pausas_envio`, só no commit; um ouvinte (dono da trava
   `lock:painel-ouvinte`) é o único que escreve o contador do dia no Redis (`painel:dia:AAAA-MM-DD`,
   GMT-3, 35 dias) e publica no canal Redis `painel`. O dia nasce de `consultas_fila.contar_cards`
   (a mesma contagem do resumo e dos relatórios) quando alguma tela o pede; a carga guarda o
   snapshot do Postgres e aviso de transação já contada nele não soma de novo, então o contador
   fica exato sem recontagem periódica. Ao reconectar, o ouvinte descarta os dias e eles são
   recarregados. Pausados é recontado com cache de 5 s, renovado na hora quando uma pausa muda.
   O WebSocket confere `Host`/`Origin` como o middleware, autentica pelo cookie de sessão e
   reconfere a sessão a cada 30 s. Sem WebSocket (proxy sem upgrade, Redis fora, período com mais de 35 dias) a
   tela segue com o polling de 30 s. Métricas: `painel_tempo_real.metricas()`.
   **Proteção do SETA** (`app/cache.py` + `seta_client.consulta_pesada`): o relatório pesado é um
   *snapshot* no Redis (resultado + `gerado_em`), com a chave igual para todos os usuários e abas.
   Pedidos iguais ao mesmo tempo fazem **uma** consulta (single-flight: quem chega depois espera
   ou recebe "processando"); a trava tem dono (só quem a pegou a solta) e batimento; no máximo
   `SETA_MAX_CONSULTAS_PESADAS` consultas pesadas rodam juntas e a fila de espera é pequena (cheia =
   429 com `Retry-After`, não 503). Efetividade e Quem pagou guardam 5 min e, vencido, mostram o último
   snapshot (até 30 min) com o aviso "dados de …" enquanto atualizam uma vez em segundo plano;
   ordenar, paginar e as três exportações da efetividade leem o snapshot, sem ir ao SETA.
   O card de pagamentos usa o mesmo snapshot de Quem pagou (mesma janela). A base de cobrança fica 10 min e
   não serve dado vencido (ela gera os leads). Erro do cálculo não é guardado: fica 30 s em
   quarentena para o polling não refazer a consulta. No front-end, trocar o filtro ou sair da tela
   cancela a consulta (`AbortController`, `useRequisicaoUnica`), o polling usa espera crescente com
   jitter e os botões de aplicar ficam desabilitados enquanto a consulta anterior roda.
   A tabela **Por faixa** mostra Pendente, Erro, Enviado, Clientes cobrados (clientes distintos
   que receberam mensagem da faixa com envio no período filtrado, a mesma base das Cobranças),
   Frequência (mensagens do período ÷ clientes cobrados), Pagaram após cobrança (clientes
   cobrados que pagaram depois do primeiro envio do período; o número abre Quem pagou com
   `base=envios`, a mesma lista), % Rep. (pagaram da faixa ÷ soma das
   faixas, fecha 100%), % Conv. (pagaram ÷ cobrados), Valor pago e ROAS (valor pago ÷ custo do
   WhatsApp das mensagens da faixa), com linha de total
   (clientes e pagamentos contados uma vez, mesmo em mais de uma faixa) e um ícone 🛈 com a
   fórmula de cada indicador. Essa é a ordem padrão: cada usuário arrasta os títulos para
   reordenar as colunas (a Faixa fica sempre na primeira) e a ordem fica salva na conta dele
   (`users.colunas_por_faixa`, `GET`/`PUT /dashboard/colunas-por-faixa`), valendo em qualquer
   navegador. **ROAS** (aqui e na Efetividade, onde é Recebimento ÷ custo): a Meta só informa o custo por
   dia e número, então o custo de cada dia é dividido pelas mensagens enviadas pela fila no dia
   (`custo_whatsapp.custo_por_envio`, sobre `consultas_fila.envios_por_dia`) e cada faixa, lead ou loja
   leva o custo dos seus envios; o gasto da Meta fica 10 min no Redis. Sem custo da Meta o ROAS
   mostra "—". A matriz **Base de cobrança — cluster × faixa** tem as abas
   Clientes, SPC, Valor em aberto e Valor em atraso (só parcelas vencidas, original ou com multa
   e juros conforme o filtro "Valor considerado").
   As tabelas do Dashboard (Por faixa, Efetividade, gasto por número e a matriz) começam com no
   máximo 70% da altura da tela e têm uma barra embaixo para ajustar a altura (arrastar, ou ↑/↓
   com o foco nela; duplo clique volta ao padrão), guardada no navegador por tabela
   (`components/TabelaAjustavel.tsx`). Na rolagem, cabeçalho, linha de total e primeira coluna
   ficam fixos.
   **Pagamentos**: o card de pagamentos do Dashboard, Efetividade e "Quem pagou" leem a tabela local
   `pagamentos_seta` (baixas do SETA de quem já foi cobrado), não o SETA direto. O worker relê as
   baixas só enquanto alguém usa o CRM (requisição de usuário nos últimos 15 min, sem contar a
   atualização automática da tela), no máximo a cada 30 min (`PAGAMENTOS_SYNC_INTERVAL_SECONDS`), por cliente, a partir da última
   leitura menos 7 dias (pega baixa retroativa e estorno); cliente sem cobrança nos últimos 60
   dias é relido uma vez por dia. Cliente cobrado depois da última rodada é buscado na hora, só
   ele. Ver `app/services/pagamentos_seta.py`.
9. **Relatórios** — abas na ordem dos cards do Dashboard (pendentes, envios realizados, erros,
   telefones inválidos e quem pagou), com filtro por período, faixa e **Campanha** (na URL) e
   exportação em Excel (.xlsx) já formatado. Na fila, "Campanha" filtra pela faixa da campanha
   (`filtro_campanha`); em "Quem pagou", por `Lead.campanha_id`, como na Efetividade.
10. **Pausas** — na aba Pendentes, qualquer usuário pode pausar (motivo obrigatório, data final
   opcional), retomar ou parar o envio por cliente, régua (faixa) ou loja. Pausa não muda o status
   do item: o worker só deixa de pegar o que está retido, inclusive o que entrar na fila depois.
   Parar marca os pendentes do escopo como `cancelled` (com quem parou e quando), sem apagar.
   **Descartar fila** apaga os pendentes que batem com os filtros da tela (faixa, campanha, loja e
   período), como a expiração do fim do dia faz: não fica registro de parado e o cliente pode voltar
   à fila (`POST /relatorios/pendentes/descartar`). Item já reservado por um envio em andamento fica.
11. **Campanhas** (menu logo abaixo de Cobrança) — cobranças fora das faixas de atraso, cada uma
   com os mesmos filtros da Cobrança (inclusive "valor em atraso" de X a Y, original ou com multa e
   juros, e "Importar lista de lojas" a partir de um .xlsx com a coluna de código da loja), template
   e número atribuídos na própria campanha e **Envio automático** opcional: ligado, roda sozinha todo
   dia de disparo no período de/até (um dia só = mesma data nas duas pontas), com recontato opcional
   a cada N dias (sem ele, cada cliente recebe uma vez por campanha); desligado, só entra na fila pelo
   "Colocar na fila agora". **Pausar** (retém os pendentes e o envio automático até retomar, via
   pausa por faixa) e **Parar** (cancela os pendentes e desliga o automático) ficam na lista e na
   campanha. A planilha de clientes pode ser escolhida já na criação. Só entra quem está em atraso no SETA, ou,
   escolhendo a faixa **Antecipado** no filtro de faixa, quem ainda não tem nada vencido (parcela mais
   antiga vencendo de 2 a 365 dias à frente; o lembrete "-1" continua fora). Antecipado é uma faixa de
   atraso só de campanhas (`config_faixas_atraso.so_campanhas`, selo "Só campanhas" em Regras de
   cobrança): fica fora da matriz do WhatsApp, da rotina diária, da Cobrança, do Remarketing e do
   "Sincronizar faixas"; na campanha fica sozinha no filtro de faixa, sem filtro de valor em atraso e
   sem a variável "Valor em atraso" (use "Valor da próxima parcela"). Quem a recebe não vai para a
   régua no dia seguinte (não está em atraso). Antecipado não tem faixa de envio própria em
   Configurações → Faixas (nem pelo "Nova faixa"): o único jeito de enviar para ela é por campanha.
   No "Por faixa" do Dashboard, a linha Antecipado aparece quando há envio de campanha para ela no
   período. A faixa de atraso **"1"** (1 dia de atraso) faz parte da régua: a migration
   `e6b2d8f4a1c7` a cria (regra de cobrança e faixa da régua, sem número/template e fora da matriz
   do WhatsApp) onde nenhuma faixa cobria o dia 1. Uma planilha de clientes (coluna
   Codigo ou CPF) restringe a base; com "valores da planilha", Valor, Celular e as demais colunas
   (nas variáveis do template) vêm dela. Com **"Todos os clientes da planilha com parcela em aberto,
   em atraso ou não"** (`Campanha.todos_da_planilha`), entra todo cliente da planilha que tem parcela
   em aberto no SETA, vencida ou não (quem não tem parcela em aberto fica de fora): em atraso, na sua
   faixa de atraso (um dia que nenhuma faixa cobre vira uma faixa só com ele); sem atraso (inclusive
   o lembrete), na faixa Antecipado. A campanha fica sem filtro de faixa e de valor em
   atraso e sem a variável "Valor em atraso". Com **"Incluir quem já recebeu mensagem hoje"**
   (`Campanha.incluir_cobrados_hoje`), a campanha sai da regra de uma mensagem por cliente por dia:
   entra na fila e envia mesmo para quem já recebeu outra mensagem hoje. Sem essa opção, quem já
   recebeu mensagem hoje fica fora do envio. O envio dela continua contando como a cobrança do dia
   para a régua e os outros caminhos. O agendador roda as campanhas do dia junto com o
   remarketing, antes do horário de início. Por baixo, cada campanha tem uma faixa própria
   ("Campanha: …", `app/campanhas.py`), fora da lista de faixas de atraso. O **Remarketing do
   Renegocie** virou uma aba desta tela (`/remarketing` redireciona para lá), com template e número
   atribuídos no próprio segmento.
   Quem entra na fila da campanha vira também um **lead da sua faixa de atraso marcado com a
   campanha** (`Lead.campanha_id`; `""` = régua). No próximo dia de disparo depois do envio, o
   agendador coloca esse cliente na fila da régua da faixa de atraso em que ele estiver naquele dia
   (base do SETA recalculada; quem pagou fica de fora), porque só sai uma cobrança por cliente por
   dia (`campanhas.enfileirar_na_regua`). A Efetividade e "Exportar leads enviados" do Dashboard têm
   o filtro **Campanha** (todas, só a régua ou uma campanha, inclusive excluídas). O item da fila de
   campanha/remarketing guarda a faixa de atraso do cliente (`QueueItem.faixa_atraso`): o "Por faixa"
   do Dashboard e os relatórios filtrados por uma faixa de atraso contam esses envios nela. Nas abas
   Pendentes e Erros (e nas exportações), "Faixa de atraso (régua)" e "Campanha" são colunas separadas. A tabela `faixas` tem o campo
   **`tipo`** (`regua`, `campanha` ou `remarketing`, migration d4f8b2c6e0a3): é ele que decide o
   que aparece em Faixas, o que recebe planilha, o que conta como faixa de atraso e como a faixa é
   agrupada no filtro dos Relatórios.
   A Efetividade tem a visão **Por campanha** (a régua numa linha própria) e a lista de campanhas do
   filtro acompanha o "Enviado de/até" antes de aplicar (`GET /campanhas/opcoes?enviado_de&enviado_ate`).
   A lista de Campanhas mostra "Criado em" e filtra por período de criação ou de envio
   (`GET /campanhas?periodo=criacao|envio&de&ate`). Onde se importa lista de lojas por .xlsx, o
   usuário escolhe a coluna da loja (`POST /lojas/colunas-planilha`, depois `ler-planilha?coluna=N`).
   O **Remarketing do Renegocie é uma campanha fixa** por segmento (`app/campanhas_fixas.py`): não
   se cria nem se exclui, aparece no topo da lista de Campanhas (`GET /campanhas/fixas`) e usa o id
   `remarketing:<SEGMENTO>` em `Lead.campanha_id` e nos filtros "Campanha". Como numa campanha, quem
   entra na fila vira lead da faixa de atraso, o envio o marca como cobrado e no dia seguinte ele vai
   para a régua; Efetividade, exportação de leads e Relatórios o tratam como as outras campanhas.

## Testes / validação de mudanças

### CI (GitHub Actions)

A cada evento no GitHub (PR aberto/atualizado, push, horário agendado), o GitHub liga uma máquina
Linux temporária, baixa o código, roda os passos de um arquivo de `.github/workflows/` e mostra o
resultado como ✅/❌ no commit e no PR. Os workflows **só leem e conferem o código**: não alteram
arquivo nem fazem commit. A única exceção é o `deploy.yml`, que publica na VPS depois do CI verde
na `main`; para isso, o usuário `deploy` da VPS lê o repositório com uma deploy key **somente
leitura** (remote `git@github.com:TopFama/FintechCRM.git` em `/opt/FintechCRM`).

| Workflow | Quando roda | Jobs (cada um numa máquina própria, em paralelo) |
|---|---|---|
| `testes.yml` | Todo PR e todo push na `main` (menos quando só mudam arquivos `.md`), toda segunda às 7h UTC e manual ("Run workflow", suíte e2e inteira por padrão) | **Backend (scripts de teste)**: Postgres e Redis descartáveis + `tests/rodar_todos.sh`. **Arquitetura (import-linter)**: `lint-imports` com `apps/backend/.importlinter`. **Frontend (build)**: `npm run build:frontend`. **E2E (Playwright)**: sobe Postgres, Redis, backend com Meta/Chatwoot/SETA/Google/Renegocie simulados e frontend, e um navegador percorre as telas (relatório do Playwright fica 7 dias como artefato quando falha). Cada spec prepara o próprio estado por API e os cenários têm tags de funcionalidade; em PR e em push na `main`, roda só os cenários que os arquivos alterados podem quebrar mais a fumaça (`e2e/selecionar-telas.mjs`; mudança global ou arquivo fora do mapa roda tudo; nada afetado pula o e2e), e a suíte inteira roda toda segunda-feira e sob demanda. **Seletor do e2e**: `node --test e2e/selecionar-telas.test.mjs` |
| `e2e-mapa.yml` | PR que mexe em `e2e/selecionar-telas.mjs`, `e2e/tests/**`, `e2e/ambiente/**` ou no próprio workflow; manual | Um job por spec e por tag: roda cada um sozinho num ambiente novo, para provar que a seleção do e2e em PR não depende de cenário que o seletor não traga |
| `security-scan.yml` | Push/PR que mexe em `package.json`, `package-lock.json` ou `apps/backend/requirements.txt`; toda segunda às 9h UTC (6h em Brasília, pega falha nova em dependência que não mudou); manual | **npm audit (frontend)**: reprova vulnerabilidade alta ou crítica. **pip-audit (backend)**: reprova qualquer vulnerabilidade conhecida, exceto a exceção documentada no próprio arquivo (`ecdsa`, PYSEC-2026-1325, não afeta o app porque o JWT usa HS256) |
| `deploy.yml` | **Automático** depois que o `testes.yml` passa inteiro num push na `main` (publica exatamente o commit testado; CI vermelho não publica). Manual ("Run workflow", `testar` ou `deploy`). PR que mexe no próprio arquivo roda o `testar` | Entra na rede Tailscale só durante o job (dispositivo efêmero `tag:ci`, segredos `TS_OAUTH_CLIENT_ID`/`TS_OAUTH_SECRET`; o SSH da VPS não aceita conexão da internet) e na VPS por SSH como o usuário `deploy` (`VPS_HOST` = IP do Tailscale da VPS, `VPS_USER`, `VPS_SSH_KEY`, `VPS_KNOWN_HOSTS`, opcional `VPS_PORT`). **testar**: só lê (usuário, commit atual, alterações locais, containers, acesso da VPS ao GitHub). **deploy** (automático ou manual na `main`): `git merge --ff-only` do commit em `/opt/FintechCRM` (commits só da VPS vão para uma branch `vps-local-*` e ela volta ao commit testado) e `docker compose up -d --build`. Os dois terminam conferindo `https://fintech.lojastopfama.com.br/api/health` |

**Merge na `main`**: não há auto-merge do GitHub. Toda mudança entra por PR de uma branch de
trabalho (exceto commit só de documentação `.md`, que vai direto para a `main`), e quem decide o merge é o agente de IA designado como maintainer do repositório,
depois de avaliar os workflows e o diff do commit mais recente do PR; conflito que exige escolher
entre dois comportamentos, ou mudança sensível, vai para o dono decidir antes. Critérios em
[`AGENTS.md`](./AGENTS.md) → "Merge na main". O
deploy é automático: quando o CI da `main` passa inteiro depois do merge, o workflow `deploy.yml`
publica na VPS exatamente o commit testado (`docker compose up -d --build`, que já cobre
dependência nova e migration, rodada na subida do backend) e confere a saúde do backend em
produção. CI vermelho na `main` não publica nada. Para refazer um deploy à mão: Actions →
"Deploy (VPS)" → Run workflow na `main`, ação `deploy`. Passo a passo, infraestrutura e erros
comuns: [Deploy em produção (VPS)](#deploy-em-produção-vps).

### Validação local

Para validar localmente antes de subir:

- **Scripts de teste do backend** (`apps/backend/tests/`): `./tests/rodar_todos.sh` dentro de
  `apps/backend`. Precisa de um Postgres UTF-8 em `localhost:15432` (usuário `postgres`, senha `t`)
  e do venv em `.venv`; cada script recria o próprio banco e imprime `OK` na última linha.
  `test_caracterizacao_envios.py` fotografa o fluxo de envio (fila, pausa, blacklist, uma mensagem
  por cliente por dia).
- **Regras de import entre camadas**: `pip install import-linter && lint-imports` dentro de
  `apps/backend` (contratos em `apps/backend/.importlinter`, explicados em
  `docs/architecture/dominios-e-camadas.md`).
- **E2E (Playwright)**: ver [`e2e/README.md`](./e2e/README.md).
- **Checagem manual de endpoints**: aponte `DATABASE_URL` para um Postgres (ou SQLite, para
  checagens rápidas sem `Enum`/tipos do Postgres) e exercite os endpoints relevantes com o
  `TestClient` do FastAPI (`from fastapi.testclient import TestClient`), que já passa pelo
  `lifespan` (migrations + criação do admin) igual à aplicação real.
- **Mudança em `app/models.py`**: gere a migration (`alembic revision --autogenerate`) e valide o
  ciclo `upgrade head` → `downgrade base` → `upgrade head` e `alembic check` contra um Postgres
  real antes de commitar — ver seção Migrations acima.
- **Frontend**: `npm run build` (roda `tsc -b && vite build`) já pega a maioria dos erros de tipo
  e import quebrado.

## Deploy em produção (VPS)

Produção roda na VPS com o mesmo `docker-compose.yml` do desenvolvimento, em `/opt/FintechCRM`,
atrás de `https://fintech.lojastopfama.com.br` (a saúde do backend fica em `/api/health`). Ninguém
publica à mão: o workflow `.github/workflows/deploy.yml` faz o deploy sozinho.

### Do merge até produção

1. O PR é mesclado na `main` (critérios em [`AGENTS.md`](./AGENTS.md) → "Merge na main").
2. O push na `main` roda o `testes.yml` com a suíte inteira (backend, import-linter, build do
   frontend e e2e completo).
3. Se **todos** os jobs passarem, o `deploy.yml` dispara (gatilho `workflow_run`) e publica
   **exatamente o commit testado**. CI vermelho não publica nada; commit só de `.md` não roda o
   `testes.yml` e, portanto, também não publica.
4. O job entra na rede Tailscale, conecta por SSH na VPS como `deploy` e, em `/opt/FintechCRM`:
   `git fetch origin main` → `git merge --ff-only <commit>` (se a VPS tiver commits fora da `main`, eles
   vão para uma branch `vps-local-*` e ela volta ao commit testado) → `docker compose up -d --build`. A
   migration roda sozinha na subida do backend, e dependência nova entra no rebuild da imagem.
5. Termina chamando `/api/health` até 30 vezes, a cada 5 s. Um 502 logo depois do rebuild é
   normal (o backend ainda está subindo); o job só falha se não responder em 150 s.

O Dashboard em tempo real usa WebSocket em `/api/dashboard/ws`: o Nginx da VPS precisa repassar
o upgrade. A config disso fica versionada em `deploy/nginx/` e o deploy a valida (`nginx -t`) e
recarrega o Nginx. Se o `nginx -t` falhar, o deploy volta o código e não publica nada. Depois do
health, o deploy confere se o WebSocket responde `101` pelo proxy e, se não, deixa um aviso. Sem o
upgrade a tela continua com o polling de 30 s.

Ligar uma vez, como root na VPS (depois que um deploy trouxe `deploy/nginx/`):

```bash
ln -s /opt/FintechCRM/deploy/nginx/fintechcrm-upgrade.conf /etc/nginx/conf.d/
ln -s /opt/FintechCRM/deploy/nginx/fintechcrm-websocket.conf /etc/nginx/snippets/
# no location que repassa /api/ em /etc/nginx/sites-available/fintech.lojastopfama.com.br:
#   include snippets/fintechcrm-websocket.conf;
# (tire desse location um proxy_http_version, Upgrade, Connection ou proxy_read_timeout que
#  já existam: repetidos, o nginx -t acusa "duplicate")
echo 'deploy ALL=(root) NOPASSWD: /usr/sbin/nginx -t, /usr/bin/systemctl reload nginx' > /etc/sudoers.d/deploy-nginx
chmod 440 /etc/sudoers.d/deploy-nginx && visudo -c
nginx -t && systemctl reload nginx
```

O deploy só usa esses dois comandos com sudo. Sem os links ou sem o sudoers, ele segue
publicando normalmente e só avisa que o Nginx não foi recarregado.

Um deploy por vez (concorrência `deploy-vps`) e nunca cancelado no meio do `docker compose`. O log
de cada deploy mostra `Código: <antes> -> <depois>` e o estado dos containers (Actions → "Deploy
(VPS)"). O `.env` da VPS fica fora do git e o deploy não mexe nele: variável nova vai à mão nesse
arquivo **antes** do merge que passa a exigi-la.

### Ações manuais

Actions → "Deploy (VPS)" → **Run workflow** na `main`:

- **testar**: só lê (usuário, commit atual, alterações locais, containers, acesso da VPS ao GitHub)
  e confere a saúde. Não muda nada. Serve para diagnosticar a conexão.
- **deploy**: publica a `main` atual (para refazer um deploy que falhou por algo fora do código).
  Recusado fora da `main`.

**Voltar uma versão**: o `--ff-only` nunca anda para trás. Para desfazer uma mudança em produção,
reverta o commit na `main` (`git revert`, por PR); o commit de revert passa pelo CI e é publicado
como qualquer outro.

### Como a infraestrutura está montada

Só é preciso refazer isto se a VPS, as chaves ou a conta do Tailscale mudarem.

- **VPS**: usuário `deploy` no grupo `docker`, dono de `/opt/FintechCRM`. O SSH (porta 22) só aceita
  conexão pela interface do Tailscale (`tailscale0`); da internet, a porta fica fechada no `ufw`.
- **Chave de acesso à VPS**: par de chaves do usuário `deploy` (a pública em
  `~deploy/.ssh/authorized_keys`, a privada **só** no segredo `VPS_SSH_KEY`; não fica cópia na VPS).
- **Leitura do GitHub pela VPS**: deploy key **somente leitura** do repositório (GitHub → Settings →
  Deploy keys, sem "Allow write access"), com a privada em `~deploy/.ssh/github_leitura` e um
  `Host github.com` no `~deploy/.ssh/config` apontando para ela. O remote de `/opt/FintechCRM` é
  `git@github.com:TopFama/FintechCRM.git`.
- **Tailscale**: a tag `tag:ci` (dona `autogroup:admin` em `tagOwners`), um grant `tag:ci` → IP do
  Tailscale da VPS na porta `tcp:22`, e um OAuth client (Settings → Trust credentials) com
  permissão de escrita em Auth Keys e a tag `tag:ci`. Cada job entra como dispositivo efêmero e sai
  ao terminar.
- **Segredos do repositório** (GitHub → Settings → Secrets and variables → Actions):

  | Segredo | O que é |
  |---|---|
  | `TS_OAUTH_CLIENT_ID` / `TS_OAUTH_SECRET` | OAuth client do Tailscale |
  | `VPS_HOST` | IP do Tailscale da VPS (`tailscale ip -4` na VPS), não o IP público |
  | `VPS_USER` | `deploy` |
  | `VPS_SSH_KEY` | chave privada do usuário `deploy` |
  | `VPS_KNOWN_HOSTS` | saída de `ssh-keyscan -p 22 <VPS_HOST>`; o job só conecta se a VPS apresentar essa chave |
  | `VPS_PORT` | opcional; padrão 22 |

### Quando o deploy falha

| Passo / erro | Causa provável |
|---|---|
| "Conferir os segredos" → `Segredos faltando: ...` | Segredo não cadastrado no repositório |
| "Testar a conexão" → `Connection timed out` | Job fora do Tailscale ou grant `tag:ci` → VPS:22 ausente; `VPS_HOST` com o IP público |
| `Host key verification failed` | `VPS_KNOWN_HOSTS` desatualizado (VPS reinstalada ou IP trocado) |
| `could not read Username for 'https://github.com'` | Remote da VPS em HTTPS: trocar para o SSH da deploy key (acima) |
| `VPS com commits fora do alvo ... e alterações não commitadas` | Alguém comitou e deixou alteração pendente direto na VPS: resolver lá (`git status`) antes de publicar de novo. Sem alteração pendente o deploy guarda os commits só da VPS na branch `vps-local-*` e volta ao commit testado |
| "Saúde do backend" → não respondeu em 150 s | Backend não subiu: `docker compose logs backend` na VPS (migration, `.env`, dependência) |

## Limitações conhecidas / próximos passos

- **Limite de consultas ao SETA por processo**: `SETA_MAX_CONSULTAS_PESADAS` e a fila de jobs do
  cache valem dentro do processo do backend (hoje um uvicorn só, com o worker dentro). Com mais de um
  processo, o limite global teria de virar um semáforo no Redis (o ponto único é
  `seta_client.consulta_pesada`); a trava por chave e o snapshot já são do Redis e valem para todos.
- **Imagem de header**: pela Meta, a imagem subida em Templates vai como mídia (`media_id`, subida
  uma vez por número e renovada a cada 20 dias; ver `dispatch_service.media_id_da_imagem`), sem
  precisar de link público. Pelo Chatwoot ainda é link: vale `PUBLIC_BASE_URL` (opcional) ou o
  endereço público por onde a imagem foi subida; sem nenhum dos dois o envio dá erro claro.
  Template com cabeçalho de imagem e sem imagem subida vira erro sem chamar a Meta.
- **Tamanho da imagem de header** (`app/utils/imagem.py`): o limite é o da Meta, 5 MB em .jpg ou
  .png de 8 bits RGB/RGBA. Vale para os dois canais: o Chatwoot não tem limite próprio para o
  cabeçalho do template, ele só repassa o link para a Meta (`image.link`), que baixa a imagem.
  No upload (Configurações → Templates, aceita .jpg, .png e .webp até 30 MB e 60 MP), a imagem
  que já cabe e está no formato certo é guardada como veio. A que não cabe (ou vem em .webp,
  CMYK, paleta, rotação por EXIF) é otimizada com a menor perda possível, nesta ordem: PNG sem
  perda → JPEG com a maior qualidade que couber (95 a 82) na resolução original → redução da
  resolução só o necessário (JPEG qualidade 88). PNG com transparência continua PNG e só perde
  resolução. A versão otimizada **não** entra no template sozinha: fica pendente (pasta
  `media/pendentes`, expira em 1 h) e a tela mostra a original ao lado dela para o usuário
  aprovar (`POST /templates/{id}/image/confirmar`) ou recusar
  (`DELETE /templates/{id}/image/pendente`); recusando, o template fica com a imagem anterior e o
  aviso pede uma imagem de até 5 MB.
- **Envio de template para aprovação** (`POST /templates/{id}/enviar-para-aprovacao`, e a
  reanálise de `PUT /templates/{id}` em template já enviado): manda `example.body_text` com o
  exemplo gravado de cada variável do corpo, os botões em `BUTTONS` (link variável com o link
  completo de exemplo) e, com cabeçalho de imagem,
  `example.header_handle` com a imagem do template subida pela Resumable Upload API da Meta (o app
  vem de `GET /app` com o próprio token, sem configuração a mais). As regras de cadastro da Meta
  (nome `[a-z0-9_]`, corpo até 1024 caracteres, variáveis em sequência e fora do começo e do fim)
  e de botões (até 10, no máximo 2 links, texto até 25 caracteres, `{{1}}` só no fim do link,
  respostas rápidas juntas) ficam em `schemas.pendencias_template`, conferidas antes de ir para a
  Meta; a tela só espelha para formatar e avisar. No envio, o link variável vai como parâmetro do
  botão (`meta_client.send_template_message`) ou em `processed_params.buttons` no Chatwoot. Só Utilidade e
  Marketing: Autenticação exige o formato próprio de código da Meta e não é cadastrada aqui.
- **Retry de envio**: hoje, uma falha de envio marca o item como `error` e fica visível no
  dashboard; o único reprocessamento automático é o erro `131026` do Chatwoot, que tenta o próximo
  telefone do cadastro. Retry geral com backoff para os demais erros ainda não está implementado.
- **Fila em "tempo real"**: o acompanhamento da fila no portal usa polling (nova consulta a cada
  poucos segundos), não WebSocket — simples e suficiente para o volume atual, mas vale revisar se
  o volume de faixas abertas simultaneamente crescer muito.
- **Autenticação e segurança**: login usuário/senha + JWT. `POST /auth/login` grava o JWT num cookie
  `access_token` httpOnly (o frontend nunca guarda o token em `localStorage`/JS — mitiga roubo de sessão via
  XSS) e também devolve o token no corpo da resposta só para uso programático (scripts de validação,
  integrações), que autenticam via header `Authorization: Bearer`; `POST /auth/logout` limpa o cookie e
  revoga a sessão (o `jti` do JWT vai para `tokens_revogados`, então o token deixa de valer mesmo se
  copiado antes). Tentativas de login erradas são limitadas em memória (`app/rate_limit.py`). Só
  dois papéis existem: administrador (`is_admin=true`, sempre o usuário de `ADMIN_EMAIL`) e usuário comum.
  O admin gerencia outros usuários em **Usuários** (`GET/POST/DELETE /users`) — quem ele cria tem acesso a
  tudo que o admin tem, exceto gerenciar outros usuários; não há papéis mais granulares que isso. Segredos
  sensíveis guardados no banco (tokens de acesso da Meta e refresh token do Google OAuth) são cifrados
  simetricamente com a chave dedicada `ENCRYPTION_KEY`. A perda dessa chave impede a leitura desses segredos
  e exige cadastrar novamente os tokens da Meta e reconectar a conta Google.

## Migração a partir do n8n

Este sistema foi desenhado a partir do fluxo `FINTECH - FLUXO DE COBRANÇA` que rodava no n8n:
- `templates_wpp` (Supabase) → tabelas `templates` + `template_variables` (Postgres próprio).
- `cobranca_wpp` (fila) → tabela `cobranca_fila`.
- Regras de normalização/validação de telefone → `app/utils/phone.py` (mesma lógica do Code node).
- Rotação de números por faixa e reserva antes do envio → `app/worker.py` (vários envios
  número + template por faixa, `faixa_envios`, disputando a mesma fila) e `app/dispatch_service.py`
  (envio de cada item).
- Schedule Trigger (cron fixo) → `global_dispatch_config` (janela de dias/horário, intervalo e
  lote únicos para toda a operação, editáveis em Configurações → Horário, sem precisar editar
  workflow nenhum); `dispatch_configs` guarda, por envio, se ele está ativo, a última rodada e o
  "rodar agora".

## Para agentes de IA

Se você é um agente de codificação (Claude Code, Codex, etc.) alterando este repositório, leia
também o [`AGENTS.md`](./AGENTS.md) na raiz — convenções do projeto, onde fica cada coisa e como
validar uma mudança antes de considerá-la pronta.
