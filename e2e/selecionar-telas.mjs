// Escolhe quais cenários e2e rodar num PR, pelos arquivos alterados: cada tela
// (spec) roda se mudou um arquivo que ela testa, junto com os cenários de que ela
// depende (a suíte roda em série e cada um usa o que os anteriores cadastraram).
// Arquivo usado por todas as telas → suíte inteira. Arquivo de app fora do mapa
// → suíte inteira (na dúvida, testa tudo).
//
//   node selecionar-telas.mjs <arquivo com a lista de alterados, um por linha>
//     imprime "todos", "nenhum" ou os specs separados por espaço
//   node selecionar-telas.mjs --spec 12-dashboard
//     imprime o spec e seus pré-requisitos (usado pelo workflow e2e-mapa.yml)

import fs from "node:fs";

const F = "apps/frontend/src/";
const B = "apps/backend/app/";

// Mudou algum destes: roda tudo.
const GLOBAIS = [
  `${F}api.ts`, `${F}App.tsx`, `${F}main.tsx`, `${F}styles.css`, `${F}format.ts`, `${F}sort.ts`,
  `${F}icons.tsx`, `${F}vite-env.d.ts`, "apps/frontend/index.html", "apps/frontend/vite.config.*",
  "apps/frontend/tsconfig*.json", "apps/frontend/package*.json", "apps/frontend/public/**",
  `${B}main.py`, `${B}models.py`, `${B}schemas.py`, `${B}config.py`, `${B}database.py`, `${B}deps.py`,
  `${B}security.py`, `${B}rate_limit.py`, `${B}crypto.py`, `${B}segredos.py`, `${B}cache.py`,
  `${B}timezone.py`, `${B}worker.py`, `${B}cobranca_regras.py`, `${B}regras_db.py`, `${B}routers/auth.py`,
  `${B}__init__.py`, `${B}routers/__init__.py`, `${B}utils/__init__.py`, `${B}services/__init__.py`,
  "apps/backend/requirements.txt", "apps/backend/alembic/**", "apps/backend/alembic.ini",
  "e2e/ambiente/**", "e2e/tests/fixtures.ts", "e2e/tests/ambiente.ts", "e2e/tests/auth.setup.ts",
  "e2e/tests/dados/**", "e2e/playwright.config.ts", "e2e/package*.json", "e2e/selecionar-telas.mjs",
  "package.json", "package-lock.json", ".github/workflows/testes.yml",
];

// Tela → pré-requisitos (diretos) e arquivos que ela testa. Conferido no CI pelo
// workflow e2e-mapa.yml: cada spec passa rodando só com os seus pré-requisitos.
const TELAS = {
  "01-login": { depende: [], arquivos: [`${F}pages/Login.tsx`] },
  "02-conexoes": {
    depende: [],
    arquivos: [
      `${F}pages/Configuracoes.tsx`, `${F}components/config/TokensMetaCard.tsx`, `${F}components/config/NumerosCard.tsx`,
      `${B}routers/meta_tokens.py`, `${B}routers/numbers.py`, `${B}routers/chatwoot.py`, `${B}routers/google.py`,
      `${B}routers/seta.py`, `${B}meta_client.py`, `${B}chatwoot_client.py`, `${B}google_client.py`,
    ],
  },
  "03-templates": {
    depende: ["02-conexoes"],
    arquivos: [
      `${F}pages/Configuracoes.tsx`, `${F}components/config/TemplatesCard.tsx`, `${B}routers/templates.py`,
      `${B}utils/imagem.py`, `${B}variaveis_template.py`, `${B}meta_client.py`,
    ],
  },
  "04-faixas": {
    depende: ["02-conexoes", "03-templates"],
    arquivos: [
      `${F}pages/Configuracoes.tsx`, `${F}pages/Faixas.tsx`, `${F}pages/FaixaWizard.tsx`, `${F}pages/FaixaDetail.tsx`,
      `${F}components/EnviosFaixa.tsx`, `${B}routers/faixas.py`, `${B}variaveis_template.py`,
    ],
  },
  "05-horario": {
    depende: ["04-faixas"],
    arquivos: [`${F}pages/Configuracoes.tsx`, `${F}components/config/DisparoCard.tsx`, `${B}routers/config_cobranca.py`, `${B}routers/faixas.py`],
  },
  "06-indicadores": {
    depende: [],
    arquivos: [
      `${F}pages/Configuracoes.tsx`, `${F}components/config/RegrasCobrancaCard.tsx`, `${F}components/config/JurosMultaCard.tsx`,
      `${F}components/config/OrcamentoCard.tsx`, `${F}components/MatrizTable.tsx`, `${B}routers/config_cobranca.py`,
    ],
  },
  "07-blacklist": {
    depende: [],
    arquivos: [`${F}pages/Configuracoes.tsx`, `${F}components/config/BlacklistCard.tsx`, `${B}routers/blacklist.py`, `${B}blacklist.py`, `${B}utils/document.py`],
  },
  "08-usuarios": {
    depende: [],
    arquivos: [`${F}pages/Configuracoes.tsx`, `${F}components/config/UsuariosCard.tsx`, `${B}routers/users.py`],
  },
  "09-cobranca": {
    // "Enviar para fila" precisa das faixas (04) com disparo configurado (05); as
    // contagens esperadas contam com as regras (06) e a blacklist (07) da suíte
    depende: ["04-faixas", "05-horario", "06-indicadores", "07-blacklist"],
    arquivos: [
      `${F}pages/Cobranca.tsx`, `${F}components/BarraFiltrosCobranca.tsx`, `${F}components/CampoValorMaximo.tsx`,
      `${F}components/CamposLoja.tsx`, `${F}components/MultiSelect.tsx`, `${F}components/useOpcoesCobranca.ts`,
      `${F}components/MatrizTable.tsx`, `${F}components/SortableTh.tsx`, `${F}components/Paginacao.tsx`,
      `${B}routers/cobranca.py`, `${B}routers/comum.py`, `${B}routers/leads.py`, `${B}cobranca_base.py`,
      `${B}cobranca_relatorio.py`, `${B}leads_service.py`, `${B}seta_client.py`, `${B}blacklist.py`, `${B}elegibilidade.py`,
      `${B}lojas.py`, `${B}lojas_iniciais.py`, `${B}services/compras_seta.py`, `${B}utils/spc.py`, `${B}utils/phone.py`,
      `${B}utils/leads_xlsx.py`, `${B}utils/xlsx.py`,
    ],
  },
  "10-importacao-e-fila": {
    depende: ["02-conexoes", "03-templates", "04-faixas"],
    arquivos: [
      `${F}pages/Cobranca.tsx`, `${F}components/UploadPlanilhaFaixa.tsx`, `${F}pages/FaixaDetail.tsx`,
      `${B}routers/uploads.py`, `${B}upload_service.py`, `${B}itens_fila.py`, `${B}fila_automatica.py`,
      `${B}elegibilidade.py`, `${B}blacklist.py`, `${B}pausas.py`, `${B}variaveis_template.py`, `${B}seta_client.py`,
      `${B}utils/spreadsheet.py`, `${B}utils/document.py`, `${B}utils/phone.py`, `${B}utils/leads_xlsx.py`,
      `${B}utils/valor.py`, `${B}routers/leads.py`, `${B}leads_service.py`,
    ],
  },
  "11-disparo": {
    // a fila da faixa 3 A 10 é enchida pelo "Enviar para fila" da Cobrança (09)
    depende: ["02-conexoes", "03-templates", "04-faixas", "05-horario", "09-cobranca", "10-importacao-e-fila"],
    arquivos: [
      `${F}pages/FaixaDetail.tsx`, `${F}components/EnviosFaixa.tsx`, `${B}dispatch_service.py`, `${B}elegibilidade.py`,
      `${B}fila_automatica.py`, `${B}pausas.py`, `${B}meta_client.py`, `${B}chatwoot_client.py`, `${B}routers/faixas.py`,
      `${B}campanhas_fixas.py`, `${B}itens_fila.py`, `${B}variaveis_template.py`, `${B}upload_service.py`,
    ],
  },
  "12-dashboard": {
    depende: ["11-disparo"],
    arquivos: [
      `${F}pages/Dashboard.tsx`, `${F}components/dashboard/**`, `${F}components/DicaIndicador.tsx`,
      `${F}components/useAtualizacaoAutomatica.ts`, `${F}components/FiltroPeriodo.tsx`, `${F}components/SelectCampanha.tsx`,
      `${F}components/MatrizTable.tsx`, `${B}routers/dashboard.py`, `${B}routers/leads.py`, `${B}routers/cobranca.py`,
      `${B}consultas_fila.py`, `${B}services/**`, `${B}cambio.py`, `${B}relatorio_efetividade.py`, `${B}cobranca_relatorio.py`,
      `${B}utils/xlsx.py`, `${B}utils/leads_xlsx.py`,
    ],
  },
  "13-relatorios": {
    depende: ["11-disparo"],
    arquivos: [
      `${F}pages/Relatorios.tsx`, `${F}components/FiltroPeriodo.tsx`, `${F}components/Paginacao.tsx`,
      `${F}components/SortableTh.tsx`, `${F}components/SelectCampanha.tsx`, `${B}routers/reports.py`,
      `${B}consultas_fila.py`, `${B}services/**`, `${B}relatorio_efetividade.py`, `${B}utils/xlsx.py`,
    ],
  },
  "14-erros-e-sincronia": {
    depende: ["12-dashboard", "13-relatorios"],
    arquivos: [
      `${F}pages/Dashboard.tsx`, `${F}components/dashboard/**`, `${F}components/useAtualizacaoAutomatica.ts`,
      `${B}routers/dashboard.py`, `${B}services/**`, `${B}cambio.py`,
    ],
  },
  "15-lojas": {
    depende: [],
    arquivos: [
      `${F}pages/Configuracoes.tsx`, `${F}components/config/LojasCard.tsx`, `${B}routers/lojas.py`, `${B}lojas.py`,
      `${B}lojas_iniciais.py`, `${B}google_client.py`, `${B}routers/google.py`,
    ],
  },
  "16-remarketing": {
    // Configurações → Faixas precisa ter faixas de atraso (sincronizadas no 04)
    depende: ["04-faixas"],
    arquivos: [
      `${F}pages/Configuracoes.tsx`, `${F}pages/Campanhas.tsx`, `${F}components/config/RemarketingCard.tsx`,
      `${F}components/config/RenegocieConexaoCard.tsx`, `${B}routers/remarketing.py`, `${B}remarketing.py`,
      `${B}campanhas_fixas.py`, `${B}cobranca_base.py`, `${B}fila_automatica.py`, `${B}elegibilidade.py`,
      `${B}leads_service.py`, `${B}seta_client.py`,
    ],
  },
  "17-pausas": {
    depende: ["11-disparo"],
    arquivos: [
      `${F}pages/Relatorios.tsx`, `${F}components/PausasPendentes.tsx`, `${B}routers/pausas.py`, `${B}pausas.py`,
      `${B}routers/reports.py`, `${B}fila_automatica.py`, `${B}consultas_fila.py`,
    ],
  },
  "18-campanhas": {
    depende: ["04-faixas"],
    arquivos: [
      `${F}pages/Campanhas.tsx`, `${F}pages/CampanhaDetail.tsx`, `${F}components/BarraFiltrosCobranca.tsx`,
      `${F}components/CamposLoja.tsx`, `${F}components/CampoValorMaximo.tsx`, `${F}components/SelectCampanha.tsx`,
      `${F}components/EnviosFaixa.tsx`, `${B}routers/campanhas.py`, `${B}campanhas.py`, `${B}campanhas_fixas.py`,
      `${B}cobranca_base.py`, `${B}fila_automatica.py`, `${B}elegibilidade.py`, `${B}pausas.py`, `${B}routers/lojas.py`,
      `${B}lojas.py`, `${B}leads_service.py`, `${B}routers/comum.py`, `${B}routers/pausas.py`, `${B}seta_client.py`,
      `${B}utils/valor.py`,
      `${B}routers/dashboard.py`, `${B}routers/reports.py`,
    ],
  },
};

// Fora de apps/ e e2e/ (docs, testes do backend, outros workflows) não afeta tela.
const AFETA_TELA = [`${F}**`, `${B}**`, "apps/frontend/**", "e2e/**"];

function comoRegex(glob) {
  const re = glob
    .replace(/[.+^${}()|[\]\\]/g, "\\$&")
    .replace(/\*\*/g, "\u0000")
    .replace(/\*/g, "[^/]*")
    .replace(/\u0000/g, ".*");
  return new RegExp(`^${re}$`);
}
const bate = (arquivo, globs) => globs.some((g) => comoRegex(g).test(arquivo));

function comPreRequisitos(specs) {
  const todos = new Set();
  const visitar = (s) => {
    if (todos.has(s)) return;
    if (!TELAS[s]) throw new Error(`spec desconhecido no mapa: ${s}`);
    todos.add(s);
    TELAS[s].depende.forEach(visitar);
  };
  specs.forEach(visitar);
  return [...todos].sort();
}

export function selecionar(alterados) {
  const specs = new Set();
  for (const arquivo of alterados.map((a) => a.trim()).filter(Boolean)) {
    if (bate(arquivo, GLOBAIS)) return "todos";
    const spec = /^e2e\/tests\/(\d\d-[^/]+)\.spec\.ts$/.exec(arquivo);
    if (spec) {
      if (!TELAS[spec[1]]) return "todos"; // spec novo ainda fora do mapa
      specs.add(spec[1]);
      continue;
    }
    if (!bate(arquivo, AFETA_TELA)) continue;
    const telas = Object.entries(TELAS).filter(([, t]) => bate(arquivo, t.arquivos)).map(([s]) => s);
    if (telas.length === 0) {
      // arquivo de código do app que nenhuma tela declara: na dúvida, tudo
      if (arquivo.startsWith(F) || arquivo.startsWith(B)) return "todos";
      continue;
    }
    telas.forEach((s) => specs.add(s));
  }
  if (specs.size === 0) return "nenhum";
  return comPreRequisitos([...specs]).map((s) => `tests/${s}.spec.ts`).join(" ");
}

if (process.argv[1] && import.meta.url === `file://${process.argv[1]}`) {
  const [, , opcao, valor] = process.argv;
  if (opcao === "--spec") {
    console.log(comPreRequisitos([valor]).map((s) => `tests/${s}.spec.ts`).join(" "));
  } else if (opcao === "--listar") {
    console.log(Object.keys(TELAS).join(" "));
  } else {
    console.log(selecionar(fs.readFileSync(opcao, "utf8").split("\n")));
  }
}
