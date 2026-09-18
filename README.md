# FintechCRM — CRM de Cobrança via WhatsApp

Portal web para gerir cobrança via WhatsApp (API oficial da Meta) sem depender do n8n: o próprio
backend fala diretamente com a Graph API da Meta para listar/criar templates, listar números,
enviar mensagens e controlar agendamento/lote de disparo. Os dados vivem num Postgres próprio,
rodando em container — não há mais dependência do Supabase.

## Estrutura (monorepo)

```
FintechCRM/
  apps/
    backend/   # FastAPI + SQLAlchemy + APScheduler (worker de disparo) + cliente Graph API
    frontend/  # React + TypeScript + Vite
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

## Fluxo do sistema

1. **Números** — cadastre os números de WhatsApp (WABA ID + phone number ID) conectados à Meta.
2. **Templates** — sincronize os templates já aprovados na Meta (por WABA ID) ou crie um novo
   template pelo portal (com opção de já submeter para análise da Meta e acompanhar o status de
   aprovação depois). Templates com cabeçalho de imagem permitem subir a imagem, reaproveitada em
   todo envio daquele template.
3. **Faixas de cobrança** — wizard guiado: nome da faixa → template aprovado → número(s) de envio
   (com rotação automática quando mais de um) → mapeamento de cada variável interna do template
   para o nome da coluna da planilha.
4. Dentro da faixa: baixe o **modelo de planilha** (colunas variam conforme as variáveis daquele
   template), preencha, suba de volta. O sistema valida telefone, evita duplicidade e insere na
   fila de cobrança.
5. Configure **intervalo entre rodadas de envio**, **quantidade de cobranças por rodada** e a
   **janela de agendamento** (dias/horário) — ou dispare **"Cobrar esta base agora"** para rodar
   imediatamente, sem esperar o agendamento.
6. O **worker interno** (APScheduler, dentro do próprio processo do backend) varre periodicamente
   as faixas ativas/marcadas para rodar agora, reserva um lote de clientes pendentes, envia via
   Graph API alternando entre os números configurados, e atualiza o status de cada envio
   (enviado/erro), com log de erro consultável no dashboard.
7. **Dashboard** — pendentes, enviados, erros, telefones inválidos, por faixa, e os erros mais
   recentes — tudo lido direto do Postgres do próprio sistema.

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
- **Migrations**: o schema é criado via `Base.metadata.create_all()` na subida do backend (sem
  Alembic). Para evoluir o schema em produção com dados já existentes, vale introduzir Alembic.
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
