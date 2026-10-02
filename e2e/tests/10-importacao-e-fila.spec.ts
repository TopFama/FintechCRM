import path from "node:path";
import { fileURLToPath } from "node:url";
import { apiGet, baixar, campo, card, expect, permitirErrosConsole, test } from "./fixtures";
import type { Page } from "@playwright/test";
import { prepararFaixas } from "./preparo";

const DADOS = path.join(path.dirname(fileURLToPath(import.meta.url)), "dados");
const importar = (page: Page) => card(page, "Importar planilha para a fila");

async function abrirImportacao(page: Page, faixa: string) {
  await page.goto("/cobranca");
  await campo(importar(page), "Faixa").selectOption({ label: faixa });
  await expect(page.getByRole("heading", { name: "Subir planilha e mapear colunas" })).toBeVisible();
}

test.beforeAll(prepararFaixas);

test.describe("Cobrança → Importar planilha para a fila", () => {
  test("faixa sem número/template avisa antes de subir", async ({ page }) => {
    await page.goto("/cobranca");
    await campo(importar(page), "Faixa").selectOption({ label: "21 A 30" });
    await expect(importar(page)).toContainText(/antes de subir a planilha/);
  });

  test("baixar modelo sugerido (.xlsx) com as colunas da faixa", async ({ page }) => {
    await abrirImportacao(page, "11 A 20");
    const { nome, linhas } = await baixar(page, () => page.getByRole("button", { name: /Baixar modelo sugerido/ }).click());
    expect(nome).toMatch(/\.xlsx$/);
    expect(linhas[0].length).toBeGreaterThan(3);
  });

  test("arquivo que não é Excel mostra erro", async ({ page }) => {
    permitirErrosConsole(page, /4\d\d/);
    await abrirImportacao(page, "11 A 20");
    await importar(page).locator('input[type="file"]').setInputFiles(path.join(DADOS, "nao_e_planilha.xlsx"));
    await expect(importar(page).locator(".error-box")).toBeVisible();
  });

  test("mapear colunas: confirmar só libera com obrigatórios; cancelar volta ao início", async ({ page }) => {
    await abrirImportacao(page, "11 A 20");
    await importar(page).locator('input[type="file"]').setInputFiles(path.join(DADOS, "planilha_faixa.xlsx"));
    const confirmar = page.getByRole("button", { name: "Confirmar e importar" });
    await expect(confirmar).toBeVisible();
    await expect(confirmar).toBeDisabled();
    await campo(importar(page), /Coluna do código/).selectOption("Codigo Cliente");
    await campo(importar(page), /Coluna do nome/).selectOption("Nome Completo");
    await campo(importar(page), /Coluna do CPF/).selectOption("Documento");
    await campo(importar(page), /Coluna do celular/).selectOption("Telefone");
    const variaveis = importar(page).locator(".field", { hasText: /cobranca_atraso: variavel_\d/ }).locator("select");
    const n = await variaveis.count();
    if (n > 0) await expect(confirmar).toBeDisabled();
    for (let i = 0; i < n; i++) await variaveis.nth(i).selectOption({ index: 1 + (i % 6) });
    await expect(confirmar).toBeEnabled();
    await expect(importar(page).getByText("Pré-visualização (com a primeira linha da planilha subida)")).toBeVisible();
    await page.getByRole("button", { name: "Cancelar" }).click();
    await expect(confirmar).toHaveCount(0);
    await expect(importar(page).getByText("Clique ou arraste a planilha aqui")).toBeVisible();
  });

  test("importar: resumo de aceitos, rejeitados e telefones inválidos", async ({ page }) => {
    await abrirImportacao(page, "11 A 20");
    await importar(page).locator('input[type="file"]').setInputFiles(path.join(DADOS, "planilha_faixa.xlsx"));
    await campo(importar(page), /Coluna do código/).selectOption("Codigo Cliente");
    await campo(importar(page), /Coluna do nome/).selectOption("Nome Completo");
    await campo(importar(page), /Coluna do CPF/).selectOption("Documento");
    await campo(importar(page), /Coluna do celular/).selectOption("Telefone");
    await campo(importar(page), /Coluna do valor/).selectOption("Valor Devido");
    const variaveis = importar(page).locator(".field", { hasText: /: variavel_\d/ }).locator("select");
    const alvo = ["Nome Completo", "Valor Devido", "Vencimento", "Codigo Cliente"];
    for (let i = 0; i < (await variaveis.count()); i++) await variaveis.nth(i).selectOption(alvo[i % alvo.length]);
    await page.getByRole("button", { name: "Confirmar e importar" }).click();
    const resumo = importar(page).locator(".upload-summary");
    await expect(resumo).toContainText("8linhas na planilha");
    await expect(resumo).toContainText("4rejeitados"); // sem código, telefone "123", fixo e variável em branco
    await expect(resumo).toContainText("telefone(s) inválido(s)");
    await expect(importar(page).getByRole("link", { name: /relatório de telefones inválidos/ })).toBeVisible();
    await expect(importar(page).locator("ul li").first()).toBeVisible(); // motivos de rejeição listados

    // Valor zerado não entra direto: o usuário escolhe um valor ou descarta
    const aceitos = Number((await resumo.locator(".item").first().locator(".num").textContent()) || 0);
    await expect(importar(page).getByRole("heading", { name: "Valor zerado na planilha (1)" })).toBeVisible();
    await expect(importar(page).locator("tbody tr", { hasText: "00000107" })).toBeVisible();
    await importar(page).getByLabel("Valor a usar na linha 9").selectOption({ label: "Outro valor" });
    await importar(page).getByLabel("Outro valor para a linha 9").fill("75,00");
    await page.getByRole("button", { name: "Confirmar valores" }).click();
    await expect(importar(page).getByRole("heading", { name: /Valor zerado na planilha/ })).toHaveCount(0);
    await expect(resumo.locator(".item").first()).toContainText(`${aceitos + 1}aceitos`);
  });

  test("valor zerado entra com o valor escolhido", async ({ page }) => {
    const f = (await apiGet(page, "/faixas")).find((x: any) => x.name === "11 A 20");
    const fila = await apiGet(page, `/faixas/${f.id}/queue?limit=100&offset=0`);
    const zerado = fila.itens.filter((i: any) => i.codigo_cliente === "00000107");
    expect(zerado.map((i: any) => [i.status, i.valor])).toEqual([["pending", "75,00"]]);
  });

  test("telefone fixo não vira celular inventado", async ({ page }) => {
    const f = (await apiGet(page, "/faixas")).find((x: any) => x.name === "11 A 20");
    const fila = await apiGet(page, `/faixas/${f.id}/queue?limit=100&offset=0`);
    expect(fila.itens.map((i: any) => i.celular)).not.toContain("5511933334444");
  });

  test("mapeamento fica lembrado na próxima importação da mesma faixa", async ({ page }) => {
    await abrirImportacao(page, "11 A 20");
    await importar(page).locator('input[type="file"]').setInputFiles(path.join(DADOS, "planilha_faixa.xlsx"));
    await expect(campo(importar(page), /Coluna do celular/)).toHaveValue("Telefone");
    await expect(campo(importar(page), /Coluna do código/)).toHaveValue("Codigo Cliente");
  });
});

test.describe("Detalhe da faixa: fila", () => {
  async function abrirFaixa(page: Page, nome: string) {
    const f = (await apiGet(page, "/faixas")).find((x: any) => x.name === nome);
    await page.goto(`/faixas/${f.id}`);
    await expect(page.getByRole("heading", { level: 2, name: nome })).toBeVisible();
  }

  test("fila mostra os itens importados, com hora de atualização", async ({ page }) => {
    await abrirFaixa(page, "11 A 20");
    const fila = card(page, "Fila desta faixa");
    await expect(fila).toContainText(/atualizado \d{2}:\d{2}/);
    await expect(fila.locator("tbody tr", { hasText: "Roberta" })).toBeVisible();
    await expect(fila.locator("tbody tr").first().locator(".badge")).toBeVisible();
  });

  test("status da fila aparece em português", async ({ page }) => {
    await abrirFaixa(page, "11 A 20");
    await expect(card(page, "Fila desta faixa").locator("tbody .badge").first()).toBeVisible();
    const badges = await card(page, "Fila desta faixa").locator("tbody .badge").allInnerTexts();
    expect(badges.filter((b) => /pending|sent|error|expired/i.test(b))).toEqual([]);
  });

  test("ordenar a fila por nome continua valendo depois da atualização automática (4s)", async ({ page }) => {
    await abrirFaixa(page, "11 A 20");
    const fila = card(page, "Fila desta faixa");
    await fila.getByRole("columnheader", { name: /^Nome/ }).click();
    await fila.getByRole("columnheader", { name: /^Nome/ }).click(); // decrescente
    const nomes = () => fila.locator("tbody tr td:nth-child(2)").allInnerTexts();
    await expect.poll(async () => { const n = await nomes(); return n.join("|") === [...n].sort((a, b) => b.localeCompare(a, "pt-BR")).join("|"); }).toBe(true);
    await page.waitForTimeout(5_000);
    const depois = await nomes();
    expect(depois).toEqual([...depois].sort((a, b) => b.localeCompare(a, "pt-BR")));
  });

  test("leads da faixa: tabela e texto coerente com o fluxo atual", async ({ page }) => {
    await abrirFaixa(page, "11 A 20");
    const leads = card(page, "Leads gerados nesta faixa de atraso");
    await expect(leads.locator("tbody tr").first()).toBeVisible();
  });

  test("texto do card de leads não manda subir planilha (leads já entram na fila)", async ({ page }) => {
    await abrirFaixa(page, "11 A 20");
    const leads = card(page, "Leads gerados nesta faixa de atraso");
    await expect(leads).not.toContainText("não entram automaticamente");
    await expect(leads).not.toContainText("Cobrança → Leads");
  });
});
