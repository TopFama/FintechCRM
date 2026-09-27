# Fichas — Réguas

Faixas de envio (régua, campanha e remarketing são todas `Faixa`, separadas pelo campo `tipo`),
pares número + template (`FaixaEnvio`), agenda por envio (`DispatchConfig`) e mapeamento de
variáveis (`FaixaVariableMapping`).

**Réguas × Envios:** a separação pedida no plano ("a régua só decide quando e o que enviar; o
disparo fica em Envios") já existe no nível de arquivo: `routers/faixas.py` só configura, e o
disparo está em `worker.py` + `dispatch_service.py`. O que se mistura é a **resolução de
variáveis** (o "o que enviar"), que hoje é feita em quatro lugares de Envios (ver
`fichas/envios.md`) em vez de numa função da régua.

### `apps/backend/app/routers/faixas.py`
- **Domínio:** Réguas
- **Camada:** interface
- **Responsabilidade:** configurar faixas e seus envios.
- **Motivos para mudar:** telas de faixa, validação de mapeamento, sincronização com as faixas de atraso.
- **Depende de:** `models`, `schemas`, `regras_db`, `utils/spreadsheet`.
- **É usado por:** `main`.
- **Violações encontradas:**
  - [ ] Mais de uma responsabilidade
  - [x] Regra de negócio no router: validação e gravação de mapeamento de variáveis (`_validar_mapeamento_variaveis`, `_salvar_mapeamento`), "sincronizar faixas de atraso" (cria faixa de régua para cada faixa de atraso).
  - [x] SQL/ORM no router (23 queries, o maior número entre os routers).
  - [ ] demais: não.
- **Churn:** 9 | **Linhas:** 406
- **Ação sugerida:** criar `reguas.py` com o mapeamento de variáveis e a resolução de variáveis de um cliente para os templates ativos da faixa (usado pelo backlog #1). O resto pode ficar.
- **Esforço:** M | **Risco:** médio

### `apps/backend/app/variaveis_template.py`
- **Domínio:** Templates
- **Camada:** domínio
- **Responsabilidade:** resolver o valor de uma variável de template a partir do contexto do cliente.
- **Depende de:** `cobranca_regras`, `timezone`, `utils/leads_xlsx`.
- **Violações encontradas:** nenhuma relevante; é função pura e bem testada (`test_variaveis_template.py`).
- **Churn:** 7 | **Linhas:** 310
- **Ação sugerida:** nenhuma.
