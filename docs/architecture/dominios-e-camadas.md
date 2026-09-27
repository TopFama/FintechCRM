# Domínios e camadas

É a régua do review: onde cada coisa deveria morar. As fichas (`fichas/`) comparam cada arquivo
com este mapa, e as regras do fim viram contratos do import-linter no CI.

## Domínios

Ajustado ao que existe no código (revisado em 27/09/2026). "Hoje em" lista os arquivos do backend que já
são desse domínio (a mesma tabela está em `scripts/grafo_dependencias.py`, que colore o
`deps.svg`).

| Domínio | Responsabilidade | Hoje em |
|---|---|---|
| **Autenticação** | Login, sessão, usuários, permissão (admin) | `routers/auth.py`, `routers/users.py`, `security.py`, `deps.py`, `rate_limit.py` |
| **Integrações** | Clientes de sistemas externos e seus cadastros (tokens, números, conexões) | `meta_client.py`, `chatwoot_client.py`, `google_client.py`, `seta_client.py`, `cambio.py`, `crypto.py`, `segredos.py`, `routers/meta_tokens.py`, `routers/numbers.py`, `routers/chatwoot.py`, `routers/google.py`, `routers/seta.py` |
| **Templates** | Templates da Meta, variáveis e como cada variável é resolvida | `routers/templates.py`, `variaveis_template.py`, `utils/imagem.py` |
| **Lojas** | Cadastro de lojas, cluster INAD, cobradora, sincronização com a planilha | `lojas.py`, `lojas_iniciais.py`, `routers/lojas.py` |
| **Cobrança** | Base de clientes em atraso do SETA, regras (clusters, faixas de atraso, matriz WhatsApp, juros), leads | `cobranca_base.py`, `cobranca_regras.py`, `regras_db.py`, `cobranca_relatorio.py`, `leads_service.py`, `routers/cobranca.py`, `routers/config_cobranca.py`, `routers/leads.py`, `utils/leads_xlsx.py`, `utils/spc.py`, `services/compras_seta.py` |
| **Réguas** | Faixas de envio: pares número + template, mapeamento de variáveis, agenda por envio | `routers/faixas.py` (modelos `Faixa`, `FaixaEnvio`, `DispatchConfig`, `FaixaVariableMapping`) |
| **Envios** | Fila, disparo, "pode entrar / pode sair", pausa e parada, blacklist, upload de planilha na faixa, histórico | `fila_automatica.py`, `elegibilidade.py`, `itens_fila.py`, `upload_service.py`, `blacklist.py`, `worker.py`, `dispatch_service.py`, `pausas.py`, `routers/pausas.py`, `routers/uploads.py`, `routers/blacklist.py` |
| **Campanhas** | Campanhas (manuais e com envio automático) e o remarketing do Renegocie, que é campanha fixa | `campanhas.py`, `campanhas_fixas.py`, `remarketing.py`, `routers/campanhas.py`, `routers/remarketing.py` |
| **Pagamentos** | Cópia local das baixas do SETA e "quem pagou" | `services/pagamentos_seta.py`, `services/pagamentos_service.py`, `services/pagos_janela_service.py` |
| **Dashboard/Relatórios** | Leitura: cards, relatórios, efetividade, orçamento e custo do WhatsApp | `routers/dashboard.py`, `routers/reports.py`, `consultas_fila.py`, `services/efetividade_service.py`, `relatorio_efetividade.py`, `services/custo_whatsapp.py` |
| **Plataforma** | O que todo domínio usa e não é de nenhum | `main.py`, `config.py`, `database.py`, `models.py`, `schemas.py`, `cache.py`, `timezone.py`, `utils/phone.py`, `utils/document.py`, `utils/spreadsheet.py`, `utils/xlsx.py`, `utils/erros.py`, `routers/comum.py` |

Diferenças para a tabela sugerida no plano: não há domínio "Clientes" separado (o cliente é o do
SETA, lido em Cobrança, e o `Lead` é a fotografia dele no dia); "Cobranças" virou **Cobrança**
(base e regras); **Templates**, **Campanhas** e **Pagamentos** entraram porque têm regra própria.

### Frontend

O frontend segue os mesmos domínios pela tela: `pages/Cobranca.tsx` (Cobrança), `Faixas.tsx`,
`FaixaWizard.tsx` e `FaixaDetail.tsx` (Réguas), `Campanhas.tsx`/`CampanhaDetail.tsx` (Campanhas), `Dashboard.tsx` e `Relatorios.tsx`
(Dashboard/Relatórios), `Configuracoes.tsx` com `components/config/*` (Integrações, Templates,
Lojas, Autenticação, regras de Cobrança, Campanhas — remarketing e conexão com o Renegocie —,
Envios — horário de disparo e blacklist — e Dashboard — orçamento). `api.ts` é Plataforma, mas hoje carrega os tipos de
todos os domínios num arquivo só.

## Camadas

```
interface     routers/ (HTTP), worker.py (agendamento)       ← recebe o pedido, valida, formata resposta
    ↓
aplicação     serviços por domínio (fila_automatica, campanhas, cobranca_base, services/…)
    ↓                                                         ← orquestra o caso de uso, controla transação
domínio       regras puras (cobranca_regras, variaveis_template, relatorio_efetividade, pausas.Retencao)
    ↑
infraestrutura  models/database (ORM), seta_client, meta_client, chatwoot_client, google_client,
                cambio, cache, crypto                         ← implementa o acesso ao mundo de fora
```

Neste projeto a regra é aplicada de forma pragmática, sem reescrever o que funciona: não vamos
criar repositórios para toda tabela nem esconder o ORM atrás de interfaces genéricas. O alvo é
tirar do caminho os acoplamentos que já causaram ou podem causar bug.

## Regras de dependência

1. **Nenhum módulo importa um router**, exceto `main.py` (que registra os routers). Routers
   podem importar `routers/comum.py`, que não é router (peças HTTP compartilhadas, sem rota). Função usada
   por mais de um lugar sai do router para o serviço do domínio ou para `utils/`.
2. **Router não contém regra de negócio.** Pode consultar o banco para ler e montar resposta
   simples, mas decisões (quem entra na fila, quem pode receber, como uma variável é resolvida)
   ficam no serviço do domínio.
3. **Um domínio usa outro pelo serviço dele**, não pelas tabelas. Exceção aceita: leitura de
   `models` para consultas de Dashboard/Relatórios, que é a camada de leitura do sistema.
4. **Integração externa só pelo cliente dela** (`meta_client`, `chatwoot_client`, `seta_client`,
   `google_client`, `cambio` e, a criar, `renegocie_client`). Nada de `httpx` solto em router ou
   serviço.
5. **Regras puras não importam infraestrutura**: `cobranca_regras`, `relatorio_efetividade`,
   `utils/*` não importam `models`, `database`, `seta_client` nem FastAPI.
6. **Autenticação não conhece outros domínios**: `deps.py` só autentica.

### Regras fixas do negócio que qualquer refatoração tem que preservar

- **No máximo uma comunicação por cliente por dia**, em qualquer caminho de envio (régua,
  campanha, remarketing, upload de planilha). Tudo mora em
  `elegibilidade.py` (backlog #4, PR #6). Entrada: `clientes_bloqueados_hoje` (que também trava
  a entrada na fila com lock do Postgres, `travar_entrada_na_fila`, até o commit de quem chamou) e
  `sem_cobrados_hoje`. Saída: `conferir_saida` (pausa, blacklist e `ja_cobrado_hoje`), chamada
  pelo `worker.py` antes de cada envio. Só ocupa o cliente quem foi enviado, está pendente/reservado ou teve falha
  incerta (timeout) na Meta.
- **SETA só leitura**: nenhum `INSERT/UPDATE/DELETE/DDL`; consultas em lote (CTE + `VALUES`),
  nunca em loop por cliente. Toda consulta nova ao SETA entra em `seta_client.py`.
- **Horário de negócio em GMT-3** (`timezone.BUSINESS_TZ`); o banco da app grava UTC ingênuo.
- **`.env` não muda** (nomes, valores, local).

## Como as regras viram CI

Fase 7: contratos do [import-linter](https://import-linter.readthedocs.io/) em
`apps/backend/.importlinter`, rodando em todo PR:

- `forbidden`: nenhum módulo fora de `app.main` e `app.routers` importa `app.routers.*` (regra 1).
- `independence`: os routers não importam uns aos outros (regra 1); `routers.comum` fica fora da
  lista, então pode ser importado por eles.
- `forbidden`: `app.cobranca_regras`, `app.relatorio_efetividade` e `app.utils` não importam
  `app.models`, `app.database`, `app.seta_client`, `fastapi` (regra 5).
- `forbidden`: `app.deps` não importa serviços (`blacklist`, `campanhas`, …, `services`,
  `seta_client`, `worker`) (regra 6); exceção `app.deps -> app.services.pagamentos_seta` (#16).
- `forbidden`: routers e serviços não importam `httpx`/`requests` (regra 4); exceções
  `remarketing` e `routers.remarketing` (#12) e `routers.meta_tokens` (nota no #7).

Contratos que ainda não passam entram com `ignore_imports` listando as exceções atuais, cada uma
apontando para o item do backlog que a remove. Assim o CI trava exceção nova sem esperar a
refatoração inteira.
