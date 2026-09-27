# Backlog de refatoração

Priorizado pela fórmula do plano:

```
prioridade = (churn normalizado × 2) + nº de violações + (1 se desbloqueia algo planejado)
```

- **Churn normalizado** = commits do arquivo mais alterado do item ÷ 70 (o maior do repositório,
  `api.ts`). Histórico desde 18/09/2026.
- **Violações** = quantas caixas da ficha o item resolve.
- **Desbloqueia**: as features citadas no plano (cards clicáveis, "Pagaram em até 7 dias",
  pausa/parada por cliente, régua e loja) já existem. Conta +1 o que protege uma regra fixa do
  negócio (uma mensagem por cliente por dia, GMT-3), deixa a próxima mudança nessas telas menor,
  ou é pré-requisito para travar as regras no CI (Fase 7).

Nenhum item muda comportamento. Cada um é um PR, validado com os scripts de `apps/backend/tests`
(hoje 13, rodados por `tests/rodar_todos.sh`), os testes de caracterização da Fase 5 e a suíte
e2e (173 cenários + login de setup). Itens #1, #2, #3, #4, #8 e #10 já estão feitos (ver
"Estado").

| # | Arquivo(s) | Ação | Esforço | Risco | Desbloqueia | Pontos |
|---|---|---|---|---|---|---|
| 1 ✅ | `routers/uploads.py`, `fila_automatica.py` | Uma função só monta o item da fila (resolve variáveis, formato achatado ou por template) para upload, extração, campanha, remarketing e reaplicar variáveis; `upload_planilha` vira chamada de serviço | M | médio | Toda mudança de variável ou de fila passa a mexer em um lugar, não quatro | 0,8 + 4 + 1 = **5,8** |
| 2 ✅ | `routers/reports.py`, `routers/cobranca.py`, `routers/uploads.py` | Tirar dos routers o que outros usam. Feito assim: gerador de .xlsx e `formula_safe` → `utils/xlsx.py`; `ler_planilha_limitada`, filtros (`filtros_base`, `buscar_base_ou_erro`) e ordenação (`ordenar_clientes`) da base → `routers/comum.py` (não é router); `sem_cobrados_hoje` → `elegibilidade.py` | P | baixo | Fase 7 (nenhum router importa router) | 0,8 + 3 + 1 = **4,8** |
| 3 ✅ | `routers/reports.py`, `routers/dashboard.py` | Camada de leitura da fila (`consultas_fila.py`) usada pelo Dashboard e pelos relatórios; "Descartar fila" (escrita) sai do router de relatórios para Envios | M | baixo | Cards clicáveis: card e relatório contam pela mesma query | 0,8 + 3 + 1 = **4,8** |
| 4 ✅ | `worker.py`, `fila_automatica.py`, `routers/campanhas.py`, `routers/pausas.py` | Centralizar "pode entrar na fila?" e "pode sair agora?" em `elegibilidade.py` (bloqueio do dia, blacklist, pausa); pausar/retomar vira serviço único usado por Pendentes e Campanhas | M | médio | Pausa/parada por cliente, régua e loja; regra de uma mensagem por dia num lugar só | 0,6 + 3 + 1 = **4,6** |
| 5 | `schemas.py` | Pacote `schemas/` com um módulo por domínio, reexportado | M | baixo | — | 1,6 + 2 = **3,6** |
| 6 | `routers/templates.py` | `templates_service.py` com a sincronização da Meta e os tradutores do JSON | M | baixo | — | 0,5 + 3 = **3,5** |
| 7 | `dispatch_service.py` | `MessageSender` com adaptadores Meta e Chatwoot; tratamento de resultado (enviado, erro, incerto) num lugar | M | médio | Troca ou novo provedor de envio | 0,2 + 3 = **3,2** |
| 8 ✅ | `routers/blacklist.py` | `codigos_bloqueados` e a classe `Blacklist` para `app/blacklist.py` | P | baixo | Fase 7 (serviço não importa router); pré-requisito do #4 | 0,1 + 2 + 1 = **3,1** |
| 9 | `apps/frontend/src/api.ts` | Dividir por domínio (`api/cliente.ts` + um arquivo por domínio), `api.ts` reexporta | M | baixo | — | 2,0 + 1 = **3,0** |
| 10 ✅ | 8 arquivos (ver ficha de `timezone.py`) | Conversões de fuso em `timezone.py`; as 8 cópias chamam as funções de lá (a última, `services/compras_seta._dia_br`, criada depois, também saiu) | P | baixo | Regra fixa GMT-3 num lugar só | 0,8 + 1 + 1 = **2,8** |
| 11 | `worker.py` | `_rotinas_do_dia` → `rotinas_diarias.py`; worker fica só com agendamento; janela de disparo em funções puras | M | alto | — | 0,6 + 2 = **2,6** |
| 12 | `remarketing.py`, `routers/remarketing.py` | `renegocie_client.py` (buscar e testar conexão), sem `httpx` solto | P | baixo | — | 0,3 + 2 = **2,3** |
| 13 | `routers/config_cobranca.py` | Separar `/config/cobranca/disparo` e `/orcamento` em routers próprios, mesmas URLs | P | baixo | — | 0,2 + 2 = **2,2** |
| 14 | `routers/reports.py` | Depois de #2 e #3, quebrar o router por relatório, mesmas URLs | M | baixo | — | 0,8 + 1 = **1,8** |
| 15 | `seta_client.py` | Fragmento SQL único de "parcela em aberto" | M | alto | — | 0,6 + 1 = **1,6** |
| 16 | `deps.py` | Registro de atividade (pagamentos do SETA) num middleware em vez de dentro da autenticação | P | baixo | — | 0,1 + 1 = **1,1** |

## Ordem de execução

A tabela diz o que vale mais; a ordem abaixo respeita dependência entre itens e começa pelo que
tem menos risco, para os testes de caracterização pegarem qualquer desvio cedo:

1. **#8** blacklist como serviço (tira 4 imports de serviço → router; o #4 precisa dele).
2. **#2** utilitários fora dos routers (tira todos os imports router → router).
3. **#10** fuso num lugar só (o #4 usa `inicio_hoje_utc`).
4. **#4** elegibilidade: "pode entrar?" e "pode sair?" num módulo só.
5. **#1** montagem única do item da fila.
6. **#3** camada de leitura da fila.
7. **Fase 7**: import-linter no CI, com as exceções que sobrarem listadas e apontando para o item
   que as remove.

Itens #5 a #7 e #9 em diante ficam para depois: nenhum deles protege regra fixa nem é
pré-requisito de outro.

## Fora do escopo da refatoração (comportamento)

Achados que mudariam o que o sistema faz. Não entram em PR de refatoração; ficam para o usuário
decidir:

- **Upload de planilha na faixa com Lead sem parcelas**: a variável ligada à coluna de valor
  usa o valor em atraso com juros do Lead da faixa. O Lead que o próprio upload cria (cliente só
  na planilha) não tem parcelas, então num upload seguinte do mesmo cliente nessa faixa o valor
  ia "0,00" em vez do valor da planilha. Resolvido em 2026-09-27: cadastro zerado cai no valor
  da planilha; linha com valor zerado volta para o usuário escolher um valor do sistema ou
  descartar.

## Estado

| # | PR | Estado |
|---|---|---|
| — | Fases 0 a 4 (esta documentação) e Fase 8 | PR #1, mergeado |
| — | Fase 5: testes de caracterização e CI em todo PR | PR #2, mergeado |
| 8 | Blacklist como serviço | PR #3, mergeado |
| 2 | Utilitários fora dos routers | PR #4, mergeado |
| 10 | Fuso num lugar só | PR #5, mergeado |
| 4 | Elegibilidade (`elegibilidade.py`, pausar/retomar único) | PR #6, mergeado |
| 1 | Montagem única do item da fila (`itens_fila.py`); upload vira serviço (`upload_service.py`) | PR #7, mergeado |
| 3 | Camada de leitura da fila (`consultas_fila.py`) | PR #8, mergeado |
| — | Fase 7: import-linter no CI | PR #9, mergeado |
| — | Trava de entrada na fila (`elegibilidade.travar_entrada_na_fila`, muda comportamento) | PR #10, mergeado |
| — | Valor zerado na planilha da faixa: usuário escolhe o valor ou descarta (comportamento, ver acima) | commits `28ab550` e seguinte em main |

Os PRs #1 a #9 foram empilhados (cada um sobre o anterior, para o CI e o teste de caracterização
valerem em todos) e já estão todos em main. Próximos itens abertos: #5, #6, #7, #9, #11 a #16.

Exceções que ficaram no import-linter (`apps/backend/.importlinter`): `deps` → `pagamentos_seta`
(sai no #16), `remarketing` e `routers/remarketing` → `httpx` (sai no #12) e
`routers/meta_tokens` → `httpx`, que só captura o `httpx.HTTPError` que o `meta_client` deixa
passar (sai quando o `meta_client` tiver erro próprio, junto do #7).
