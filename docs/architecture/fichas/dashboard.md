# Fichas — Dashboard e Relatórios

Camada de leitura: cards, relatórios exportáveis, efetividade, orçamento e custo do WhatsApp. As
features citadas no plano como próximas (cards clicáveis, "Pagaram em até 7 dias", pausa/parada
por cliente, régua e loja) já existem; o objetivo aqui é que as próximas mudanças nessas telas
mexam em menos arquivos.

Revisado em 27/09/2026 (depois dos PRs #3 a #10); churn e cobertura são os de 26/09.

**Leitura × escrita:** o plano pede que consultas de relatório não reaproveitem services de
escrita. Em 26/09 a query da fila que monta Pendentes e Erros (`_fila_report_query`, no router de
relatórios) também era usada para apagar pendentes, e o Dashboard importava helpers do router de
relatórios. Resolvido pelo backlog #3 (PR #8): a leitura da fila mora em `consultas_fila.py`
(`itens_da_fila`, `limites_utc`, `contar_pausados`…), usada pelos dois routers, e o "Descartar
fila" chama `fila_automatica.descartar_pendentes` (Envios).

### `apps/backend/app/routers/reports.py`
- **Domínio:** Dashboard/Relatórios
- **Camada:** interface (com aplicação e formatação dentro)
- **Responsabilidade (1 frase, sem "e"):** servir os relatórios da tela Relatórios.
- **Motivos para mudar:** colunas de relatório, filtros, exportação .xlsx, cores do Excel da efetividade, descartar fila, pagamentos.
- **Depende de:** `cache`, `consultas_fila`, `fila_automatica` (descartar fila), `pausas`, `regras_db`, `seta_client`, `services/efetividade_service`, `services/pagamentos_service`, `utils/xlsx`, `models`, `schemas`, `timezone`.
- **É usado por:** `main`.
- **Violações encontradas:**
  - [x] Mais de uma responsabilidade: seis relatórios (telefones inválidos, envios, pendentes, erros, efetividade, pagamentos) num arquivo só (858 linhas; o maior do backend hoje é `seta_client.py`).
  - [x] SQL/ORM no router: queries de telefones inválidos e envios.
  - [ ] Acesso direto a dados de outro domínio (aceito para camada de leitura)
  - Resolvido: `.xlsx` e `formula_safe` em `utils/xlsx.py` (backlog #2); queries da fila em `consultas_fila.py` e "descartar fila" em `fila_automatica.descartar_pendentes` (backlog #3); fuso em `timezone.hora_br` (backlog #10).
- **Churn:** 28 | **Linhas:** 858 | **Cobertura:** 61% (medida em 26/09)
- **Ação sugerida:** quebrar o router por relatório (backlog #14), sem mudar URLs.
- **Esforço:** M | **Risco:** baixo a médio (e2e 13 cobre todos os relatórios)

### `apps/backend/app/routers/dashboard.py`
- **Domínio:** Dashboard/Relatórios
- **Camada:** interface
- **Responsabilidade:** servir os cards do Dashboard. Na tabela "Por faixa", `_nome_faixa` é a única definição da faixa da linha (a de atraso do cliente, senão a da fila); os totais que não são soma da coluna (clientes e valor pago contados uma vez) vêm em `total_por_faixa`.
- **Depende de:** `cache`, `consultas_fila`, `seta_client`, `services/custo_whatsapp`, `services/pagamentos_service`, `services/pagos_janela_service`, `utils/xlsx`, `timezone`.
- **Violações encontradas:** nenhuma grave. As de 26/09 (import de `routers.reports`, `_limites_utc` e contagem de pausados no router) foram resolvidas pelo backlog #3: `_resumo` monta o card a partir de `consultas_fila` (`limites_utc`, `contar_pausados`), a mesma fonte dos relatórios.
- **Churn:** 15 | **Linhas:** 350 | **Cobertura:** 24% (medida em 26/09)

### `apps/backend/app/services/efetividade_service.py`
- **Domínio:** Dashboard/Relatórios
- **Camada:** aplicação
- **Responsabilidade:** montar os dados da efetividade.
- **Depende de:** `campanhas_fixas`, `google_client`, `lojas`, `regras_db`, `relatorio_efetividade`, `services/custo_whatsapp`, `services/pagamentos_seta`, `seta_client`.
- **Violações encontradas:** nenhuma. A de 26/09 (cópias de fuso `_inicio_dia_utc`/`_dia_br`) foi resolvida pelo backlog #10: usa `timezone.dia_br` e `timezone.inicio_do_dia_utc`.
- **Churn:** 10 | **Linhas:** 275

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
