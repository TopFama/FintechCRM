# Fichas — Envios

Fila (`queue_items`), disparo, pausa/parada, blacklist e upload de planilha na faixa. É o domínio
que carrega a regra fixa de **uma comunicação por cliente por dia**, então é o primeiro alvo.
Ordenado do arquivo com mais violações para o com menos. Churn = commits no histórico inteiro
(desde 18/09/2026).

## Achado central: "pode entrar?" e "pode sair?" estão espalhados

A decisão de um cliente entrar na fila e a de uma mensagem sair hoje são feitas em vários lugares,
cada um com a sua cópia:

| Checagem | Onde acontece hoje |
|---|---|
| Pendente/reservado ou cobrado hoje (entrada) | `fila_automatica.clientes_bloqueados_hoje`, chamada por `enfileirar_leads`, `campanhas.executar`, `remarketing.enfileirar`, `routers/uploads.upload_planilha` |
| Cobrado hoje (lista da tela) | `fila_automatica.cobrados_hoje` via `routers/cobranca.sem_cobrados_hoje` |
| Blacklist (entrada) | `cobranca_base.buscar_base` (na consulta ao SETA), `remarketing.selecionar`, `routers/uploads` (classe `Blacklist`), `routers/leads` |
| Pausa (saída) | `worker.run_dispatch_cycle`: `retencao.faixas`, `~retencao.condicao()` na busca e `Retencao.carregar(db).retido(item)` antes de cada envio; `campanhas.campanhas_para_hoje` lê pausas de faixa de novo |
| Blacklist (saída) | `worker.run_dispatch_cycle` com `Blacklist(db).contem` |
| Cobrado hoje (saída) | `worker.run_dispatch_cycle` com `ja_cobrado_hoje` |
| Janela/horário | `worker._within_schedule_window`, `_due`, `_na_janela_diaria` |

Hoje funciona (conferido em 25/09 e no code review de 26/09), mas qualquer caminho novo de envio
precisa lembrar de chamar cada checagem, e as três checagens de saída estão escritas dentro do
laço do worker. É o item #4 do backlog: um módulo `elegibilidade` com `pode_entrar(...)` e
`motivo_para_nao_sair(item)`, chamado por todos os caminhos.

---

### `apps/backend/app/routers/uploads.py`
- **Domínio:** Envios
- **Camada:** interface (com aplicação dentro)
- **Responsabilidade (1 frase, sem "e"):** receber a planilha de clientes de uma faixa.
- **Motivos para mudar:** formato da planilha, regra de variável, regra de bloqueio do dia, criação de Lead, telefone inválido.
- **Depende de:** `fila_automatica` (`Blacklist`, `clientes_bloqueados_hoje`), `variaveis_template`, `regras_db`, `pausas`, `utils/*`, `models`.
- **É usado por:** `main`; `routers/campanhas` e `routers/lojas` importam `_ler_planilha_limitada` daqui.
- **Violações encontradas:**
  - [x] Mais de uma responsabilidade: `upload_planilha` tem ~350 linhas (linhas 96–443) que leem a planilha, validam mapeamento, normalizam cliente, resolvem variável, aplicam bloqueio do dia e blacklist, criam `QueueItem`, `Lead` e `InvalidPhoneRecord`.
  - [x] Regra de negócio fora do serviço: resolução de variáveis e montagem do `variables_json` (achatado ou por template) repetem o que `fila_automatica.enfileirar_clientes` faz.
  - [x] SQL/ORM fora do repository: queries de `Lead`, `Faixa` e inserts direto no router.
  - [ ] Acesso direto a dados de outro domínio
  - [ ] Chamada direta a provedor externo sem interface
  - [ ] Dependência circular
  - [x] Duplicação de regra existente em outro arquivo: montagem do item da fila (4 cópias: aqui, `enfileirar_clientes`, `enfileirar_leads`, `reaplicar_variaveis`).
  - [x] Utilitário de outros routers morando aqui (`_ler_planilha_limitada`).
- **Achado de comportamento (não é refatoração):** o `QueueItem` criado pelo upload não preenche `lojas` (a extração automática, campanhas e remarketing preenchem). Consequência provável: "Pausar loja" não retém item vindo de planilha subida na faixa, e o filtro de loja dos relatórios não o encontra. Fica como pergunta ao usuário, fora dos PRs de refatoração.
- **Churn:** 28 commits | **Linhas:** 464
- **Ação sugerida:** Extract Module: `upload_planilha` passa a só ler a requisição e chamar um serviço `fila_automatica.enfileirar_planilha(...)`; a montagem do item vai para a função única do backlog #1. `_ler_planilha_limitada` vai para `utils/spreadsheet.py`.
- **Esforço:** M | **Risco:** médio (caminho de envio; coberto por `test_valor_e_exportacao.py` e e2e 10)

### `apps/backend/app/worker.py`
- **Domínio:** Envios
- **Camada:** interface (agendamento) com aplicação dentro
- **Responsabilidade (1 frase, sem "e"):** decidir quando cada rotina roda.
- **Motivos para mudar:** horário/janela, rotinas do dia (extração, remarketing, campanhas, régua pós-campanha, expiração), regras de saída do item, espera após falha, sincronização de pagamentos.
- **Depende de:** `campanhas`, `remarketing`, `cobranca_base`, `leads_service`, `fila_automatica`, `pausas`, `dispatch_service`, `seta_client`, `services/pagamentos_seta` (13 módulos internos).
- **É usado por:** `main`.
- **Violações encontradas:**
  - [x] Mais de uma responsabilidade: agenda, orquestra as rotinas do dia e decide se cada item pode sair.
  - [x] Regra de negócio fora do serviço: pausa, blacklist e "já cobrado hoje" são checados dentro do laço de `run_dispatch_cycle`.
  - [x] SQL/ORM fora do repository: busca de `DispatchConfig` e de pendentes inline.
  - [ ] Acesso direto a dados de outro domínio
  - [ ] Chamada direta a provedor externo sem interface
  - [x] Dependência circular (contornada): `import` local de `campanhas`, `remarketing` e `cobranca_base` "para evitar ciclo".
  - [x] Duplicação de regra: janela de dia de disparo calculada em 4 funções parecidas (`_within_schedule_window`, `_deve_extrair_leads`, `_na_janela_diaria`, e `fila_automatica.ultimo_fim_de_janela`).
- **Churn:** 22 | **Linhas:** 383
- **Ação sugerida:** (1) checagens de saída viram `elegibilidade.motivo_para_nao_sair(db, item)` (backlog #4); (2) `_rotinas_do_dia` vai para `rotinas_diarias.py`, deixando no worker só o agendamento (backlog #11); (3) cálculo de janela vai para um `janela_disparo.py` puro.
- **Esforço:** M | **Risco:** alto (é o disparo; `test_worker_schedule.py` cobre só a janela)

### `apps/backend/app/fila_automatica.py`
- **Domínio:** Envios
- **Camada:** aplicação
- **Responsabilidade (1 frase, sem "e"):** colocar clientes na fila da faixa certa.
- **Motivos para mudar:** regra de bloqueio do dia, blacklist, resolução de variáveis, formato do item, expiração no fim da janela, reaplicar variáveis.
- **Depende de:** `models`, `pausas`, `regras_db`, `routers.blacklist` (!), `variaveis_template`, `utils/*`, `timezone`.
- **É usado por:** `worker`, `campanhas`, `remarketing`, `routers/uploads`, `routers/leads`, `routers/cobranca`, `routers/pausas`.
- **Violações encontradas:**
  - [x] Mais de uma responsabilidade: bloqueio do dia, blacklist, montagem de item, expiração da fila e reaplicar variáveis.
  - [ ] Regra de negócio fora do domínio
  - [ ] SQL/ORM fora do repository (aceito: é o serviço do domínio)
  - [x] Serviço importando router: `from .routers.blacklist import codigos_bloqueados`.
  - [ ] Chamada direta a provedor externo sem interface
  - [ ] Dependência circular
  - [x] Duplicação: `enfileirar_clientes` e `enfileirar_leads` repetem o laço de resolver variáveis e criar item; `reaplicar_variaveis` tem uma terceira versão; `_utc_ingenuo`/`inicio_hoje_utc` repetem helpers de fuso de outros 6 arquivos.
- **Churn:** 13 | **Linhas:** 428 | **Cobertura:** 37%
- **Ação sugerida:** dividir em `elegibilidade.py` (bloqueio do dia, blacklist, pausa: backlog #4), `fila_automatica.py` (montagem única do item: backlog #1) e manter a expiração aqui. `codigos_bloqueados` vem de `blacklist.py` (backlog #8).
- **Esforço:** M | **Risco:** alto (regra de 1 mensagem por dia)

### `apps/backend/app/dispatch_service.py`
- **Domínio:** Envios
- **Camada:** aplicação + infraestrutura (mídia)
- **Responsabilidade (1 frase, sem "e"):** enviar um item da fila pelo canal do número.
- **Motivos para mudar:** API da Meta, API do Chatwoot, imagem de cabeçalho, regra de "falha incerta ocupa o cliente", marcar lead como cobrado.
- **Depende de:** `meta_client`, `chatwoot_client`, `campanhas_fixas`, `config`, `models`.
- **É usado por:** `worker`, `routers/templates` (teste de envio).
- **Violações encontradas:**
  - [x] Mais de uma responsabilidade: envio pelos dois canais, cache de mídia da Meta e atualização do `Lead`.
  - [ ] Regra de negócio fora do domínio
  - [ ] SQL/ORM fora do repository
  - [x] Acesso direto a dados de outro domínio: `_marcar_lead_cobrado` atualiza `Lead` (Cobrança/Campanhas) direto.
  - [x] Chamada direta a provedor sem interface: `_enviar_via_meta` e `_enviar_via_chatwoot` repetem o mesmo tratamento de erro (erro conhecido libera o cliente, falha inesperada grava `sent_at`) em vez de dois adaptadores de um `MessageSender`.
  - [ ] Dependência circular
  - [x] Duplicação: bloco de tratamento de erro repetido nos dois canais.
- **Churn:** 8 | **Linhas:** 288 | **Cobertura:** 80%
- **Ação sugerida:** Ports & Adapters: `MessageSender` com `MetaSender` e `ChatwootSender`; o tratamento de resultado (enviado, erro, incerto) fica num lugar só (backlog #7).
- **Esforço:** M | **Risco:** médio

### `apps/backend/app/routers/pausas.py`
- **Domínio:** Envios
- **Camada:** interface
- **Responsabilidade:** expor pausar, retomar e parar por cliente, faixa e loja.
- **Motivos para mudar:** telas de pausa, novos escopos.
- **Depende de:** `pausas`, `fila_automatica.reaplicar_variaveis`, `regras_db`, `models`.
- **É usado por:** `main`.
- **Violações encontradas:**
  - [x] SQL/ORM no router: `opcoes_fila` e `_valor_legivel` consultam fila, faixa e lojas direto.
  - [ ] demais: não.
- **Autorização:** todas as rotas usam `get_current_user` (qualquer usuário logado pausa/para), igual ao resto do app; a regra está num lugar só (`deps.py`), não duplicada.
- **Churn:** 2 | **Linhas:** 200 | **Cobertura:** 27%
- **Ação sugerida:** nenhuma urgente; as consultas de opções podem ir para a camada de leitura da fila (backlog #3).
- **Esforço:** P | **Risco:** baixo

### `apps/backend/app/routers/blacklist.py`
- **Domínio:** Envios
- **Camada:** interface
- **Responsabilidade:** expor o cadastro da blacklist.
- **Violações encontradas:**
  - [x] Regra de negócio no router consumida por serviços: `codigos_bloqueados` é importada por `fila_automatica`, `cobranca_base`, `remarketing` e `routers/leads`. Serviço depender de router inverte a camada e é o motivo de alguns imports locais "para evitar ciclo".
- **Churn:** 2 | **Linhas:** 97
- **Ação sugerida:** mover `codigos_bloqueados` e a classe `Blacklist` para `app/blacklist.py` (backlog #8).
- **Esforço:** P | **Risco:** baixo

### `apps/backend/app/pausas.py`
- **Domínio:** Envios
- **Camada:** domínio + aplicação
- **Responsabilidade:** dizer quais itens estão retidos por pausa ativa.
- **Violações encontradas:**
  - [ ] nenhuma grave. `lojas_formatadas` (formato `,01,07,`) é usado por `fila_automatica` e mora aqui por acaso.
- **Churn:** 1 | **Linhas:** 126 | **Cobertura:** 67%
- **Ação sugerida:** passa a ser usado só por `elegibilidade` e pelas rotas de pausa; `lojas_formatadas` pode ir para `utils`.
- **Esforço:** P | **Risco:** baixo
