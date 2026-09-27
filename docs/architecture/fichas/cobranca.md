# Fichas — Cobrança

Base de clientes em atraso lida do SETA, regras de cobrança (clusters, faixas de atraso, matriz
WhatsApp, juros) e leads. Ordenado do arquivo com mais violações para o com menos. Revisado em
27/09/2026 (depois dos PRs #3 a #10); churn e cobertura são os de 26/09.

### `apps/backend/app/routers/cobranca.py`
- **Domínio:** Cobrança
- **Camada:** interface
- **Responsabilidade:** expor a consulta da base de cobrança com filtros.
- **Motivos para mudar:** filtros da tela, ordenação, exportação, relatório de matriz.
- **Depende de:** `cobranca_relatorio`, `cobranca_regras`, `regras_db`, `seta_client`, `elegibilidade.sem_cobrados_hoje`, `services/compras_seta`, `utils/spc`, `utils/xlsx`, `timezone`, `routers/comum` (`filtros_base`, `buscar_base_ou_erro`, `ordenar_clientes`, `ClienteSortColumn`).
- **É usado por:** `main` (ninguém mais importa este router).
- **Violações encontradas:** as de 26/09 (router servindo de biblioteca de filtros para outros dois routers, "sem cobrados hoje" no router, import de `.xlsx` de `routers/reports`) foram resolvidas pelo backlog #2 (PR #4): filtros e ordenação em `routers/comum.py`, `sem_cobrados_hoje` em `elegibilidade.py`, `.xlsx` em `utils/xlsx.py`.
- **Churn:** 14 | **Linhas:** 169

### `apps/backend/app/routers/leads.py`
- **Domínio:** Cobrança
- **Camada:** interface
- **Responsabilidade:** expor a geração, consulta e exportação de leads.
- **Depende de:** `fila_automatica.enfileirar_leads`, `leads_service`, `google_client`, `lojas`, `regras_db`, `seta_client`, `services/efetividade_service`, `blacklist`, `elegibilidade`, `timezone`, `utils/leads_xlsx`, `routers/comum`.
- **É usado por:** `main`.
- **Violações encontradas:**
  - [x] Regra de negócio no router: `filtrar_leads`/`query_leads_filtrada` (filtro de leads, inclusive blacklist e lojas) e `enfileirar_pendentes_de_hoje`.
  - [x] SQL/ORM no router.
  - Resolvido: imports de `routers.blacklist`/`routers.cobranca` (backlogs #8 e #2) e a cópia de fuso `_inicio_utc` (hoje `timezone.inicio_do_dia_utc`, backlog #10).
- **Churn:** 18 | **Linhas:** 358 | **Cobertura:** 65% (medida em 26/09)
- **Ação sugerida:** filtros de lead para `leads_service.py`.
- **Esforço:** M | **Risco:** baixo

### `apps/backend/app/seta_client.py`
- **Domínio:** Integrações (é o único acesso ao SETA; listado aqui porque todo SQL de cobrança mora nele)
- **Camada:** infraestrutura
- **Responsabilidade:** consultar o SETA em modo só leitura.
- **Motivos para mudar:** regra de parcela em aberto, juros/multa, SPC, baixas, performance da consulta.
- **Depende de:** `cobranca_regras` (tipos), `config`, `timezone`.
- **É usado por:** os routers `campanhas`, `cobranca`, `comum`, `dashboard`, `leads`, `remarketing`, `reports` e `seta`; os módulos `worker`, `campanhas`, `cobranca_base`, `leads_service`, `remarketing` e `upload_service`; e os serviços `compras_seta`, `efetividade_service`, `pagamentos_seta`, `pagamentos_service` e `pagos_janela_service`.
- **Violações encontradas:**
  - [ ] Mais de uma responsabilidade (várias consultas, mas todas "ler o SETA")
  - [x] Duplicação: o filtro de parcela em aberto (`rp='R'`, `status='A'`, tipo 4/5, valor > 0, juros/multa) aparece em `_SQL_BASE_COBRANCA` e `_SQL_PARCELAS_COBRANCA`.
  - [ ] demais: não. Conexão já abre com `default_transaction_read_only=on` e `statement_timeout`; consultas por cliente são em lote.
- **Churn:** 21 | **Linhas:** 766
- **Ação sugerida:** extrair o fragmento SQL de "parcela em aberto" compartilhado. Baixa prioridade e risco alto (produção, tabela de 27M linhas): só com teste de caracterização contra o SETA falso do e2e (backlog #15).
- **Esforço:** M | **Risco:** alto

### `apps/backend/app/cobranca_base.py`
- **Domínio:** Cobrança
- **Camada:** aplicação
- **Responsabilidade:** montar a base de cobrança do dia a partir do SETA.
- **Depende de:** `cache`, `cobranca_regras`, `regras_db`, `seta_client`, `blacklist`, `services/compras_seta`, `utils/phone`.
- **É usado por:** `worker`, `campanhas`, `remarketing`, `routers/campanhas`, `routers/comum`.
- **Violações encontradas:** nenhuma. A de 26/09 (import de `codigos_bloqueados` do router) foi resolvida pelo backlog #8.
- **Churn:** 8 | **Linhas:** 232 | **Cobertura:** 80% (medida em 26/09)

### `apps/backend/app/routers/config_cobranca.py`
- **Domínio:** Cobrança (+ Envios + Dashboard)
- **Camada:** interface
- **Responsabilidade:** hoje são três: regras de cobrança, horário global de disparo e orçamento mensal.
- **Violações encontradas:**
  - [x] Mais de uma responsabilidade: `/disparo` (config do worker) e `/orcamento` (Indicadores) moram no router de regras de cobrança.
  - [x] SQL/ORM no router (19 queries), incluindo validação de faixas/clusters que poderia ser do `cobranca_regras`.
- **Churn:** 6 | **Linhas:** 333
- **Ação sugerida:** separar `routers/config_disparo.py` e `routers/orcamento.py` sem mudar URL (backlog #13).
- **Esforço:** P | **Risco:** baixo

### `apps/backend/app/leads_service.py`
- **Domínio:** Cobrança
- **Camada:** aplicação
- **Responsabilidade:** gravar leads a partir dos clientes da base.
- **Violações encontradas:** nenhuma relevante. Busca SPC e parcelas em lote.
- **Churn:** 2 | **Linhas:** 105 | **Cobertura:** 92%
- **Ação sugerida:** receber os filtros de lead que hoje estão em `routers/leads.py`.

### `apps/backend/app/cobranca_regras.py`, `regras_db.py`, `cobranca_relatorio.py`
- **Domínio:** Cobrança
- **Camada:** domínio (regras puras) / aplicação (`regras_db` carrega do banco)
- **Responsabilidade:** representar as regras de cobrança (cluster, faixa de atraso, matriz, juros).
- **Violações encontradas:** nenhuma. `cobranca_regras` não importa nada do app; é o modelo do que o resto deveria ser.
- **Churn:** 5 / 1 / 3 | **Linhas:** 169 / 55 / 65
- **Ação sugerida:** travar a pureza no import-linter (Fase 7).

## Pagamentos (`services/`)

### `apps/backend/app/services/pagamentos_seta.py`
- **Domínio:** Pagamentos
- **Camada:** aplicação
- **Responsabilidade:** manter a cópia local das baixas do SETA.
- **Violações encontradas:**
  - [x] Acoplamento com Autenticação: `registrar_atividade()` é chamado de dentro de `deps.get_current_user` (toda requisição autenticada marca "alguém usando o CRM"). Funciona, mas autenticação passou a conhecer pagamentos.
- **Churn:** 5 | **Linhas:** 310
- **Ação sugerida:** mover o registro de atividade para um middleware em `main.py` (backlog #16).
- **Esforço:** P | **Risco:** baixo

### `apps/backend/app/services/pagamentos_service.py`, `pagos_janela_service.py`
- **Domínio:** Pagamentos
- **Camada:** aplicação
- **Responsabilidade:** responder "quem pagou" numa janela. `condicao_cobrados` é a definição de "lead cobrado no período", base de "Quem pagou" e das colunas Clientes cobrados/Frequência/% Conv. do Dashboard (`clientes_cobrados_por_faixa`).
- **Depende de:** `consultas_fila` (`limites_utc`/`condicao_periodo`, só os limites do período), `google_client`, `lojas`, `services/pagamentos_seta`, `timezone`.
- **Violações encontradas:** nenhuma. A de 26/09 (cópias de `_inicio_utc`/`_dia_br`, uma importada como "privada" por `routers/campanhas`) foi resolvida pelo backlog #10: usam `timezone`.
- **Churn:** 6 / 1 | **Linhas:** 148 / 50

### `apps/backend/app/services/compras_seta.py`
- **Domínio:** Cobrança (faixa de compra do cliente)
- **Camada:** aplicação
- **Responsabilidade:** manter a cópia local das compras no crediário de cada cliente (tabelas `compras_seta` e `sincronizacoes_seta`), atualizada pelo worker às 03:00 (GMT-3).
- **Depende de:** `seta_client`, `models`, `timezone`.
- **É usado por:** `worker`, `cobranca_base`, `remarketing`, `routers/cobranca`.
- **Violações encontradas:** nenhuma (a cópia própria `_dia_br` foi trocada por `timezone.dia_br` em 27/09).
- **Linhas:** 132
