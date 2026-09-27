# Fichas — Lojas

### `apps/backend/app/lojas.py`
- **Domínio:** Lojas
- **Camada:** aplicação
- **Responsabilidade:** manter o cadastro de lojas.
- **Motivos para mudar:** colunas da planilha de lojas, filtros por cluster/cobradora.
- **Depende de:** `config`, `google_client`, `lojas_iniciais`, `models`.
- **É usado por:** `campanhas`, `remarketing`, `main`, routers de cobrança, leads, google, lojas, efetividade e pagamentos.
- **Violações encontradas:**
  - [ ] Nenhuma relevante. Há um cache em memória do processo, mas só para o caso de a tabela `lojas` estar vazia (lê direto da planilha).
- **Churn:** 3 | **Linhas:** 232
- **Ação sugerida:** nenhuma agora.

### `apps/backend/app/routers/lojas.py`
- **Domínio:** Lojas
- **Camada:** interface
- **Responsabilidade:** expor o cadastro de lojas.
- **Violações encontradas:**
  - [x] Importa `routers.uploads._ler_planilha_limitada` e lê planilha com funções de `campanhas.py` (imports locais dentro da função).
- **Churn:** 5 | **Linhas:** 155
- **Ação sugerida:** leitura de planilha em `utils/spreadsheet.py` (backlog #2).
- **Esforço:** P | **Risco:** baixo
