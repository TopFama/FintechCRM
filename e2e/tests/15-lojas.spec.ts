import { card, expect, permitirErrosConsole, responderDialogo, test } from "./fixtures";

// Roda por último: mexe na base de lojas que os filtros das outras telas usam.
test.describe("Configurações → Lojas", () => {
  test.beforeEach(async ({ page }) => {
    await page.goto("/configuracoes?aba=lojas");
  });

  const lojas = (page: import("@playwright/test").Page) => card(page, /^Lojas$/);
  const linha = (page: import("@playwright/test").Page, filial: string) =>
    lojas(page).locator("tbody tr").filter({ has: page.locator("td.cell-strong", { hasText: new RegExp(`^${filial}$`) }) });

  test("lista a base com cobradora e busca", async ({ page }) => {
    await expect(lojas(page).locator("tbody tr")).toHaveCount(4);
    await expect(linha(page, "10")).toContainText("Sem cobradora");
    await expect(linha(page, "02")).toContainText("MJ");
    await lojas(page).getByLabel("Buscar").fill("syscob");
    await expect(lojas(page).locator("tbody tr")).toHaveCount(2);
    await lojas(page).getByLabel("Buscar").fill("nada disso");
    await expect(lojas(page).getByText("Nenhuma loja encontrada")).toBeVisible();
  });

  test("formatação condicional do Cluster INAD igual à planilha", async ({ page }) => {
    await linha(page, "01").getByRole("button", { name: "Editar" }).click();
    await linha(page, "01").getByLabel("Cluster INAD").fill("CLUSTER UTI +");
    await linha(page, "01").getByRole("button", { name: "Salvar" }).click();
    await expect(lojas(page).locator(".success-box")).toContainText("Loja 01 salva.");
    await expect(linha(page, "01").locator(".badge.cluster-inad-uti-mais")).toHaveText("CLUSTER UTI +");
  });

  test("editar a cobradora; cancelar não salva", async ({ page }) => {
    await linha(page, "10").getByRole("button", { name: "Editar" }).click();
    await linha(page, "10").getByLabel("Regional").fill("QUALQUER");
    await linha(page, "10").getByRole("button", { name: "Cancelar" }).click();
    await expect(linha(page, "10")).toContainText("CENTRO");

    await linha(page, "10").getByRole("button", { name: "Editar" }).click();
    await linha(page, "10").getByLabel("Cobradora").fill("mj");
    await linha(page, "10").getByRole("button", { name: "Salvar" }).click();
    await expect(linha(page, "10").locator(".badge.draft")).toHaveText("mj");
  });

  test("adicionar, duplicada e excluir", async ({ page }) => {
    permitirErrosConsole(page, /409/);
    const add = card(page, "Adicionar loja");
    await add.getByLabel("Filial").fill("77");
    await add.getByLabel("Nome").fill("77 - LOJA NOVA");
    await add.getByLabel("Estado").fill("to");
    await add.getByRole("button", { name: "Adicionar loja" }).click();
    await expect(lojas(page).locator(".success-box")).toContainText("Loja 77 adicionada.");
    await expect(linha(page, "77")).toContainText("TO");

    await add.getByLabel("Filial").fill("77");
    await add.getByRole("button", { name: "Adicionar loja" }).click();
    await expect(lojas(page).locator(".error-box")).toContainText("já está cadastrada");

    const dialogo = responderDialogo(page);
    await linha(page, "77").getByRole("button", { name: "Excluir a loja 77" }).click();
    expect(await dialogo).toContain("77 - LOJA NOVA");
    await expect(linha(page, "77")).toHaveCount(0);
  });

  test("sincronizar: a planilha vence nos campos que tem e mantém a cobradora", async ({ page }) => {
    await linha(page, "02").getByRole("button", { name: "Editar" }).click();
    await linha(page, "02").getByLabel("Regional").fill("LESTE");
    await linha(page, "02").getByRole("button", { name: "Salvar" }).click();
    await expect(linha(page, "02")).toContainText("LESTE");

    const dialogo = responderDialogo(page);
    await lojas(page).getByRole("button", { name: "Sincronizar com a planilha" }).click();
    expect(await dialogo).toContain("substituem");
    await expect(lojas(page).locator(".success-box")).toContainText("Sincronizado com a planilha");
    await expect(linha(page, "02")).toContainText("NORTE");
    await expect(linha(page, "02")).toContainText("MJ");
  });
});
