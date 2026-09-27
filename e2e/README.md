# Testes ponta a ponta (Playwright)

Agente de QA do FintechCRM: 173 cenários (mais o login de setup, `tests/auth.setup.ts`) que usam o app pelo navegador, tela por tela, contra um
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
npx playwright test          # roda os 173 cenários em série
npx playwright show-report   # relatório HTML com screenshots e traces das falhas
```

Os cenários dependem uns dos outros (cadastram token, números, faixas, fila e envios em sequência),
então rode sempre a suíte inteira depois de um `./ambiente/subir.sh` novo. Se o Chromium do
Playwright não estiver baixado, a configuração usa o que estiver em `$CHROMIUM_PATH` ou em
`$PLAYWRIGHT_BROWSERS_PATH` (padrão `/opt/pw-browsers`; não precisa de `playwright install` nesse caso).

## O que tem em cada pasta

| Caminho | O que é |
|---|---|
| `ambiente/subir.sh` | Recria `crm_app` e `seta_fake`, popula o SETA falso e sobe backend + frontend |
| `ambiente/env.teste.sh` | Variáveis só de teste (nunca usa o `.env` do projeto) |
| `ambiente/seta_falso.py` | Tabelas do SETA que o backend lê (`pessoas`, `financeiro_titulos`, `vendas`, `condicoes`, `caixa_lotes`) com 36 clientes fictícios cobrindo todas as faixas de atraso |
| `ambiente/servidor_teste.py` | Sobe o backend com Meta, Chatwoot, Google, câmbio e Renegocie simulados; `GET /__e2e/envios` lista o que teria sido enviado |
| `ambiente/gerar_planilhas.py` | Gera as planilhas fictícias de `tests/dados/` |
| `tests/01…18-*.spec.ts` | Cenários por tela: login, Conexões, Templates, Faixas, Horário, Indicadores, Blacklist, Usuários, Cobrança, importação/fila, disparo, Dashboard, Relatórios, erros, Lojas, Remarketing, Pausas, Campanhas |
| `tests/auth.setup.ts` | Login de setup, que grava a sessão usada pelos demais cenários |
| `tests/fixtures.ts`, `tests/ambiente.ts` | Fixtures e helpers compartilhados (acesso ao ambiente de teste) |
| `tests/dados/` | Planilhas fictícias usadas nos uploads |

## Bugs conhecidos

Hoje nenhum cenário está marcado assim. A convenção: cenários marcados com
`test.fail(true, "BUG: …")` descrevem o comportamento correto e hoje falham
por causa de um bug do app. Eles aparecem como aprovados enquanto o bug existir; quando o bug for
corrigido, o Playwright acusa "Expected to fail, but passed" — é só remover a linha `test.fail`.
