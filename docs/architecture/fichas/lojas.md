# Fichas — Lojas

### `apps/backend/app/lojas.py`
- **Domínio:** Lojas
- **Camada:** aplicação
- **Responsabilidade:** manter o cadastro de lojas.
- **Motivos para mudar:** colunas da planilha de lojas, filtros por cluster/cobradora.
- **Depende de:** `config`, `google_client`, `lojas_iniciais`, `models`.
- **É usado por:** `campanhas`, `remarketing`, `main`, `routers/comum` (filtros da base), `routers/leads`, `routers/google`, `routers/lojas` e os serviços de efetividade e pagamentos.
- **Violações encontradas:**
  - [ ] Nenhuma relevante. Há um cache em memória do processo, mas só para o caso de a tabela `lojas` estar vazia (lê direto da planilha).
- **Churn:** 3 | **Linhas:** 232
- **Ação sugerida:** nenhuma agora.

### `apps/backend/app/routers/lojas.py`
- **Domínio:** Lojas
- **Camada:** interface
- **Responsabilidade:** expor o cadastro de lojas.
- **Violações encontradas:**
  - [x] Lê planilha com funções de `campanhas.py` (`colunas_planilha`, `ler_lojas`, imports locais dentro da função). Resolvido pela metade no backlog #2: o limite de tamanho do upload vem de `routers.comum.ler_planilha_limitada`, não mais de `routers.uploads`.
- **Churn:** 5 | **Linhas:** 155
- **Ação sugerida:** leitura de planilha de lojas em `utils/spreadsheet.py`.
- **Esforço:** P | **Risco:** baixo
