import { apiGet, baixar, campo, card, escolherMulti, expect, permitirErrosConsole, responderDialogo, test } from "./fixtures";
import type { Page } from "@playwright/test";

const titulo = (page: Page) => card(page, /^Clientes/).locator("h3");
const linhas = (page: Page) => card(page, /^Clientes/).locator("tbody tr");
const coluna = async (page: Page, i: number) => linhas(page).locator(`td:nth-child(${i})`).allInnerTexts();
const filtros = (page: Page) => card(page, "Filtros");

async function aplicar(page: Page) {
  await filtros(page).getByRole("button", { name: "Aplicar filtros" }).click();
  await expect(page.getByText("Consultando o SETA")).toHaveCount(0, { timeout: 30_000 });
}

async function semRegrasPadrao(page: Page) {
  await filtros(page).getByLabel("Somente o primeiro dia da faixa").uncheck();
  await filtros(page).getByLabel("Somente clientes da regra WhatsApp").uncheck();
}

test.describe("Cobrança: consulta de clientes no SETA", () => {
  test.beforeEach(async ({ page }) => {
    await page.goto("/cobranca");
  });

  test("antes de aplicar: estado vazio; filtros padrão ligados", async ({ page }) => {
    await expect(page.getByText("Aplique os filtros para listar clientes.")).toBeVisible();
    await expect(filtros(page).getByLabel("Somente o primeiro dia da faixa")).toBeChecked();
    await expect(filtros(page).getByLabel("Somente clientes da regra WhatsApp")).toBeChecked();
  });

  test("aplicar mostra carregamento, total e tabela com os filtros padrão", async ({ page }) => {
    await filtros(page).getByRole("button", { name: "Aplicar filtros" }).click();
    await expect(page.getByText("Consultando o SETA — isso pode levar até 45 segundos...")).toBeVisible();
    await expect(titulo(page)).toContainText(/\(\d+\)/, { timeout: 30_000 });
    const n = await linhas(page).count();
    expect(n).toBeGreaterThan(0);
    await expect(titulo(page)).toContainText(`(${n})`);
    await expect(card(page, /^Clientes/)).toContainText(`Mostrando 1–${n} de ${n}`);
    // só primeiro dia de faixa: atraso sempre é o primeiro dia de alguma faixa padrão
    const atrasos = await coluna(page, 7);
    const primeiros = ["vence amanhã", "2 dias", "3 dias", "11 dias", "21 dias", "31 dias", "41 dias", "61 dias", "81 dias", "101 dias", "121 dias", "141 dias", "151 dias"];
    for (const a of atrasos) expect(primeiros).toContain(a);
  });

  test("sem as regras padrão: todos os clientes, blacklist fora, paginação", async ({ page }) => {
    await semRegrasPadrao(page);
    await aplicar(page);
    await expect(titulo(page)).toContainText("(34)"); // 36 do SETA falso menos 2 na blacklist
    const codigos = await coluna(page, 1);
    expect(codigos).not.toContain("00000035");
    expect(codigos).not.toContain("00000036");

    const pag = card(page, /^Clientes/).locator(".paginacao");
    await expect(pag).toContainText("Mostrando 1–34 de 34");
    await pag.getByRole("combobox").selectOption("25");
    await expect(pag).toContainText("Mostrando 1–25 de 34");
    await expect(pag).toContainText("Página 1 de 2");
    await expect(pag.getByRole("button", { name: "← Anterior" })).toBeDisabled();
    const pagina1 = await coluna(page, 1);
    await pag.getByRole("button", { name: "Próxima →" }).click();
    await expect(pag).toContainText("Mostrando 26–34 de 34");
    await expect(pag.getByRole("button", { name: "Próxima →" })).toBeDisabled();
    const pagina2 = await coluna(page, 1);
    expect(pagina2.filter((c) => pagina1.includes(c))).toEqual([]);
    await pag.getByRole("button", { name: "← Anterior" }).click();
    await expect(pag).toContainText("Página 1 de 2");
  });

  test("ordenação é feita no servidor sobre o resultado inteiro", async ({ page }) => {
    await semRegrasPadrao(page);
    await aplicar(page);
    const pag = card(page, /^Clientes/).locator(".paginacao");
    await pag.getByRole("combobox").selectOption("25");
    const cab = card(page, /^Clientes/).getByRole("columnheader", { name: /^Nome/ });
    await cab.click();
    await expect(page.getByText("Consultando o SETA")).toHaveCount(0);
    const asc = await coluna(page, 3);
    const limpo = (s: string) => s.replace(/\s*SPC$/, "");
    expect(asc.map(limpo)).toEqual([...asc.map(limpo)].sort((a, b) => a.localeCompare(b, "pt-BR")));
    expect(limpo(asc[0])).toBe("ADRIANA COSTA"); // primeiro nome do conjunto inteiro, não só da página
    await cab.click();
    await expect(page.getByText("Consultando o SETA")).toHaveCount(0);
    const desc = await coluna(page, 3);
    expect(limpo(desc[0])).toBe("VINICIUS BATISTA");
    await expect(pag).toContainText("Página 1 de 2"); // ordenar volta para a primeira página

    // atraso: numérico, não alfabético
    await card(page, /^Clientes/).getByRole("columnheader", { name: /^Atraso/ }).click();
    await expect(page.getByText("Consultando o SETA")).toHaveCount(0);
    const dias = (await coluna(page, 7)).map((d) => (d === "vence amanhã" ? -1 : parseInt(d)));
    expect(dias).toEqual([...dias].sort((a, b) => a - b));

    // faixa: ordem de atraso, não alfabética
    await card(page, /^Clientes/).getByRole("columnheader", { name: /^Faixa/ }).click();
    await expect(page.getByText("Consultando o SETA")).toHaveCount(0);
    const faixas = await coluna(page, 8);
    const ordem = ["-1", "2", "3 A 10", "11 A 20", "21 A 30", "31 A 40", "41 A 60", "61 A 80", "81 A 100", "101 A 120", "121 A 140", "141 A 150", "151+"];
    const idx = faixas.map((f) => ordem.indexOf(f));
    expect(idx).toEqual([...idx].sort((a, b) => a - b));
  });

  test("filtros de faixa, cobradora, status, SPC e loja", async ({ page }) => {
    await semRegrasPadrao(page);
    await escolherMulti(filtros(page), "Faixa de atraso", ["3 A 10"]);
    await expect(filtros(page).locator(".ms-btn", { hasText: "3 A 10" })).toBeVisible();
    await aplicar(page);
    expect(new Set(await coluna(page, 8))).toEqual(new Set(["3 A 10"]));

    await filtros(page).getByRole("button", { name: "Limpar" }).click();
    await expect(filtros(page).getByLabel("Somente o primeiro dia da faixa")).toBeChecked();
    await semRegrasPadrao(page);
    await escolherMulti(filtros(page), "Restrição SPC", ["Sim"]);
    await aplicar(page);
    const n = await linhas(page).count();
    expect(n).toBeGreaterThan(0);
    await expect(linhas(page).locator(".badge", { hasText: "SPC" })).toHaveCount(n);

    await filtros(page).getByRole("button", { name: "Limpar" }).click();
    await semRegrasPadrao(page);
    await escolherMulti(filtros(page), "Status do cliente", ["Bloqueado", "Especial", "Ativo"]);
    await expect(filtros(page).locator(".ms-btn", { hasText: "3 selecionados" })).toBeVisible();
    await aplicar(page);
    await expect(titulo(page)).toContainText("(34)");

    await filtros(page).getByRole("button", { name: "Limpar" }).click();
    await semRegrasPadrao(page);
    await escolherMulti(filtros(page), "Loja", ["06 - LOJA PRAIA"]);
    await escolherMulti(filtros(page), "Cobradora", ["SYSCOB"]);
    await aplicar(page);
    const total = await linhas(page).count();
    expect(total).toBeGreaterThan(0);
    expect(total).toBeLessThan(34);
  });

  test("cobradora filtra pelas lojas do cluster dela, com opção Sem cobradora", async ({ page }) => {
    await semRegrasPadrao(page);
    await escolherMulti(filtros(page), "Status do cliente", ["Bloqueado", "Especial", "Ativo"]);
    await escolherMulti(filtros(page), "Cobradora", ["SYSCOB", "MJ", "Sem cobradora"]);
    await aplicar(page);
    await expect(titulo(page)).toContainText("(34)");

    await filtros(page).getByRole("button", { name: "Limpar" }).click();
    await semRegrasPadrao(page);
    await escolherMulti(filtros(page), "Status do cliente", ["Bloqueado", "Especial", "Ativo"]);
    await escolherMulti(filtros(page), "Cobradora", ["MJ"]);
    await aplicar(page);
    const soMj = await linhas(page).count();
    expect(soMj).toBeLessThan(34);
  });

  test("filtros por atributo da loja (regional, estado)", async ({ page }) => {
    await semRegrasPadrao(page);
    await escolherMulti(filtros(page), "Estado", ["RJ"]);
    await aplicar(page);
    const rj = await linhas(page).count();
    expect(rj).toBeGreaterThan(0);
    await filtros(page).getByRole("button", { name: "Limpar" }).click();
    await semRegrasPadrao(page);
    await escolherMulti(filtros(page), "Regional", ["NORTE"]);
    await aplicar(page);
    expect(await linhas(page).count()).toBeGreaterThan(0);
  });

  test("filtro de vencimento (de/até)", async ({ page }) => {
    await semRegrasPadrao(page);
    const d = new Date();
    d.setDate(d.getDate() - 30);
    const iso = `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`;
    await filtros(page).getByLabel("Vencimento de").fill(iso);
    await aplicar(page);
    const atrasos = (await coluna(page, 7)).map((a) => (a === "vence amanhã" ? -1 : parseInt(a)));
    expect(atrasos.length).toBeGreaterThan(0);
    expect(Math.max(...atrasos)).toBeLessThanOrEqual(30);
  });

  test("filtro sem resultado mostra mensagem de 'nenhum cliente'", async ({ page }) => {
    await filtros(page).getByLabel("Vencimento de").fill("2000-01-01");
    await filtros(page).getByLabel("Vencimento até").fill("2000-01-02");
    await aplicar(page);
    await expect(card(page, /^Clientes/)).toContainText(/nenhum cliente/i);
  });

  test("exportar Excel usa os filtros e a ordenação aplicados", async ({ page }) => {
    await semRegrasPadrao(page);
    await escolherMulti(filtros(page), "Faixa de atraso", ["3 A 10"]);
    await aplicar(page);
    const n = await linhas(page).count();
    const { nome, linhas: xlsx } = await baixar(page, () => filtros(page).getByRole("button", { name: "Exportar Excel" }).click());
    expect(nome).toMatch(/\.xlsx$/);
    expect(xlsx.length - 1).toBe(n);
    expect(xlsx[0].join(" ")).toMatch(/nome/i);
  });

  test("SETA fora do ar: mensagem clara e botão volta a funcionar", async ({ page }) => {
    permitirErrosConsole(page, "503");
    await page.route("**/cobranca/clientes?*", (r) =>
      r.fulfill({ status: 503, contentType: "application/json", body: JSON.stringify({ detail: "Falha ao consultar o SETA (OperationalError)" }) })
    );
    await filtros(page).getByRole("button", { name: "Aplicar filtros" }).click();
    await expect(card(page, /^Clientes/).locator(".error-box")).toContainText("SETA");
    await expect(page.getByText("Aplique os filtros para listar clientes.")).toHaveCount(0);
    await page.unroute("**/cobranca/clientes?*");
    await aplicar(page);
    await expect(card(page, /^Clientes/).locator(".error-box")).toHaveCount(0);
    expect(await linhas(page).count()).toBeGreaterThan(0);
  });

  test("filtro editado e não aplicado não é usado em silêncio por 'Enviar para fila'", async ({ page }) => {
    await aplicar(page);
    await escolherMulti(filtros(page), "Faixa de atraso", ["151+"]);
    let url = "";
    await page.route("**/leads/gerar?*", (r) => {
      url = r.request().url();
      return r.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify({ status: "ready", data: { criados: 0, ja_existiam: 0, sem_celular: 0, na_fila: 0 } }) });
    });
    const dialogo = responderDialogo(page, true);
    await filtros(page).getByRole("button", { name: "Enviar para fila de cobrança" }).click();
    await dialogo;
    await expect.poll(() => url).not.toBe("");
    expect(decodeURIComponent(url)).toContain("faixa=151+");
  });

  test("enviar para fila numa faixa sem número/template avisa que nada entrou na fila", async ({ page }) => {
    await escolherMulti(filtros(page), "Faixa de atraso", ["151+"]);
    await aplicar(page);
    const dialogo = responderDialogo(page, true);
    await filtros(page).getByRole("button", { name: "Enviar para fila de cobrança" }).click();
    await dialogo;
    await expect(filtros(page).locator(".error-box")).toContainText("Nenhum cliente entrou na fila");
    await expect(filtros(page).locator(".success-box")).toHaveCount(0);
  });

  test("cancelar a confirmação não envia nada", async ({ page }) => {
    await aplicar(page);
    let chamou = false;
    page.on("request", (r) => r.url().includes("/leads/gerar") && (chamou = true));
    const msg = responderDialogo(page, false);
    await filtros(page).getByRole("button", { name: "Enviar para fila de cobrança" }).click();
    expect(await msg).toMatch(/Enviar \d+ cliente\(s\) com os filtros atuais para a fila de cobrança\?/);
    await page.waitForTimeout(500);
    expect(chamou).toBe(false);
  });

  test("enviar para fila: confirmação, sucesso, lista some e os clientes entram na fila da faixa", async ({ page }) => {
    await escolherMulti(filtros(page), "Faixa de atraso", ["3 A 10", "11 A 20"]);
    await semRegrasPadrao(page);
    await aplicar(page);
    const n = await linhas(page).count();
    expect(n).toBeGreaterThan(0);
    const msg = responderDialogo(page, true);
    await filtros(page).getByRole("button", { name: "Enviar para fila de cobrança" }).click();
    expect(await msg).toContain(`Enviar ${n} cliente(s)`);
    await expect(filtros(page).locator(".success-box")).toHaveText(/^\d+ cliente\(s\) enviado\(s\) para a fila de cobrança\./, { timeout: 30_000 });
    await expect(page.getByText("Aplique os filtros para listar clientes.")).toBeVisible();

    const faixas = await apiGet(page, "/faixas");
    let naFila = 0;
    for (const nome of ["3 A 10", "11 A 20"]) {
      const f = faixas.find((x: any) => x.name === nome);
      naFila += (await apiGet(page, `/faixas/${f.id}/queue?limit=100&offset=0`)).total;
    }
    expect(naFila).toBeGreaterThan(0);
  });

  test("vindo da matriz do Dashboard (?cluster=&faixa=) já consulta com os filtros", async ({ page }) => {
    await page.goto("/cobranca?cluster=ESPECIAL&faixa=151%2B");
    await expect(filtros(page).locator(".ms-btn", { hasText: "ESPECIAL" })).toBeVisible();
    await expect(filtros(page).locator(".ms-btn", { hasText: "151+" })).toBeVisible();
    await expect(page.getByText("Consultando o SETA")).toHaveCount(0, { timeout: 30_000 });
    await expect(page.getByText("Nenhum cliente encontrado com esses filtros.").or(linhas(page).first())).toBeVisible();
  });
});
