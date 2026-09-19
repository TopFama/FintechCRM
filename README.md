# FintechCRM — CRM de Cobrança via WhatsApp

Portal web para gerir cobrança via WhatsApp (API oficial da Meta) sem depender do n8n: o próprio
backend fala diretamente com a Graph API da Meta para listar/criar templates, listar números,
enviar mensagens e controlar agendamento/lote de disparo. Os dados vivem num Postgres próprio,
rodando em container — não há mais dependência do Supabase.

## Estrutura (monorepo)

```
FintechCRM/
  apps/
    backend/       # FastAPI + SQLAlchemy + APScheduler (worker de disparo) + cliente Graph API
      alembic/     # migrations do schema (versionadas, aplicadas automaticamente na subida)
    frontend/      # React + TypeScript + Vite
  docker-compose.yml
  .env.example
```

## Como rodar localmente

1. Copie `.env.example` para `.env` e preencha pelo menos `META_ACCESS_TOKEN` (token da API da
   Meta). WABA ID e `phone_number_id` de cada número **não** vão no `.env` — são cadastrados dentro
   do próprio portal, na tela **Números**, depois que o sistema estiver no ar.
2. Suba tudo:

   ```bash
   docker compose up --build
   ```

3. Acesse:
   - Portal: http://localhost:5173
   - API (docs interativas): http://localhost:8000/docs

4. Login inicial: o backend cria automaticamente um usuário admin na primeira subida, com
   `ADMIN_EMAIL` / `ADMIN_PASSWORD` definidos no `.env`.

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
3. **Faixas de cobrança** — wizard guiado: nome da faixa → template aprovado → número(s) de envio
   (com rotação automática quando mais de um) → mapeamento de cada variável interna do template
   para o nome da coluna da planilha.
4. Dentro da faixa: baixe o **modelo de planilha** (sugestão de colunas) ou suba direto a planilha
   que já tiver. O sistema lê o cabeçalho (primeira linha) e mostra um mapeamento em lista suspensa
   — você escolhe qual coluna real vira cada variável do template, o nome, o celular, o valor
   cobrado e o **código do cliente** (obrigatório: SETA de 8 dígitos ou CPF válido). Só depois de
   confirmar o mapeamento a planilha é importada para a fila.
5. Validação por linha: telefone é normalizado para `55DD9XXXXXXXX` (detecta se falta o DDI `55`
   ou o 9º dígito e completa; se tiver menos dígitos que o padrão, a linha vai para o **relatório
   de telefones inválidos**, com código do cliente e telefone informado). Linhas sem código de
   cliente válido ou com telefone duplicado na fila são rejeitadas e listadas no resultado do
   upload.
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
   por faixa e exportação em CSV.

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
- **Autenticação**: login simples (usuário/senha + JWT), sem papéis granulares, conforme escopo
  combinado para a v1.

## Migração a partir do n8n

Este sistema foi desenhado a partir do fluxo `FINTECH - FLUXO DE COBRANÇA` que rodava no n8n:
- `templates_wpp` (Supabase) → tabelas `templates` + `template_variables` (Postgres próprio).
- `cobranca_wpp` (fila) → tabela `cobranca_fila`.
- Regras de normalização/validação de telefone → `app/utils/phone.py` (mesma lógica do Code node).
- Rotação de números por faixa e reserva antes do envio → `app/worker.py`.
- Schedule Trigger (cron fixo) → `dispatch_configs` (intervalo/lote/janela configuráveis por
  faixa, editáveis pela própria interface, sem precisar editar workflow nenhum).
