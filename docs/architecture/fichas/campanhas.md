# Fichas — Campanhas

Campanhas (manuais e com envio automático) e o remarketing do Renegocie, que é tratado como
campanha fixa (`campanhas_fixas.py`). Ordenado do arquivo com mais violações para o com menos.
Revisado em 27/09/2026 (depois dos PRs #3 a #10); churn e cobertura são os de 26/09.

### `apps/backend/app/routers/campanhas.py`
- **Domínio:** Campanhas
- **Camada:** interface
- **Responsabilidade:** expor o cadastro e a operação das campanhas.
- **Motivos para mudar:** filtros da campanha, lista, pausa/parada, planilha de clientes, prévia.
- **Depende de:** `campanhas`, `campanhas_fixas`, `cobranca_base`, `cobranca_regras`, `google_client`, `pausas`, `regras_db`, `seta_client`, `cache`, `timezone`, `routers/comum` (permitido: não é router).
- **É usado por:** `main`.
- **Violações encontradas:**
  - [x] Mais de uma responsabilidade: validação da campanha, contagens da fila, filtro "enviadas no período" e pausa estão no router.
  - [x] SQL/ORM no router: `_contagens`, `_enviadas_no_periodo`, `_pausas_por_faixa`.
  - [x] Acesso a dados de outro domínio: lê `Lead` e `QueueItem` direto.
  - [ ] Chamada direta a provedor externo sem interface
  - [x] Schemas definidos no próprio router.
  - Resolvido: pausar/retomar/parar usam `pausas.pausar`, `pausas.retomar_escopo` e `pausas.parar` (backlog #4); os imports de `routers.cobranca`, `routers.uploads` e de `pagamentos_service._inicio_utc` saíram (backlogs #2 e #10).
- **Churn:** 8 | **Linhas:** 489 | **Cobertura:** 30%
- **Ação sugerida:** as contagens da campanha podem ir para a camada de leitura da fila (`consultas_fila.py`).
- **Esforço:** M | **Risco:** médio

### `apps/backend/app/remarketing.py`
- **Domínio:** Campanhas
- **Camada:** aplicação + infraestrutura
- **Responsabilidade:** selecionar e enfileirar os clientes do remarketing do Renegocie.
- **Depende de:** `campanhas_fixas`, `cobranca_base`, `cobranca_regras`, `crypto`, `blacklist`, `elegibilidade`, `fila_automatica`, `leads_service`, `lojas`, `regras_db`, `seta_client`, `services/compras_seta`, `timezone`, `utils/phone`.
- **É usado por:** `worker`, `routers/remarketing`.
- **Violações encontradas:**
  - [x] Mais de uma responsabilidade: é o cliente HTTP do Renegocie e a regra de seleção.
  - [ ] Regra de negócio fora do domínio
  - [ ] SQL/ORM fora do repository (aceito)
  - [ ] Acesso direto a dados de outro domínio
  - [x] Chamada direta a provedor externo sem interface: `buscar_no_renegocie` usa `httpx` direto, e `routers/remarketing.testar_conexao` usa `buscar_no_renegocie` mas captura `httpx.HTTPError` direto (o erro de transporte vaza do cliente).
  - [ ] Dependência circular
  - Resolvido: importava `codigos_bloqueados` de `routers.blacklist`; hoje vem de `app/blacklist.py` (backlog #8).
- **Churn:** 11 | **Linhas:** 321 | **Cobertura:** 20%
- **Ação sugerida:** `renegocie_client.py` com `buscar_remarketing(dias)` e `testar()`, no padrão dos outros clientes (backlog #12).
- **Esforço:** P | **Risco:** baixo

### `apps/backend/app/campanhas.py`
- **Domínio:** Campanhas
- **Camada:** aplicação
- **Responsabilidade:** executar uma campanha no dia.
- **Motivos para mudar:** filtros, período, fonte de valores (SETA ou planilha), régua pós-campanha, leitura da planilha.
- **Regras próprias:** `selecionar` só traz quem está em atraso (`dias_atraso >= 1`) ou numa faixa só de campanhas (Antecipado), pedida com `incluir_so_campanhas=True`; `erro_faixa_so_campanhas` (usado por `routers/campanhas` e por `routers/faixas._salvar_mapeamento`) deixa a faixa só de campanhas sozinha, sem filtro de valor em atraso e sem os campos de `CAMPOS_SO_EM_ATRASO`. Teste: `tests/test_faixa_antecipado.py`. Com `todos_da_planilha` (e planilha), a base pede ao SETA todos os dias (`cobranca_base.TODOS_OS_DIAS`) e `faixa_na_campanha` põe cada cliente na faixa de atraso, numa faixa só com o dia quando nenhuma o cobre ou, sem atraso, na faixa só de campanhas; `erro_todos_da_planilha` barra filtro de faixa/valor em atraso e a variável "Valor em atraso". Com `incluir_cobrados_hoje`, `_bloqueados` ignora a cobrança de hoje na entrada (só trava a fila) e `elegibilidade.fora_da_regra_do_dia` libera a saída. Teste: `tests/test_campanha_todos_da_planilha.py`.
- **Depende de:** `cobranca_base`, `elegibilidade`, `fila_automatica`, `leads_service`, `lojas`, `pausas`, `regras_db`, `seta_client`, `timezone`, `utils/phone`, `utils/valor`, `variaveis_template`.
- **É usado por:** `worker`, `routers/campanhas`, `routers/lojas` (leitura de planilha).
- **Violações encontradas:**
  - [x] Mais de uma responsabilidade: execução da campanha, "levar à régua quem recebeu campanha" e leitura de planilhas .xlsx (`_linhas_xlsx`, `colunas_planilha`, `ler_lojas`, `ler_clientes`), que `routers/lojas` também usa.
  - [x] Duplicação: `campanhas_para_hoje` relê as pausas de faixa por conta própria.
- **Churn:** 9 | **Linhas:** 447 | **Cobertura:** 18%
- **Ação sugerida:** leitura de planilha para `utils/spreadsheet.py`; `enfileirar_na_regua` pode virar `regua_pos_campanha.py`. Baixa prioridade.
- **Esforço:** M | **Risco:** médio (18% de cobertura: precisa de caracterização antes)

### `apps/backend/app/routers/remarketing.py`
- **Domínio:** Campanhas
- **Camada:** interface
- **Violações encontradas:** `testar_conexao` captura `httpx.HTTPError` direto (ver acima; exceção no `.importlinter`).
- **Churn:** 6 | **Linhas:** 201
- **Ação sugerida:** usar `renegocie_client` (backlog #12).

### `apps/backend/app/campanhas_fixas.py`
- **Domínio:** Campanhas
- **Camada:** domínio
- **Responsabilidade:** identificar os segmentos do remarketing como campanhas fixas.
- **Violações encontradas:** nenhuma.
- **Churn:** 1 | **Linhas:** 39
