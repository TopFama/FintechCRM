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
- **Depende de:** `cache`, `consultas_fila`, `fila_automatica` (descartar fila), `pausas`, `regras_db`, `seta_client`, `services/efetividade_service`, `services/pagamentos_service`, `utils/xlsx`, `models`, `schemas`, `timezone`; SETA/Redis ocupado vira 429 e fora do ar vira 503 com `codigo` nos handlers do `main.py`. Efetividade e Quem pagou leem o snapshot do cache; ordenar, paginar e exportar não consultam o SETA.
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
- **Responsabilidade:** servir os cards do Dashboard. Na tabela "Por faixa", `consultas_fila.nome_faixa` é a única definição da faixa da linha (a de atraso do cliente, senão a da fila). Clientes cobrados são os clientes distintos com mensagem enviada (`sent`) da faixa com `sent_at` no período, de `consultas_fila.clientes_com_envio_no_periodo`, a mesma base das Cobranças: Frequência = mensagens do período ÷ clientes cobrados, e "Pagaram após cobrança" = desses clientes, quem pagou depois do primeiro envio do período (`pagamentos_service.clientes_que_pagaram(base="envios")`, a mesma lista que o número abre em Quem pagou com `base=envios`). Lead marcado como cobrado à mão, sem envio, não conta. Os totais que não são soma da coluna (clientes e valor pago contados uma vez) vêm em `total_por_faixa`. O custo do WhatsApp de cada faixa (base do ROAS, `_somar_custo_por_faixa`) = custo por envio de cada dia (`custo_whatsapp.custo_por_envio`) × mensagens enviadas pela faixa no dia (`consultas_fila.envios_por_dia`); o ROAS em si é calculado na tela. A ordem das colunas dessa tabela é guardada por usuário (`GET`/`PUT /dashboard/colunas-por-faixa`, coluna `users.colunas_por_faixa`; vazia = ordem padrão da tela).
- **Depende de:** `cache`, `consultas_fila`, `painel_tempo_real` (WebSocket `/dashboard/ws`), `seta_client`, `services/custo_whatsapp`, `services/pagamentos_service`, `services/pagos_janela_service`, `utils/xlsx`, `timezone`. O card de pagamentos (`GET /dashboard/janela-pagamento`, "Pagaram em até N dias") lê a janela de `config_parametros.dias_janela_dashboard` (Configurações → Indicadores; nulo = qualquer data após a cobrança) e reaproveita o snapshot `relatorio-pagamentos` (mesma chave de Quem pagou com a mesma janela); sem Redis o resumo cai para só o que é local (`buscar_novos=False`).
- **Violações encontradas:** nenhuma grave. As de 26/09 (import de `routers.reports`, `_limites_utc` e contagem de pausados no router) foram resolvidas pelo backlog #3: `_resumo` monta o card a partir de `consultas_fila` (`limites_utc`, `contar_pausados`), a mesma fonte dos relatórios.
- **Churn:** 15 | **Linhas:** 350 | **Cobertura:** 24% (medida em 26/09)

### `apps/backend/app/painel_tempo_real.py`
- **Domínio:** Dashboard/Relatórios
- **Camada:** aplicação (com infraestrutura: LISTEN do Postgres e Redis)
- **Responsabilidade:** manter os números dos cards da fila em tempo real.
- **Depende de:** `cache` (cliente Redis e cache de Pausados), `consultas_fila` (`contar_cards`, `dia_do_card`, `contar_pausados`), `database`, `timezone`. As mudanças chegam pelas triggers `painel_*` (migration `a3d5f7b9c1e2`), não por chamadas espalhadas no código.
- **É usado por:** `main` (ouvinte no lifespan), `routers/dashboard` (WebSocket `/dashboard/ws`).
- **Violações encontradas:** nenhuma.

### `apps/backend/app/services/efetividade_service.py`
- **Domínio:** Dashboard/Relatórios
- **Camada:** aplicação
- **Responsabilidade:** montar os dados da efetividade.
- **Depende de:** `cache`, `campanhas_fixas`, `google_client`, `lojas`, `regras_db`, `relatorio_efetividade`, `services/custo_whatsapp`, `services/pagamentos_seta`, `seta_client`. Duas etapas: `snapshot_efetividade` (a consulta pesada ao SETA, sem filtro de loja, guardada no cache) e a derivação (loja, custo do WhatsApp, ordenação, página, Excel), que só lê o snapshot. O custo de cada lead (base do ROAS) é o custo por envio do dia da cobrança (`custo_whatsapp.custo_por_envio`), repartido entre as parcelas pelo mesmo peso do valor pago (`_repartir`); fica fora do snapshot para a Meta fora do ar não estragar o cache do SETA.
- **Violações encontradas:** nenhuma. A de 26/09 (cópias de fuso `_inicio_dia_utc`/`_dia_br`) foi resolvida pelo backlog #10: usa `timezone.dia_br` e `timezone.inicio_do_dia_utc`.
- **Churn:** 10 | **Linhas:** 275

### `apps/backend/app/services/custo_whatsapp.py`
- **Domínio:** Dashboard/Relatórios
- **Camada:** aplicação
- **Responsabilidade:** calcular o custo do WhatsApp em reais. `gasto_diario_brl` guarda o gasto por dia 10 min no Redis (falha não é guardada; sem Redis vai à Meta); `custo_por_envio` divide o gasto de cada dia pelas mensagens enviadas pela fila no dia, a única regra de rateio do ROAS (Dashboard e Efetividade).
- **Violações encontradas:**
  - [x] Acesso a dados de outro domínio: `_tokens_da_waba` decifra tokens da Meta direto das tabelas, repetindo parte de `meta_client.token_da_waba` (a diferença é que aqui tenta todos os tokens ativos).
- **Churn:** 5 | **Linhas:** 186
- **Ação sugerida:** `meta_client.tokens_da_waba(db, waba_id)` devolvendo todos; baixa prioridade.

### `apps/backend/app/relatorio_efetividade.py`
- **Domínio:** Dashboard/Relatórios
- **Camada:** domínio
- **Responsabilidade:** calcular as métricas de efetividade.
- **Violações encontradas:** nenhuma; função pura e testada (`test_relatorio_efetividade.py`).
