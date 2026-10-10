// Escolhe quais cenários e2e rodar num PR, pelos arquivos alterados.
//
// Cada cenário carrega tags de funcionalidade (@cobranca, @pagamentos, @orcamento…
// ver e2e/README.md). O mapa abaixo diz, para cada tag, quais arquivos do app mudam
// o comportamento que ela verifica. Um arquivo alterado liga as tags dele, o spec
// alterado roda inteiro e, quando mudou código do app, a fumaça (@smoke) vai junto.
//
// Classes de arquivo:
//   global     (GLOBAIS)      muda tudo (rotas, segurança, ambiente de teste) → suíte inteira
//   contrato   (CONTRATOS)    tipos e acesso à API usados por todas as telas → suíte inteira,
//                             a não ser que a mesma mudança aponte funcionalidades específicas
//   visual     (VISUAIS)      estilos, ícones, públicos → só @visual (+ fumaça)
//   funcional  (FUNCIONALIDADES) o resto do app: cada arquivo liga as tags que o usam
//   ci         (CI)           workflows e o próprio seletor → só a fumaça
// Arquivo de código do app que nenhuma classe declara → suíte inteira (na dúvida, testa tudo).
// Fora do app e do e2e (docs, testes do backend, outros workflows) não roda e2e.
//
//   node selecionar-telas.mjs <arquivo com a lista de alterados, um por linha>
//     imprime JSON { modo: "todos"|"nenhum"|"parcial", grep, tags, specs, motivos }
//   node selecionar-telas.mjs --listar-specs | --listar-tags

import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

const F = "apps/frontend/src/";
const B = "apps/backend/app/";
const AQUI = path.dirname(fileURLToPath(import.meta.url));

// Mudou algum destes: o impacto não se limita a uma funcionalidade.
export const GLOBAIS = [
  `${F}App.tsx`, `${F}main.tsx`, "apps/frontend/index.html", "apps/frontend/vite.config.*",
  "apps/frontend/tsconfig*.json", "apps/frontend/package*.json",
  `${B}main.py`, `${B}config.py`, `${B}database.py`, `${B}deps.py`,
  `${B}security.py`, `${B}rate_limit.py`, `${B}crypto.py`, `${B}segredos.py`,
  `${B}timezone.py`, `${B}worker.py`, `${B}routers/auth.py`,
  "apps/backend/requirements.txt", "apps/backend/alembic/**", "apps/backend/alembic.ini",
  "e2e/ambiente/**", "e2e/tests/fixtures.ts", "e2e/tests/ambiente.ts", "e2e/tests/auth.setup.ts",
  "e2e/playwright.config.ts", "e2e/package*.json",
  "package.json", "package-lock.json",
];

// Contratos: formatos de dados e funções de acesso que as telas compartilham.
export const CONTRATOS = [
  `${F}api.ts`, `${F}format.ts`, `${F}sort.ts`, `${F}vite-env.d.ts`,
  `${B}schemas.py`, `${B}models.py`, `${B}cobranca_regras.py`, `${B}regras_db.py`,
  `${B}__init__.py`, `${B}routers/__init__.py`, `${B}utils/__init__.py`, `${B}services/__init__.py`,
  `${B}utils/erros.py`,
];

export const VISUAIS = [`${F}styles.css`, `${F}icons.tsx`, `${F}public/**`];

// Muda o jeito de rodar os testes, não o app: basta ver que a fumaça ainda passa.
export const CI = [".github/workflows/testes.yml", ".github/workflows/e2e-mapa.yml", "e2e/selecionar-telas.mjs", "e2e/selecionar-telas.test.mjs"];

// Funcionalidade (tag) → arquivos que mudam o que os cenários dela verificam.
export const FUNCIONALIDADES = {
  login: [`${F}pages/Login.tsx`],
  conexoes: [
    `${F}pages/Configuracoes.tsx`, `${F}components/config/TokensMetaCard.tsx`, `${F}components/config/NumerosCard.tsx`,
    `${B}routers/meta_tokens.py`, `${B}routers/numbers.py`, `${B}routers/chatwoot.py`, `${B}routers/google.py`,
    `${B}routers/seta.py`, `${B}meta_client.py`, `${B}chatwoot_client.py`, `${B}google_client.py`,
  ],
  templates: [
    `${F}pages/Configuracoes.tsx`, `${F}components/config/TemplatesCard.tsx`, `${F}components/PreviaWhatsapp.tsx`, `${B}routers/templates.py`,
    `${B}utils/imagem.py`, `${B}variaveis_template.py`, `${B}meta_client.py`,
    `${F}components/AvisosCategoria.tsx`,
  ],
  faixas: [
    `${F}pages/Configuracoes.tsx`, `${F}pages/Faixas.tsx`, `${F}pages/FaixaWizard.tsx`, `${F}pages/FaixaDetail.tsx`,
    `${F}components/EnviosFaixa.tsx`, `${F}components/PreviaWhatsapp.tsx`, `${B}routers/faixas.py`, `${B}variaveis_template.py`,
  ],
  horario: [`${F}pages/Configuracoes.tsx`, `${F}components/config/DisparoCard.tsx`, `${B}routers/config_cobranca.py`, `${B}routers/faixas.py`],
  indicadores: [
    `${F}pages/Configuracoes.tsx`, `${F}components/config/RegrasCobrancaCard.tsx`, `${F}components/config/JurosMultaCard.tsx`,
    `${F}components/config/OrcamentoCard.tsx`, `${F}components/MatrizTable.tsx`, `${B}routers/config_cobranca.py`,
    `${F}components/config/JanelaPagamentoCard.tsx`, `${F}components/SelectJanelaPagamento.tsx`,
  ],
  blacklist: [`${F}pages/Configuracoes.tsx`, `${F}components/config/BlacklistCard.tsx`, `${B}routers/blacklist.py`, `${B}blacklist.py`, `${B}utils/document.py`],
  usuarios: [`${F}pages/Configuracoes.tsx`, `${F}components/config/UsuariosCard.tsx`, `${B}routers/users.py`],
  lojas: [
    `${F}pages/Configuracoes.tsx`, `${F}components/config/LojasCard.tsx`, `${B}routers/lojas.py`, `${B}lojas.py`,
    `${B}lojas_iniciais.py`, `${B}google_client.py`, `${B}routers/google.py`,
  ],
  cobranca: [
    `${F}pages/Cobranca.tsx`, `${F}components/BarraFiltrosCobranca.tsx`, `${F}components/CampoValorMaximo.tsx`,
    `${F}components/CamposLoja.tsx`, `${F}components/MultiSelect.tsx`, `${F}components/useOpcoesCobranca.ts`,
    `${F}components/useRequisicaoUnica.ts`, `${F}components/dashboard/MatrizCobrancaCard.tsx`,
    `${F}components/MatrizTable.tsx`, `${F}components/SortableTh.tsx`, `${F}components/Paginacao.tsx`,
    `${B}routers/cobranca.py`, `${B}routers/comum.py`, `${B}routers/leads.py`, `${B}cobranca_base.py`,
    `${B}cobranca_relatorio.py`, `${B}leads_service.py`, `${B}seta_client.py`, `${B}blacklist.py`, `${B}elegibilidade.py`,
    `${B}lojas.py`, `${B}lojas_iniciais.py`, `${B}google_client.py`, `${B}cache.py`, `${B}services/compras_seta.py`,
    `${B}utils/spc.py`, `${B}utils/phone.py`, `${B}utils/leads_xlsx.py`, `${B}utils/xlsx.py`,
  ],
  importacao: [
    `${F}pages/Cobranca.tsx`, `${F}components/UploadPlanilhaFaixa.tsx`, `${F}pages/FaixaDetail.tsx`,
    `${B}routers/uploads.py`, `${B}upload_service.py`, `${B}itens_fila.py`, `${B}fila_automatica.py`,
    `${B}elegibilidade.py`, `${B}blacklist.py`, `${B}pausas.py`, `${B}variaveis_template.py`, `${B}seta_client.py`,
    `${B}telefones_invalidos.py`, `${B}utils/spreadsheet.py`, `${B}utils/document.py`, `${B}utils/phone.py`,
    `${B}utils/leads_xlsx.py`, `${B}utils/valor.py`, `${B}routers/leads.py`, `${B}leads_service.py`,
  ],
  fila: [
    `${F}pages/FaixaDetail.tsx`, `${F}components/EnviosFaixa.tsx`, `${F}components/PreviaWhatsapp.tsx`, `${B}routers/faixas.py`, `${B}itens_fila.py`,
    `${B}consultas_fila.py`, `${B}fila_automatica.py`,
  ],
  disparo: [
    `${F}pages/FaixaDetail.tsx`, `${F}components/EnviosFaixa.tsx`, `${F}components/PreviaWhatsapp.tsx`, `${B}dispatch_service.py`, `${B}elegibilidade.py`,
    `${B}fila_automatica.py`, `${B}pausas.py`, `${B}meta_client.py`, `${B}chatwoot_client.py`, `${B}routers/faixas.py`,
    `${B}campanhas_fixas.py`, `${B}itens_fila.py`, `${B}variaveis_template.py`, `${B}upload_service.py`,
    `${B}telefones_invalidos.py`,
  ],
  dashboard: [
    `${F}pages/Dashboard.tsx`, `${F}components/dashboard/MatrizCobrancaCard.tsx`, `${F}components/DicaIndicador.tsx`,
    `${F}components/TabelaAjustavel.tsx`, `${F}components/useAtualizacaoAutomatica.ts`, `${F}components/useRequisicaoUnica.ts`,
    `${F}components/FiltroPeriodo.tsx`, `${F}components/SelectCampanha.tsx`, `${F}components/MatrizTable.tsx`,
    `${F}components/usePainelTempoReal.ts`, `${B}painel_tempo_real.py`,
    `${B}routers/dashboard.py`, `${B}consultas_fila.py`, `${B}cobranca_relatorio.py`,
  ],
  relatorios: [
    `${F}pages/Relatorios.tsx`, `${F}components/FiltroPeriodo.tsx`, `${F}components/Paginacao.tsx`, `${F}components/useRequisicaoUnica.ts`,
    `${F}components/SortableTh.tsx`, `${F}components/SelectCampanha.tsx`, `${B}routers/reports.py`,
    `${B}consultas_fila.py`, `${B}utils/xlsx.py`,
  ],
  resiliencia: [
    `${F}components/AvisoSetaFora.tsx`, `${F}components/useAtualizacaoAutomatica.ts`, `${F}components/useRequisicaoUnica.ts`, `${F}pages/Dashboard.tsx`,
    `${F}components/config/NumerosCard.tsx`, `${F}components/config/TokensMetaCard.tsx`,
    `${B}routers/dashboard.py`, `${B}routers/numbers.py`, `${B}routers/meta_tokens.py`,
  ],
  pausas: [
    `${F}pages/Relatorios.tsx`, `${F}components/PausasPendentes.tsx`, `${B}routers/pausas.py`, `${B}pausas.py`,
    `${B}routers/reports.py`, `${B}fila_automatica.py`, `${B}consultas_fila.py`, `${B}routers/lojas.py`,
  ],
  leads: [
    `${F}components/dashboard/LeadsCard.tsx`, `${B}routers/leads.py`, `${B}leads_service.py`, `${B}utils/leads_xlsx.py`,
    `${B}services/efetividade_service.py`, `${B}routers/cobranca.py`,
  ],
  elegibilidade: [
    `${B}elegibilidade.py`, `${B}fila_automatica.py`, `${B}itens_fila.py`, `${B}dispatch_service.py`, `${B}pausas.py`,
    `${B}blacklist.py`,
  ],
  remarketing: [
    `${F}pages/Configuracoes.tsx`, `${F}pages/Campanhas.tsx`, `${F}components/config/RemarketingCard.tsx`,
    `${F}components/config/RenegocieConexaoCard.tsx`, `${B}routers/remarketing.py`, `${B}remarketing.py`,
    `${B}campanhas_fixas.py`, `${B}cobranca_base.py`, `${B}fila_automatica.py`, `${B}elegibilidade.py`,
    `${B}leads_service.py`, `${B}seta_client.py`, `${B}services/compras_seta.py`,
  ],
  campanhas: [
    `${F}pages/Campanhas.tsx`, `${F}pages/CampanhaDetail.tsx`, `${F}components/BarraFiltrosCobranca.tsx`, `${F}components/useRequisicaoUnica.ts`,
    `${F}components/CamposLoja.tsx`, `${F}components/CampoValorMaximo.tsx`, `${F}components/SelectCampanha.tsx`,
    `${F}components/EnviosFaixa.tsx`, `${F}components/PreviaWhatsapp.tsx`, `${F}components/ModalDecisaoVariaveis.tsx`, `${B}routers/campanhas.py`, `${B}campanhas.py`, `${B}campanhas_fixas.py`,
    `${B}cobranca_base.py`, `${B}fila_automatica.py`, `${B}elegibilidade.py`, `${B}pausas.py`, `${B}routers/lojas.py`,
    `${B}lojas.py`, `${B}leads_service.py`, `${B}routers/comum.py`, `${B}routers/pausas.py`, `${B}seta_client.py`,
    `${B}cache.py`, `${B}services/compras_seta.py`, `${B}utils/valor.py`, `${B}routers/dashboard.py`, `${B}routers/reports.py`,
  ],
  // Cálculos de dinheiro e pagamento: os números em si são conferidos nos testes do
  // backend; aqui só o que aparece na tela (cards, abas, exportação, estados de erro).
  pagamentos: [
    `${B}services/pagamentos_service.py`, `${B}services/pagamentos_seta.py`, `${B}seta_client.py`, `${B}cache.py`,
    `${B}consultas_fila.py`, `${B}routers/reports.py`, `${B}routers/dashboard.py`, `${B}lojas.py`, `${B}google_client.py`,
    `${F}components/SelectJanelaPagamento.tsx`,
  ],
  "pagos-janela": [
    `${B}services/pagos_janela_service.py`, `${B}services/pagamentos_service.py`, `${B}routers/dashboard.py`,
    `${B}routers/config_cobranca.py`, `${F}components/SelectJanelaPagamento.tsx`,
  ],
  efetividade: [
    `${F}components/dashboard/EfetividadeCard.tsx`, `${F}components/SelectJanelaPagamento.tsx`, `${B}services/efetividade_service.py`, `${B}services/pagamentos_seta.py`,
    `${B}services/custo_whatsapp.py`, `${B}relatorio_efetividade.py`, `${B}cambio.py`, `${B}cache.py`, `${B}seta_client.py`,
    `${B}campanhas_fixas.py`, `${B}lojas.py`, `${B}google_client.py`, `${B}routers/reports.py`,
  ],
  orcamento: [
    `${F}components/dashboard/OrcamentoProgressaoCard.tsx`, `${B}services/custo_whatsapp.py`, `${B}cambio.py`,
    `${B}routers/dashboard.py`, `${B}meta_client.py`,
  ],
  visual: [
    `${F}components/TabelaAjustavel.tsx`, `${F}components/DicaIndicador.tsx`, `${F}pages/Dashboard.tsx`,
    `${F}components/FiltroPeriodo.tsx`, `${F}components/MatrizTable.tsx`,
  ],
};

// Subconjunto de FUNCIONALIDADES que roda junto de qualquer mudança em código do app.
export const FUMACA = "smoke";

// Só estes diretórios têm código que o e2e exercita.
const AFETA_E2E = [`${F}**`, `${B}**`, "apps/frontend/**", "apps/backend/requirements.txt", "apps/backend/alembic/**", "e2e/**",
  "package.json", "package-lock.json", ".github/workflows/testes.yml", ".github/workflows/e2e-mapa.yml"];

function comoRegex(glob) {
  const re = glob
    .replace(/[.+^${}()|[\]\\]/g, "\\$&")
    .replace(/\*\*/g, "\u0000")
    .replace(/\*/g, "[^/]*")
    .replace(/\u0000/g, ".*");
  return new RegExp(`^${re}$`);
}
const bate = (arquivo, globs) => globs.some((g) => comoRegex(g).test(arquivo));

const tagsDoArquivo = (arquivo) =>
  Object.entries(FUNCIONALIDADES).filter(([, arquivos]) => bate(arquivo, arquivos)).map(([tag]) => tag);

const lerTexto = (rel) => {
  try {
    return fs.readFileSync(path.join(AQUI, rel), "utf8");
  } catch {
    return "";
  }
};
export const listarSpecs = () =>
  fs.readdirSync(path.join(AQUI, "tests")).filter((f) => f.endsWith(".spec.ts")).map((f) => f.replace(".spec.ts", "")).sort();

// Specs que usam um arquivo de apoio de e2e/tests (helper importado, planilha de dados):
// quem importa o helper, ou cita a planilha, direto ou por um helper.
function specsQueUsam(arquivo) {
  const specs = listarSpecs();
  const nome = path.basename(arquivo);
  const base = nome.replace(/\.(ts|tsx)$/, "");
  const importa = (spec, alvo) => new RegExp(`from "\\./${alvo}"`).test(lerTexto(`tests/${spec}.spec.ts`));
  if (arquivo.startsWith("e2e/tests/dados/")) {
    const helpers = fs.readdirSync(path.join(AQUI, "tests")).filter((f) => f.endsWith(".ts") && !f.endsWith(".spec.ts"))
      .map((f) => f.replace(".ts", "")).filter((h) => lerTexto(`tests/${h}.ts`).includes(nome));
    return specs.filter((s) => lerTexto(`tests/${s}.spec.ts`).includes(nome) || helpers.some((h) => importa(s, h)));
  }
  return specs.filter((s) => importa(s, base));
}

export function selecionar(alterados) {
  const tags = new Set();
  const specs = new Set();
  const motivos = [];
  let contrato = false;
  let codigoApp = false;
  let ci = false;
  const todos = (motivo) => ({ modo: "todos", grep: "", tags: [], specs: [], motivos: [motivo] });

  for (const arquivo of alterados.map((a) => a.trim()).filter(Boolean)) {
    if (!bate(arquivo, AFETA_E2E)) continue;
    if (bate(arquivo, CI)) {
      ci = true;
      motivos.push(`${arquivo}: só a fumaça`);
      continue;
    }
    if (bate(arquivo, GLOBAIS)) return todos(`${arquivo}: global`);

    const spec = /^e2e\/tests\/(\d\d-[^/]+)\.spec\.ts$/.exec(arquivo);
    if (spec) {
      specs.add(spec[1]);
      motivos.push(`${arquivo}: o próprio spec`);
      continue;
    }
    if (arquivo.startsWith("e2e/tests/")) {
      const usam = specsQueUsam(arquivo);
      if (usam.length === 0) return todos(`${arquivo}: apoio do e2e sem spec que o use`);
      usam.forEach((s) => specs.add(s));
      motivos.push(`${arquivo}: apoio usado por ${usam.length} spec(s)`);
      continue;
    }
    if (arquivo.startsWith("e2e/")) return todos(`${arquivo}: arquivo do e2e fora do mapa`);

    codigoApp = true;
    if (bate(arquivo, CONTRATOS)) {
      contrato = true;
      motivos.push(`${arquivo}: contrato`);
      continue;
    }
    if (bate(arquivo, VISUAIS)) {
      tags.add("visual");
      motivos.push(`${arquivo}: visual`);
      continue;
    }
    const doArquivo = tagsDoArquivo(arquivo);
    if (doArquivo.length === 0) return todos(`${arquivo}: arquivo do app fora do mapa`);
    doArquivo.forEach((t) => tags.add(t));
    motivos.push(`${arquivo}: ${doArquivo.map((t) => "@" + t).join(" ")}`);
  }

  // contrato sozinho não aponta funcionalidade: testa tudo. Com funcionalidades
  // específicas na mesma mudança, elas e a fumaça bastam (o backend tem testes próprios).
  if (contrato && tags.size === 0 && specs.size === 0) return todos("só contratos compartilhados mudaram");
  if (tags.size === 0 && specs.size === 0 && !ci) return { modo: "nenhum", grep: "", tags: [], specs: [], motivos };

  if (codigoApp || ci) tags.add(FUMACA);
  const partes = [...[...tags].sort().map((t) => `@${t}\\b`), ...[...specs].sort().map((s) => `${s}\\.spec`)];
  return { modo: "parcial", grep: partes.join("|"), tags: [...tags].sort(), specs: [...specs].sort(), motivos };
}

if (process.argv[1] && import.meta.url === `file://${process.argv[1]}`) {
  const [, , opcao] = process.argv;
  if (opcao === "--listar-specs") {
    console.log(listarSpecs().join(" "));
  } else if (opcao === "--listar-tags") {
    console.log([...Object.keys(FUNCIONALIDADES), FUMACA].join(" "));
  } else {
    console.log(JSON.stringify(selecionar(fs.readFileSync(opcao, "utf8").split("\n"))));
  }
}
