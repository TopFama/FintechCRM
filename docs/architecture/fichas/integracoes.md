# Fichas — Integrações e Templates

Clientes de sistemas externos e as telas que cadastram tokens, números e conexões. A regra
"integração só pelo cliente dela" já é seguida para Meta, Chatwoot, Google, SETA e câmbio; a
exceção é o Renegocie (ver `fichas/campanhas.md`).

### `apps/backend/app/routers/templates.py`
- **Domínio:** Templates
- **Camada:** interface
- **Responsabilidade:** expor o cadastro de templates.
- **Motivos para mudar:** formato de template da Meta, sincronização, imagem de cabeçalho, teste de envio.
- **Depende de:** `meta_client`, `chatwoot_client`, `dispatch_service`, `variaveis_template`, `utils/phone`, `utils/imagem`, `config`.
- **Violações encontradas:**
  - [x] Mais de uma responsabilidade: `sync_from_meta` (80 linhas) faz o upsert dos templates vindos da Meta e interpreta o JSON da Meta (`_map_meta_status`, `_extract_body_text`, `_extract_variable_count`, `_extract_header_type`) dentro do router; upload de imagem grava arquivo em disco e cuida da etapa de validação da imagem otimizada (pendente/confirmar/descartar); a otimização em si fica em `utils/imagem.py`.
  - [x] Regra de negócio no router: qual token usar por WABA e o upsert.
  - [x] SQL/ORM no router (11 queries).
  - [ ] Chamada direta a provedor sem interface (passa por `MetaClient`)
- **Churn:** 17 | **Linhas:** 567
- **Ação sugerida:** `templates_service.py` com `sincronizar_da_meta(db)` e os tradutores do JSON da Meta (backlog #6).
- **Esforço:** M | **Risco:** baixo (e2e 03 cobre)

### `apps/backend/app/routers/meta_tokens.py`
- **Domínio:** Integrações
- **Camada:** interface
- **Responsabilidade:** expor o cadastro de tokens da Meta.
- **Violações encontradas:**
  - [x] Tratamento de `httpx.HTTPError` no router (a chamada em si é pelo `MetaClient`, mas o erro de transporte vaza).
  - [x] SQL/ORM no router (importação de números da WABA).
- **Churn:** 6 | **Linhas:** 282
- **Ação sugerida:** `MetaClient` converter erro de transporte em `MetaAPIError`. Baixa prioridade.

### `apps/backend/app/meta_client.py`
- **Domínio:** Integrações
- **Camada:** infraestrutura
- **Responsabilidade:** falar com a Graph API da Meta.
- **Violações encontradas:**
  - [x] Mais de uma responsabilidade (leve): além do cliente HTTP, escolhe o token no banco (`token_da_waba`, `token_do_numero`).
- **Churn:** 10 | **Linhas:** 212
- **Ação sugerida:** manter. Se `custo_whatsapp` passar a usar `tokens_da_waba` daqui, a regra de escolha fica num lugar só.

### `apps/backend/app/chatwoot_client.py`, `google_client.py`, `cambio.py`, `crypto.py`, `segredos.py`
- **Domínio:** Integrações
- **Camada:** infraestrutura
- **Responsabilidade:** um cliente por sistema externo (e a cifra dos segredos).
- **Violações encontradas:** nenhuma relevante.
- **Churn:** 6 / 1 / 3 / 2 / 3 | **Linhas:** 165 / 177 / 81 / 54 / 75

### `apps/backend/app/routers/numbers.py`, `chatwoot.py`, `google.py`, `seta.py`
- **Domínio:** Integrações
- **Camada:** interface
- **Violações encontradas:** nenhuma relevante (CRUD simples).
