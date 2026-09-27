# Fichas — Campanhas

Campanhas (manuais e com envio automático) e o remarketing do Renegocie, que é tratado como
campanha fixa (`campanhas_fixas.py`). Ordenado do arquivo com mais violações para o com menos.

### `apps/backend/app/routers/campanhas.py`
- **Domínio:** Campanhas
- **Camada:** interface
- **Responsabilidade:** expor o cadastro e a operação das campanhas.
- **Motivos para mudar:** filtros da campanha, lista, pausa/parada, planilha de clientes, prévia.
- **Depende de:** `campanhas`, `campanhas_fixas`, `cobranca_base`, `google_client`, `pausas`, `regras_db`, `seta_client`, `cache`, `services.pagamentos_service._inicio_utc` (privado), `routers.cobranca` (!), `routers.uploads` (!).
- **É usado por:** `main`.
- **Violações encontradas:**
  - [x] Mais de uma responsabilidade: validação da campanha, contagens da fila, filtro "enviadas no período" e pausa estão no router.
  - [x] Regra de negócio no router: `pausar`/`retomar`/`parar` criam e encerram `PausaEnvio` direto, repetindo o que `routers/pausas.py` faz (inclusive a checagem "já existe pausa ativa").
  - [x] SQL/ORM no router: `_contagens`, `_enviadas_no_periodo`, `_pausas_por_faixa`.
  - [x] Acesso a dados de outro domínio: lê `Lead` e `QueueItem` direto.
  - [ ] Chamada direta a provedor externo sem interface
  - [x] Router importando router e função privada de serviço.
  - [x] Duplicação: pausa/retomada (com `routers/pausas.py`).
- **Churn:** 8 | **Linhas:** 505 | **Cobertura:** 30%
- **Ação sugerida:** `pausas.pausar(db, escopo, valor, ...)` e `pausas.retomar(...)` como serviço único, usado pelas duas rotas (parte do backlog #4); imports de router pelo backlog #2.
- **Esforço:** M | **Risco:** médio

### `apps/backend/app/remarketing.py`
- **Domínio:** Campanhas
- **Camada:** aplicação + infraestrutura
- **Responsabilidade:** selecionar e enfileirar os clientes do remarketing do Renegocie.
- **Depende de:** `campanhas_fixas`, `cobranca_base`, `cobranca_regras`, `crypto`, `fila_automatica`, `leads_service`, `lojas`, `regras_db`, `seta_client`, `routers.blacklist` (!).
- **É usado por:** `worker`, `routers/remarketing`.
- **Violações encontradas:**
  - [x] Mais de uma responsabilidade: é o cliente HTTP do Renegocie e a regra de seleção.
  - [ ] Regra de negócio fora do domínio
  - [ ] SQL/ORM fora do repository (aceito)
  - [ ] Acesso direto a dados de outro domínio
  - [x] Chamada direta a provedor externo sem interface: `buscar_no_renegocie` usa `httpx` direto, e `routers/remarketing.testar_conexao` faz outra chamada `httpx` por conta própria.
  - [ ] Dependência circular
  - [x] Serviço importando router (`codigos_bloqueados`).
- **Churn:** 11 | **Linhas:** 314 | **Cobertura:** 20%
- **Ação sugerida:** `renegocie_client.py` com `buscar_remarketing(dias)` e `testar()`, no padrão dos outros clientes (backlog #12).
- **Esforço:** P | **Risco:** baixo

### `apps/backend/app/campanhas.py`
- **Domínio:** Campanhas
- **Camada:** aplicação
- **Responsabilidade:** executar uma campanha no dia.
- **Motivos para mudar:** filtros, período, fonte de valores (SETA ou planilha), régua pós-campanha, leitura da planilha.
- **Depende de:** `cobranca_base`, `fila_automatica`, `leads_service`, `lojas`, `pausas`, `regras_db`, `seta_client`, `timezone`, `utils/phone`.
- **É usado por:** `worker`, `routers/campanhas`, `routers/lojas` (leitura de planilha).
- **Violações encontradas:**
  - [x] Mais de uma responsabilidade: execução da campanha, "levar à régua quem recebeu campanha" e leitura de planilhas .xlsx (`_linhas_xlsx`, `colunas_planilha`, `ler_lojas`, `ler_clientes`), que `routers/lojas` também usa.
  - [x] Duplicação: `campanhas_para_hoje` relê as pausas de faixa por conta própria.
- **Churn:** 9 | **Linhas:** 450 | **Cobertura:** 18%
- **Ação sugerida:** leitura de planilha para `utils/spreadsheet.py`; `enfileirar_na_regua` pode virar `regua_pos_campanha.py`. Baixa prioridade.
- **Esforço:** M | **Risco:** médio (18% de cobertura: precisa de caracterização antes)

### `apps/backend/app/routers/remarketing.py`
- **Domínio:** Campanhas
- **Camada:** interface
- **Violações encontradas:** chamada `httpx` inline em `testar_conexao` (ver acima).
- **Churn:** 6 | **Linhas:** 199
- **Ação sugerida:** usar `renegocie_client` (backlog #12).

### `apps/backend/app/campanhas_fixas.py`
- **Domínio:** Campanhas
- **Camada:** domínio
- **Responsabilidade:** identificar os segmentos do remarketing como campanhas fixas.
- **Violações encontradas:** nenhuma.
- **Churn:** 1 | **Linhas:** 39
