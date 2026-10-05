// Testes do seletor de cenários e2e: node --test e2e/selecionar-telas.test.mjs
import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";
import test from "node:test";
import { fileURLToPath } from "node:url";
import { CONTRATOS, FUMACA, FUNCIONALIDADES, GLOBAIS, VISUAIS, listarSpecs, selecionar } from "./selecionar-telas.mjs";

const AQUI = path.dirname(fileURLToPath(import.meta.url));
const RAIZ = path.join(AQUI, "..");
const F = "apps/frontend/src/";
const B = "apps/backend/app/";

const sel = (...arquivos) => selecionar(arquivos);
const aplicar = (g, arquivo) => new RegExp(g).test(arquivo);
const roda = (r, tag) => r.modo === "todos" || r.tags.includes(tag);

function arquivosDe(dir, extensoes) {
  const saida = [];
  const visitar = (d) => {
    for (const e of fs.readdirSync(path.join(RAIZ, d), { withFileTypes: true })) {
      if (e.name === "__pycache__" || e.name === "node_modules") continue;
      const rel = `${d}/${e.name}`;
      if (e.isDirectory()) visitar(rel);
      else if (extensoes.some((x) => e.name.endsWith(x))) saida.push(rel);
    }
  };
  visitar(dir);
  return saida;
}

// ---- guardas do mapa ----

test("todo arquivo do app tem classe no mapa (senão a suíte inteira roda por engano)", () => {
  const arquivos = [...arquivosDe("apps/frontend/src", [".ts", ".tsx", ".css"]), ...arquivosDe("apps/backend/app", [".py"])];
  const sem = arquivos.filter((a) => {
    const r = sel(a);
    return r.modo === "todos" && !/global|contratos/.test(r.motivos.join());
  });
  assert.deepEqual(sem, [], "declarar em FUNCIONALIDADES, CONTRATOS, VISUAIS ou GLOBAIS");
});

test("arquivos citados no mapa existem (renomear sem atualizar o mapa quebra a seleção)", () => {
  const citados = new Set(Object.values(FUNCIONALIDADES).flat());
  const faltam = [...citados].filter((g) => !g.includes("*") && !fs.existsSync(path.join(RAIZ, g)));
  assert.deepEqual(faltam, []);
});

test("as tags do mapa são as dos specs, e todo spec e cenário tem tag", () => {
  const nosSpecs = new Set();
  for (const s of listarSpecs()) {
    const texto = fs.readFileSync(path.join(AQUI, "tests", `${s}.spec.ts`), "utf8");
    const usadas = [...texto.matchAll(/"@([\w-]+)"/g)].map((m) => m[1]);
    assert.ok(usadas.length > 0, `${s} sem tag`);
    // todo test() fica dentro de um describe com tag
    assert.match(texto, /test\.describe(\.serial)?\([^\n]*\{ tag: /, `${s}: o describe principal precisa de tag`);
    usadas.forEach((t) => nosSpecs.add(t));
  }
  const nomes = new Set([...Object.keys(FUNCIONALIDADES), FUMACA]);
  assert.deepEqual([...nosSpecs].filter((t) => !nomes.has(t)).sort(), [], "tag usada no spec e ausente do mapa");
  assert.deepEqual([...nomes].filter((t) => !nosSpecs.has(t)).sort(), [], "tag do mapa que nenhum cenário usa");
});

// ---- comportamento ----

test("arquivo desconhecido do app → suíte inteira", () => {
  assert.equal(sel(`${B}modulo_novo.py`).modo, "todos");
  assert.equal(sel(`${F}components/NovoComponente.tsx`).modo, "todos");
});

test("fora do app e do e2e (docs, testes do backend, outros workflows) → nenhum", () => {
  assert.equal(sel("README.md", "apps/backend/tests/test_regras.py", ".github/workflows/deploy.yml", "docs/x.png").modo, "nenhum");
  assert.equal(sel().modo, "nenhum");
});

test("globais → suíte inteira", () => {
  for (const g of [`${B}main.py`, `${F}App.tsx`, `${B}timezone.py`, "e2e/tests/fixtures.ts", "e2e/ambiente/servidor_teste.py", "apps/backend/alembic/versions/x.py"]) {
    assert.equal(sel(g).modo, "todos", g);
  }
});

test("só contrato → suíte inteira; contrato com funcionalidade → a funcionalidade e a fumaça", () => {
  assert.equal(sel(`${F}api.ts`).modo, "todos");
  assert.equal(sel(`${B}schemas.py`).modo, "todos");
  const r = sel(`${F}api.ts`, `${B}services/custo_whatsapp.py`);
  assert.equal(r.modo, "parcial");
  assert.deepEqual(r.tags, ["efetividade", "orcamento", "smoke"]);
});

test("estilos → só os cenários visuais e a fumaça", () => {
  const r = sel(`${F}styles.css`);
  assert.deepEqual(r.tags, ["smoke", "visual"]);
  assert.deepEqual(r.specs, []);
});

test("mudança no CI ou no seletor → só a fumaça", () => {
  assert.deepEqual(sel("e2e/selecionar-telas.mjs").tags, ["smoke"]);
  assert.deepEqual(sel(".github/workflows/testes.yml").tags, ["smoke"]);
});

test("spec alterado roda inteiro, sem a fumaça e sem outras telas", () => {
  const r = sel("e2e/tests/12-dashboard.spec.ts");
  assert.equal(r.modo, "parcial");
  assert.deepEqual(r.specs, ["12-dashboard"]);
  assert.deepEqual(r.tags, []);
  assert.ok(aplicar(r.grep, "[chromium] › 12-dashboard.spec.ts:13:3 › Dashboard › qualquer"));
  assert.ok(!aplicar(r.grep, "[chromium] › 13-relatorios.spec.ts:13:3 › Relatórios › qualquer @relatorios"));
});

test("helper de preparo alterado roda os specs que o importam", () => {
  const r = sel("e2e/tests/preparo.ts");
  assert.ok(r.specs.includes("12-dashboard") && r.specs.includes("13-relatorios"));
  assert.ok(!r.specs.includes("01-login") && !r.specs.includes("15-lojas"));
});

test("spec novo sem mapa roda por nome", () => {
  assert.deepEqual(sel("e2e/tests/99-novo.spec.ts").specs, ["99-novo"]);
});

// serviços um a um: não puxam funcionalidades sem relação
const SERVICOS = {
  [`${B}services/efetividade_service.py`]: { liga: ["efetividade", "leads"], nao: ["cobranca", "orcamento", "disparo", "pagos-janela", "dashboard"] },
  [`${B}services/pagamentos_seta.py`]: { liga: ["pagamentos", "efetividade"], nao: ["cobranca", "orcamento", "disparo", "relatorios"] },
  [`${B}services/pagos_janela_service.py`]: { liga: ["pagos-janela"], nao: ["pagamentos", "efetividade", "orcamento", "cobranca", "relatorios"] },
  [`${B}services/custo_whatsapp.py`]: { liga: ["orcamento", "efetividade"], nao: ["pagamentos", "cobranca", "relatorios", "disparo"] },
  [`${B}services/compras_seta.py`]: { liga: ["cobranca", "remarketing", "campanhas"], nao: ["dashboard", "pagamentos", "efetividade", "orcamento", "relatorios"] },
  [`${B}cache.py`]: { liga: ["pagamentos", "efetividade", "cobranca", "campanhas"], nao: ["orcamento", "disparo", "login", "usuarios"] },
};
for (const [arquivo, { liga, nao }] of Object.entries(SERVICOS)) {
  test(`${arquivo.replace(B, "")} liga só o que usa`, () => {
    const r = sel(arquivo);
    assert.equal(r.modo, "parcial");
    for (const t of liga) assert.ok(r.tags.includes(t), `deveria ligar @${t}`);
    for (const t of nao) assert.ok(!roda(r, t), `não deveria ligar @${t}`);
    assert.ok(r.tags.includes("smoke"));
  });
}

test("prévia do WhatsApp liga as telas que mostram template, não as outras", () => {
  const r = sel(`${F}components/PreviaWhatsapp.tsx`);
  for (const t of ["templates", "faixas", "fila", "disparo"]) assert.ok(r.tags.includes(t), t);
  for (const t of ["cobranca", "dashboard", "relatorios"]) assert.ok(!r.tags.includes(t), t);
});

test("seta_client.py liga o que consulta o SETA, não o resto", () => {
  const r = sel(`${B}seta_client.py`);
  for (const t of ["cobranca", "pagamentos", "efetividade", "remarketing", "campanhas", "importacao"]) assert.ok(r.tags.includes(t), t);
  for (const t of ["orcamento", "usuarios", "login", "blacklist", "templates", "horario"]) assert.ok(!r.tags.includes(t), t);
});

test("12-dashboard e 13-relatorios: cada página liga a sua tela, não a outra", () => {
  const dash = sel(`${F}pages/Dashboard.tsx`);
  assert.ok(dash.tags.includes("dashboard") && !dash.tags.includes("relatorios"));
  const rel = sel(`${F}pages/Relatorios.tsx`);
  assert.ok(rel.tags.includes("relatorios") && !rel.tags.includes("dashboard"));
});

test("o grep escolhe as tags certas e não confunde prefixos", () => {
  const { grep } = sel(`${B}services/pagos_janela_service.py`);
  assert.ok(aplicar(grep, "Dashboard › card x @pagos-janela @pagamentos"));
  assert.ok(!aplicar(grep, "Relatórios › quem pagou @relatorios @pagamentos"));
  assert.ok(aplicar(grep, "Fumaça › Dashboard @smoke"));
});

test("a saída traz o motivo de cada arquivo", () => {
  const r = sel(`${B}services/custo_whatsapp.py`, "README.md");
  assert.equal(r.motivos.length, 1);
  assert.match(r.motivos[0], /custo_whatsapp\.py: @efetividade @orcamento/);
});

test("as classes não se repetem: um arquivo não é global e contrato ao mesmo tempo", () => {
  const dup = GLOBAIS.filter((g) => CONTRATOS.includes(g) || VISUAIS.includes(g));
  assert.deepEqual(dup, []);
});
