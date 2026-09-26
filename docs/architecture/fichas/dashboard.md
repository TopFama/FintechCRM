# Fichas — Dashboard e Relatórios

Camada de leitura: cards, relatórios exportáveis, efetividade, orçamento e custo do WhatsApp. As
features citadas no plano como próximas (cards clicáveis, "Pagaram em até 7 dias", pausa/parada
por cliente, régua e loja) já existem; o objetivo aqui é que as próximas mudanças nessas telas
mexam em menos arquivos.

**Leitura × escrita:** o plano pede que consultas de relatório não reaproveitem services de
escrita. Hoje não reaproveitam, mas o contrário acontece: a query da fila que monta Pendentes e
Erros (`_fila_report_query`, em `routers/reports.py`) também é usada para **apagar** pendentes
("Descartar fila"), e o Dashboard importa helpers do router de relatórios.

### `apps/backend/app/routers/reports.py`
- **Domínio:** Dashboard/Relatórios
- **Camada:** interface (com aplicação e formatação dentro)
- **Responsabilidade (1 frase, sem "e"):** servir os relatórios da tela Relatórios.
- **Motivos para mudar:** colunas de relatório, filtros, exportação .xlsx, cores do Excel da efetividade, descartar fila, pagamentos.
- **Depende de:** `cache`, `campanhas_fixas`, `pausas`, `regras_db`, `seta_client`, `services/efetividade_service`, `services/pagamentos_service`, `models`, `schemas`, `timezone`.
- **É usado por:** `main`; `routers/dashboard` e `routers/cobranca` importam `_build_xlsx`, `_XLSX_MEDIA_TYPE`, `_formula_safe`.
- **Violações encontradas:**
  - [x] Mais de uma responsabilidade: seis relatórios (telefones inválidos, envios, pendentes, erros, efetividade, pagamentos), o gerador de .xlsx, o saneador de fórmula (CWE-1236) e uma operação de escrita (descartar pendentes). 1080 linhas, o maior arquivo do backend.
  - [x] Regra de negócio no router: escrita "descartar fila" (`descartar_pendentes`) mora num router de leitura.
  - [x] SQL/ORM no router: queries de fila, telefones inválidos e envios.
  - [ ] Acesso direto a dados de outro domínio (aceito para camada de leitura)
  - [ ] Chamada direta a provedor externo sem interface
  - [ ] Dependência circular
  - [x] Duplicação: `_inicio_utc`, `_hora_br` (fuso); montagem de filtro por período também existe em `routers/dashboard.py`.
  - [x] Utilitário usado por outros routers morando aqui (`_build_xlsx`, `_formula_safe`).
- **Churn:** 28 | **Linhas:** 1080 | **Cobertura:** 61%
- **Ação sugerida:** (a) `.xlsx` para `utils/xlsx.py` (backlog #2); (b) queries da fila para `consultas_fila.py` e "descartar fila" para o serviço de Envios (backlog #3); (c) quebrar o router por relatório (backlog #14), sem mudar URLs.
- **Esforço:** M | **Risco:** baixo a médio (e2e 13 cobre todos os relatórios)

### `apps/backend/app/routers/dashboard.py`
- **Domínio:** Dashboard/Relatórios
- **Camada:** interface
- **Responsabilidade:** servir os cards do Dashboard.
- **Depende de:** `cache`, `pausas`, `seta_client`, `services/custo_whatsapp`, `services/pagamentos_service`, `services/pagos_janela_service`, `routers.reports` (!).
- **Violações encontradas:**
  - [x] SQL/ORM no router: o resumo (`_resumo`) é uma consulta de 70 linhas dentro do router; a contagem "pausados" usa `pausas.Retencao` direto.
  - [x] Router importando router.
  - [x] Duplicação: `_limites_utc` (fuso) e a regra "reservado conta como pendente" também aparece nos relatórios.
- **Churn:** 15 | **Linhas:** 307 | **Cobertura:** 24%
- **Ação sugerida:** o resumo passa a vir de `consultas_fila.py` (mesma fonte dos relatórios, o que garante "o total do relatório bate com o card") — backlog #3.
- **Esforço:** P | **Risco:** baixo

### `apps/backend/app/services/efetividade_service.py`
- **Domínio:** Dashboard/Relatórios
- **Camada:** aplicação
- **Responsabilidade:** montar os dados da efetividade.
- **Depende de:** `campanhas_fixas`, `google_client`, `lojas`, `regras_db`, `relatorio_efetividade`, `services/custo_whatsapp`, `services/pagamentos_seta`, `seta_client`.
- **Violações encontradas:**
  - [x] Duplicação: `_inicio_dia_utc`, `_dia_br` (fuso).
- **Churn:** 10 | **Linhas:** 283
- **Ação sugerida:** só o fuso (backlog #10).

### `apps/backend/app/services/custo_whatsapp.py`
- **Domínio:** Dashboard/Relatórios
- **Camada:** aplicação
- **Responsabilidade:** calcular o custo do WhatsApp em reais.
- **Violações encontradas:**
  - [x] Acesso a dados de outro domínio: `_tokens_da_waba` decifra tokens da Meta direto das tabelas, repetindo parte de `meta_client.token_da_waba` (a diferença é que aqui tenta todos os tokens ativos).
- **Churn:** 5 | **Linhas:** 186
- **Ação sugerida:** `meta_client.tokens_da_waba(db, waba_id)` devolvendo todos; baixa prioridade.

### `apps/backend/app/relatorio_efetividade.py`
- **Domínio:** Dashboard/Relatórios
- **Camada:** domínio
- **Responsabilidade:** calcular as métricas de efetividade.
- **Violações encontradas:** nenhuma; função pura e testada (`test_relatorio_efetividade.py`).
