# Testes ponta a ponta (Playwright)

Exercitam as telas de Cobrança, Leads, Blacklist e Configurações contra um frontend e um backend
já em execução — a suíte não sobe nem derruba servidores.

```bash
npm install
npx playwright install chromium
npx playwright test
```

| Variável | Padrão | Uso |
|---|---|---|
| `E2E_BASE_URL` | `http://localhost:4174` | frontend (ex.: `vite preview` de um build com `VITE_API_URL` apontando para o backend abaixo) |
| `E2E_API_URL` | `http://localhost:8010` | backend, usado para limpar dados criados pelos testes |
| `E2E_EMAIL` / `E2E_SENHA` | admin de teste | usuário com acesso ao portal |

Efeitos colaterais: cria leads (cenário 3) e marca dois como enviados (cenário 4) — rode contra um banco de
aplicação descartável, nunca produção. As entradas criadas na blacklist são removidas ao final. As telas de
Cobrança consultam o ERP de verdade e podem levar até um minuto por consulta.
