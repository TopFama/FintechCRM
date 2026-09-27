# Fichas — Envios

Fila (`cobranca_fila`, modelo `QueueItem`), disparo, pausa/parada, blacklist e upload de planilha
na faixa. É o domínio que carrega a regra fixa de **uma comunicação por cliente por dia**, então
foi o primeiro alvo. Fichas revisadas em 27/09/2026, depois dos PRs #3 a #10; churn e cobertura
são os da fotografia de 26/09 (histórico desde 18/09/2026).

## Achado central (resolvido): "pode entrar?" e "pode sair?" estavam espalhados

Em 26/09 cada caminho de envio tinha a sua cópia das checagens de entrada e saída, e as três de
saída estavam escritas dentro do laço do worker. O backlog #4 (PR #6) juntou tudo em
`elegibilidade.py`, e o PR #10 acrescentou a trava de entrada. Onde cada checagem mora hoje:

| Checagem | Onde acontece hoje |
|---|---|
| Pendente/reservado ou cobrado hoje (entrada) | `elegibilidade.clientes_bloqueados_hoje` (trava a entrada com `travar_entrada_na_fila`, lock do Postgres até o commit), chamada por `fila_automatica.enfileirar_leads`/`enfileirar_clientes`, `campanhas.executar`, `remarketing.enfileirar` e `upload_service.importar_planilha` |
| Cobrado hoje (lista da tela) | `elegibilidade.sem_cobrados_hoje` (usa `cobrados_hoje`), chamada por `routers/cobranca` e `routers/leads` |
| Blacklist (entrada) | classe `blacklist.Blacklist`: `cobranca_base.buscar_base` (na consulta ao SETA), `remarketing`, `upload_service`, `routers/leads` |
| Pausa, blacklist e cobrado hoje (saída) | `elegibilidade.conferir_saida`, chamada pelo `worker.run_dispatch_cycle` antes de cada envio; o worker ainda filtra a busca de pendentes por `retencao.faixas`/`retencao.condicao()`, e `campanhas.campanhas_para_hoje` relê as pausas de faixa |
| Janela/horário | `worker._within_schedule_window`, `_due`, `_na_janela_diaria` |

---

### `apps/backend/app/elegibilidade.py`
- **Domínio:** Envios
- **Camada:** aplicação (regra fixa de uma comunicação por cliente por dia)
- **Responsabilidade (1 frase, sem "e"):** dizer quem pode entrar na fila e quem pode sair agora.
- **Depende de:** `models`, `blacklist`, `pausas.Retencao`, `timezone`.
- **É usado por:** `worker`, `fila_automatica`, `campanhas`, `remarketing`, `upload_service`, `routers/cobranca`, `routers/leads`.
- **Violações encontradas:** nenhuma.
- **Linhas:** 128

### `apps/backend/app/upload_service.py`
- **Domínio:** Envios
- **Camada:** aplicação
- **Responsabilidade (1 frase, sem "e"):** importar as linhas da planilha na fila de uma faixa da régua.
- **Motivos para mudar:** formato da planilha, validação por linha (código, nome, CPF, telefone, valor zerado), criação de Lead, telefone inválido.
- **Depende de:** `itens_fila`, `blacklist`, `elegibilidade`, `pausas.lojas_formatadas`, `regras_db`, `seta_client`, `variaveis_template`, `timezone`, `utils/document`, `utils/phone`, `models`, `schemas`.
- **É usado por:** `routers/uploads`.
- **Violações encontradas:**
  - [x] Mais de uma responsabilidade: `importar_planilha` ainda é uma função longa (normaliza, valida, cria `QueueItem`, `Lead` e `InvalidPhoneRecord`), mas a montagem do item já vem de `itens_fila`.
- **Linhas:** 407
- **Nota de comportamento:** o valor em atraso zerado do cadastro cai no valor da planilha; linha com valor zerado (na planilha ou na variável de valor) não entra: volta no resultado do upload para o usuário escolher um valor do sistema ou descartar, e a escolha entra por `POST /faixas/{id}/uploads/valores-zerados` (27/09/2026).

### `apps/backend/app/itens_fila.py`
- **Domínio:** Envios
- **Camada:** aplicação
- **Responsabilidade (1 frase, sem "e"):** montar o item da fila a partir das fontes de variável de cada template ativo da faixa.
- **Depende de:** `models`, `variaveis_template`, `utils/leads_xlsx`.
- **É usado por:** `fila_automatica`, `upload_service`, `routers/uploads`.
- **Violações encontradas:** nenhuma (é o ponto único do backlog #1, PR #7).
- **Linhas:** 108

### `apps/backend/app/routers/uploads.py`
- **Domínio:** Envios
- **Camada:** interface
- **Responsabilidade (1 frase, sem "e"):** receber a planilha de clientes de uma faixa.
- **Depende de:** `upload_service`, `itens_fila`, `variaveis_template`, `utils/spreadsheet`, `routers/comum.ler_planilha_limitada`, `models`, `schemas`.
- **É usado por:** `main`.
- **Violações encontradas:** as de 26/09 (função de ~350 linhas no router, montagem duplicada do item, utilitário usado por outros routers) foram resolvidas pelos backlogs #1 e #2: `upload_planilha` lê a requisição, valida o mapeamento e chama `upload_service.importar_planilha`.
- **Churn:** 28 commits | **Linhas:** 202 | **Cobertura:** 70% (medida em 26/09)
- **Achado de comportamento:** resolvido em 27/09/2026 (commit `28ab550`), ver backlog → "Fora do escopo da refatoração".

### `apps/backend/app/worker.py`
- **Domínio:** Envios
- **Camada:** interface (agendamento) com aplicação dentro
- **Responsabilidade (1 frase, sem "e"):** decidir quando cada rotina roda.
- **Motivos para mudar:** horário/janela, rotinas do dia (extração, remarketing, campanhas, régua pós-campanha, expiração), espera após falha, sincronização de pagamentos, cópia das compras do SETA.
- **Depende de:** `campanhas`, `remarketing`, `cobranca_base` (import local), `leads_service`, `fila_automatica`, `elegibilidade`, `blacklist`, `pausas`, `dispatch_service`, `seta_client`, `services/pagamentos_seta`, `services/compras_seta`, `timezone`, `config`, `database`, `models`.
- **É usado por:** `main`.
- **Violações encontradas:**
  - [x] Mais de uma responsabilidade: agenda e orquestra as rotinas do dia (`_rotinas_do_dia`, backlog #11).
  - [x] SQL/ORM fora do repository: busca de `DispatchConfig` e de pendentes inline.
  - [x] Dependência circular (contornada): `import` local de `campanhas`, `remarketing` e `cobranca_base` "para evitar ciclo".
  - [x] Duplicação de regra: janela de dia de disparo calculada em 4 funções parecidas (`_within_schedule_window`, `_deve_extrair_leads`, `_na_janela_diaria`, e `fila_automatica.ultimo_fim_de_janela`).
  - Resolvido: as checagens de saída saíram do laço para `elegibilidade.conferir_saida` (backlog #4).
- **Churn:** 22 | **Linhas:** 396
- **Ação sugerida:** `_rotinas_do_dia` vai para `rotinas_diarias.py`, deixando no worker só o agendamento (backlog #11); cálculo de janela vai para um `janela_disparo.py` puro.
- **Esforço:** M | **Risco:** alto (é o disparo; `test_worker_schedule.py` cobre só a janela)

### `apps/backend/app/fila_automatica.py`
- **Domínio:** Envios
- **Camada:** aplicação
- **Responsabilidade (1 frase, sem "e"):** colocar clientes na fila da faixa certa.
- **Motivos para mudar:** entrada de leads/clientes na fila, expiração no fim da janela, descarte de pendentes, reaplicar variáveis.
- **Depende de:** `models`, `itens_fila`, `elegibilidade`, `pausas.lojas_formatadas`, `regras_db`, `variaveis_template`, `utils/leads_xlsx`, `utils/phone`, `timezone`.
- **É usado por:** `worker`, `campanhas`, `remarketing`, `routers/leads`, `routers/pausas`, `routers/reports` (descartar fila).
- **Violações encontradas:** as de 26/09 (serviço importando `routers.blacklist`, montagem do item repetida, helpers de fuso e de bloqueio do dia aqui dentro) foram resolvidas pelos backlogs #1, #4, #8 e #10. Restam `enfileirar_clientes`, `enfileirar_leads`, `reaplicar_variaveis`, `ultimo_fim_de_janela`, `expirar_nao_enviados` e `descartar_pendentes`.
- **Churn:** 13 | **Linhas:** 287 | **Cobertura:** 37% (medida em 26/09)

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
- **Depende de:** `pausas` (serviço de pausar/retomar/parar), `fila_automatica.reaplicar_variaveis`, `regras_db`, `models`.
- **É usado por:** `main`.
- **Violações encontradas:**
  - [x] SQL/ORM no router: `opcoes_fila` e `_valor_legivel` consultam fila, faixa e lojas direto.
  - [ ] demais: não.
- **Autorização:** todas as rotas usam `get_current_user` (qualquer usuário logado pausa/para), igual ao resto do app; a regra está num lugar só (`deps.py`), não duplicada.
- **Churn:** 2 | **Linhas:** 188 | **Cobertura:** 27% (medida em 26/09)
- **Ação sugerida:** nenhuma urgente; as consultas de opções podem ir para a camada de leitura da fila (backlog #3).
- **Esforço:** P | **Risco:** baixo

### `apps/backend/app/routers/blacklist.py`
- **Domínio:** Envios
- **Camada:** interface
- **Responsabilidade:** expor o cadastro da blacklist.
- **Violações encontradas:** nenhuma. A de 26/09 (serviços importando `codigos_bloqueados` do router) foi resolvida pelo backlog #8 (PR #3): `codigos_bloqueados` e a classe `Blacklist` moram em `app/blacklist.py` (29 linhas), usado por `worker`, `elegibilidade`, `cobranca_base`, `remarketing`, `upload_service` e `routers/leads`.
- **Churn:** 2 | **Linhas:** 89

### `apps/backend/app/pausas.py`
- **Domínio:** Envios
- **Camada:** domínio + aplicação
- **Responsabilidade:** retenção por pausa ativa e pausar/retomar/parar por escopo (cliente, faixa, loja).
- **Depende de:** `models`, `timezone`, `utils/document`.
- **É usado por:** `worker`, `elegibilidade`, `fila_automatica`, `upload_service`, `campanhas`, `consultas_fila`, `routers/pausas`, `routers/campanhas`, `routers/reports`.
- **Violações encontradas:**
  - [ ] nenhuma grave. `lojas_formatadas` (formato `,01,07,`) é usado por `fila_automatica` e `upload_service` e mora aqui por acaso.
- **Churn:** 1 | **Linhas:** 155 | **Cobertura:** 67% (medida em 26/09)
- **Ação sugerida:** `lojas_formatadas` pode ir para `utils`.
- **Esforço:** P | **Risco:** baixo
