# Fichas — Cobrança

Base de clientes em atraso lida do SETA, regras de cobrança (clusters, faixas de atraso, matriz
WhatsApp, juros) e leads. Ordenado do arquivo com mais violações para o com menos.

### `apps/backend/app/routers/cobranca.py`
- **Domínio:** Cobrança
- **Camada:** interface
- **Responsabilidade:** expor a consulta da base de cobrança com filtros.
- **Motivos para mudar:** filtros da tela, ordenação, exportação, relatório de matriz.
- **Depende de:** `cobranca_base`, `cobranca_regras`, `cobranca_relatorio`, `fila_automatica.cobrados_hoje`, `google_client`, `lojas`, `seta_client`, `cache`, `routers.reports` (!).
- **É usado por:** `main`; `routers/leads` importa `filtros_base`, `buscar_base_ou_erro`, `sem_cobrados_hoje`; `routers/campanhas` importa `ClienteSortColumn`, `_ordenar_clientes`.
- **Violações encontradas:**
  - [x] Mais de uma responsabilidade: é router e ao mesmo tempo a biblioteca de filtros/ordenação da base usada por outros dois routers.
  - [x] Regra de negócio fora do serviço: "tirar da lista quem já foi cobrado hoje" (`sem_cobrados_hoje`) e a tradução de filtros de loja/cobradora em códigos de loja.
  - [ ] SQL/ORM fora do repository
  - [ ] Acesso direto a dados de outro domínio
  - [ ] Chamada direta a provedor externo sem interface
  - [x] Router importando router: usa `_build_xlsx`, `_formula_safe`, `_XLSX_MEDIA_TYPE` de `routers/reports.py`; e é importado por `routers/leads` e `routers/campanhas`.
  - [ ] Duplicação
- **Churn:** 14 | **Linhas:** 259
- **Ação sugerida:** `filtros_base`, `buscar_base_ou_erro`, `_ordenar_clientes`, `sem_cobrados_hoje` vão para um `cobranca_consulta.py` (serviço); geração de .xlsx vai para `utils/xlsx.py` (backlog #2).
- **Esforço:** P | **Risco:** baixo

### `apps/backend/app/routers/leads.py`
- **Domínio:** Cobrança
- **Camada:** interface
- **Responsabilidade:** expor a geração, consulta e exportação de leads.
- **Depende de:** `fila_automatica`, `leads_service`, `google_client`, `lojas`, `regras_db`, `seta_client`, `services/efetividade_service`, `routers.blacklist` (!), `routers.cobranca` (!).
- **É usado por:** `main`.
- **Violações encontradas:**
  - [x] Regra de negócio no router: `filtrar_leads`/`query_leads_filtrada` (60 linhas de filtro de leads, inclusive blacklist e lojas) e `enfileirar_pendentes_de_hoje`.
  - [x] SQL/ORM no router.
  - [x] Router importando router (`blacklist`, `cobranca`).
  - [x] Duplicação: `_inicio_utc` (fuso) é a 5ª cópia do helper.
- **Churn:** 18 | **Linhas:** 360 | **Cobertura:** 65%
- **Ação sugerida:** filtros de lead para `leads_service.py`; imports de router resolvidos pelos itens #8 e #2 do backlog; fuso pelo #10.
- **Esforço:** M | **Risco:** baixo

### `apps/backend/app/seta_client.py`
- **Domínio:** Integrações (é o único acesso ao SETA; listado aqui porque todo SQL de cobrança mora nele)
- **Camada:** infraestrutura
- **Responsabilidade:** consultar o SETA em modo só leitura.
- **Motivos para mudar:** regra de parcela em aberto, juros/multa, SPC, baixas, performance da consulta.
- **Depende de:** `cobranca_regras` (tipos), `config`, `timezone`.
- **É usado por:** 10 módulos (routers de cobrança, leads, dashboard, reports, campanhas, remarketing, seta; `worker`; serviços de pagamento e efetividade).
- **Violações encontradas:**
  - [ ] Mais de uma responsabilidade (várias consultas, mas todas "ler o SETA")
  - [x] Duplicação: o filtro de parcela em aberto (`rp='R'`, `status='A'`, tipo 4/5, valor > 0, juros/multa) aparece em `_SQL_BASE_COBRANCA` e `_SQL_PARCELAS_COBRANCA`.
  - [ ] demais: não. Conexão já abre com `default_transaction_read_only=on` e `statement_timeout`; consultas por cliente são em lote.
- **Churn:** 21 | **Linhas:** 666
- **Ação sugerida:** extrair o fragmento SQL de "parcela em aberto" compartilhado. Baixa prioridade e risco alto (produção, tabela de 27M linhas): só com teste de caracterização contra o SETA falso do e2e (backlog #15).
- **Esforço:** M | **Risco:** alto

### `apps/backend/app/cobranca_base.py`
- **Domínio:** Cobrança
- **Camada:** aplicação
- **Responsabilidade:** montar a base de cobrança do dia a partir do SETA.
- **Depende de:** `cache`, `cobranca_regras`, `regras_db`, `seta_client`, `utils/phone`, `routers.blacklist` (!).
- **É usado por:** `worker`, `campanhas`, `remarketing`, `routers/cobranca`, `routers/campanhas`.
- **Violações encontradas:**
  - [x] Serviço importando router (`codigos_bloqueados`).
  - [ ] demais: não.
- **Churn:** 8 | **Linhas:** 223 | **Cobertura:** 80%
- **Ação sugerida:** só o import (backlog #8).
- **Esforço:** P | **Risco:** baixo

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
- **Churn:** 5 | **Linhas:** 270
- **Ação sugerida:** mover o registro de atividade para um middleware em `main.py` (backlog #16).
- **Esforço:** P | **Risco:** baixo

### `apps/backend/app/services/pagamentos_service.py`, `pagos_janela_service.py`
- **Domínio:** Pagamentos
- **Camada:** aplicação
- **Responsabilidade:** responder "quem pagou" numa janela.
- **Violações encontradas:**
  - [x] Duplicação: `_inicio_utc` e `_dia_br` (fuso) repetidos; `_inicio_utc` é importado como "privado" por `routers/campanhas`.
- **Churn:** 6 / 1 | **Linhas:** 134 / 50
- **Ação sugerida:** fuso no `timezone.py` (backlog #10).
