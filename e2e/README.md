# Testes ponta a ponta (Playwright)

Agente de QA do FintechCRM: 183 cenários (mais o login de setup, `tests/auth.setup.ts`) que usam o app pelo navegador, tela por tela, contra um
ambiente **de teste** montado do zero. Nada aqui fala com produção: o SETA é um Postgres local com
clientes fictícios, e a Meta, o Chatwoot, o Google Sheets, o câmbio e o portal TopFamaRenegocie são simulados dentro do
próprio backend de teste. Nenhuma mensagem de WhatsApp sai de verdade.

## Como rodar

Pré-requisitos: Postgres local (usuário `postgres` com permissão de criar bancos), Redis local,
Python 3.12 (o mesmo do CI) e Node 20+. No CI a suíte roda em todo PR (job `e2e` de
`.github/workflows/testes.yml`).

```bash
cd e2e
npm install
./ambiente/subir.sh          # recria os bancos de teste, sobe backend (8010) e frontend (4174)
npx playwright test          # roda todos os cenários em série
npx playwright show-report   # relatório HTML com screenshots e traces das falhas
```

Cada spec prepara sozinho o estado de que precisa, por API, em `tests/preparo.ts` (token e números,
templates, faixas, blacklist, fila de disparo, operação com envios e erros). Nenhum depende de outro
spec ter rodado antes, então qualquer spec ou tag roda sozinho num `./ambiente/subir.sh` novo:

```bash
npx playwright test tests/12-dashboard.spec.ts   # um spec
npx playwright test --grep "@pagamentos\b"        # uma funcionalidade, em todos os specs
npx playwright test --grep "@smoke\b"             # a fumaça (login, Dashboard, Cobrança, Relatórios, Configurações)
```

Dentro de um spec os cenários seguem em série e alguns usam o que o anterior fez; por isso uma tag
sempre marca o `describe` inteiro desses specs (10, 11, 16, 17, 18), e só marca cenário solto onde
cada um começa do zero (09, 12, 13, 14).

## Tags

Todo `describe` principal leva a tag da tela (`@cobranca`, `@dashboard`, `@relatorios`…) e os
cenários que verificam outra funcionalidade levam também a dela:

| Tag | O que verifica |
|---|---|
| `@smoke` | Fumaça: as telas principais abrem e mostram dados |
| `@login` `@conexoes` `@templates` `@faixas` `@horario` `@indicadores` `@blacklist` `@usuarios` `@lojas` | Telas de Configurações e login |
| `@cobranca` `@importacao` `@fila` `@disparo` `@leads` `@elegibilidade` `@pausas` | Consulta e envio para a fila, importação, fila e disparo, leads, no máximo uma cobrança por dia, pausas |
| `@dashboard` `@relatorios` | Telas de números e relatórios |
| `@pagamentos` `@pagos-janela` `@efetividade` `@orcamento` | Cards e abas de pagamento, "Pagaram em até 7 dias", efetividade e orçamento (os cálculos em si são conferidos nos testes do backend; aqui, só o que aparece na tela) |
| `@campanhas` `@remarketing` | Campanhas e remarketing do Renegocie |
| `@resiliencia` | Erro, SETA/Meta fora do ar, cancelamento e atualização automática |
| `@visual` | Aparência medida (cores, alinhamento, larguras, rolagem) |

**Cenário novo:** use a tag da tela no `describe` e acrescente as demais que ele exercita.
O `selecionar-telas.test.mjs` reprova tag usada no spec e ausente do mapa, e o contrário.

## Seleção no CI

`selecionar-telas.mjs` decide o que rodar pelos arquivos alterados. A pergunta que guia o mapa é
"qual comportamento observável esta alteração pode quebrar?":

| Classe | Exemplos | O que roda |
|---|---|---|
| global (`GLOBAIS`) | `App.tsx`, `main.py`, `config.py`, `deps.py`, `timezone.py`, `worker.py`, ambiente de teste, `fixtures.ts` | suíte inteira |
| contrato (`CONTRATOS`) | `api.ts`, `schemas.py`, `models.py`, `format.ts` | suíte inteira, a menos que a mesma mudança aponte funcionalidades específicas: aí só elas e a fumaça |
| visual (`VISUAIS`) | `styles.css`, `icons.tsx` | `@visual` e fumaça |
| funcional (`FUNCIONALIDADES`) | cada arquivo de tela, router, serviço ou módulo | as tags que o usam (ex.: `custo_whatsapp.py` → `@orcamento` e `@efetividade`) e a fumaça |
| CI (`CI`) | workflows de teste, o próprio seletor | só a fumaça |
| spec, helper ou planilha de `e2e/tests` | `12-dashboard.spec.ts`, `preparo.ts` | o spec inteiro; o helper roda os specs que o importam |
| fora do app | `.md`, `apps/backend/tests/**`, outros workflows | nada (o job é pulado) |

Arquivo do app que nenhuma classe declara roda a suíte inteira (na dúvida, testa tudo). A suíte
inteira também roda toda segunda-feira e sob demanda ("Run workflow" → `completa`), e o backend
(`tests/rodar_todos.sh`) e o build do frontend rodam sempre, completos.

`node selecionar-telas.mjs alterados.txt` mostra a escolha (JSON com `grep`, `tags` e o motivo de
cada arquivo). Os testes do seletor: `node --test selecionar-telas.test.mjs` (job `seletor` do CI);
eles reprovam arquivo do app sem classe, arquivo citado no mapa que não existe mais e tag fora de sincronia.

**Arquivo, spec ou tela nova:** declare o arquivo em `FUNCIONALIDADES` (ou na classe certa) e o
`describe` com as tags. O workflow `e2e-mapa.yml` roda cada spec e cada tag sozinho; se um falha
lá, o cenário depende de outro: prepare o estado em `tests/preparo.ts` ou marque o `describe`
inteiro. Se o Chromium do
Playwright não estiver baixado, a configuração usa o que estiver em `$CHROMIUM_PATH` ou em
`$PLAYWRIGHT_BROWSERS_PATH` (padrão `/opt/pw-browsers`; não precisa de `playwright install` nesse caso).

## O que tem em cada pasta

| Caminho | O que é |
|---|---|
| `selecionar-telas.mjs`, `selecionar-telas.test.mjs` | Mapa funcionalidade (tag) → arquivos do app; escolhe os cenários do e2e no CI; testes do seletor |
| `ambiente/subir.sh` | Recria `crm_app` e `seta_fake`, popula o SETA falso e sobe backend + frontend |
| `ambiente/env.teste.sh` | Variáveis só de teste (nunca usa o `.env` do projeto) |
| `ambiente/seta_falso.py` | Tabelas do SETA que o backend lê (`pessoas`, `financeiro_titulos`, `vendas`, `condicoes`, `caixa_lotes`) com 36 clientes fictícios cobrindo todas as faixas de atraso |
| `ambiente/servidor_teste.py` | Sobe o backend com Meta, Chatwoot, Google, câmbio e Renegocie simulados; `GET /__e2e/envios` lista o que teria sido enviado |
| `ambiente/gerar_planilhas.py` | Gera as planilhas fictícias de `tests/dados/` |
| `tests/99-smoke.spec.ts` | Fumaça (`@smoke`): login, Dashboard, Cobrança, Relatórios e Configurações |
| `tests/01…18-*.spec.ts` | Cenários por tela: login, Conexões, Templates, Faixas, Horário, Indicadores, Blacklist, Usuários, Cobrança, importação/fila, disparo, Dashboard, Relatórios, erros, Lojas, Remarketing, Pausas, Campanhas |
| `tests/auth.setup.ts` | Login de setup, que grava a sessão usada pelos demais cenários |
| `tests/fixtures.ts`, `tests/ambiente.ts` | Fixtures e helpers compartilhados (acesso ao ambiente de teste) |
| `tests/preparo.ts` | Prepara por API o estado de cada spec (conexões, templates, faixas, blacklist, fila, operação) |
| `tests/dados/` | Planilhas fictícias usadas nos uploads |

## Bugs conhecidos

Hoje nenhum cenário está marcado assim. A convenção: cenários marcados com
`test.fail(true, "BUG: …")` descrevem o comportamento correto e hoje falham
por causa de um bug do app. Eles aparecem como aprovados enquanto o bug existir; quando o bug for
corrigido, o Playwright acusa "Expected to fail, but passed" — é só remover a linha `test.fail`.
