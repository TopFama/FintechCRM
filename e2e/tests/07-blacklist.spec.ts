import { card, expect, permitirErrosConsole, responderDialogo, test } from "./fixtures";

test.describe("Configurações → Blacklist", { tag: "@blacklist" }, () => {
  test.beforeEach(async ({ page }) => {
    await page.goto("/configuracoes?aba=blacklist");
  });

  test("adicionar código SETA, CPF, duplicado e inválido", async ({ page }) => {
    permitirErrosConsole(page, /4\d\d/);
    const add = card(page, "Adicionar");
    await add.getByLabel("Código SETA ou CPF").fill("36");
    await add.getByLabel("Motivo (opcional)").fill("Pediu para não ser cobrado");
    await add.getByRole("button", { name: "Adicionar" }).click();
    await expect(add.locator(".success-box")).toContainText('"36" adicionado à blacklist.');
    const tabela = card(page, /Registros/);
    await expect(tabela.locator("tbody tr")).toHaveCount(1);
    await expect(tabela.locator("tbody tr")).toContainText("Pediu para não ser cobrado");

    await add.getByLabel("Código SETA ou CPF").fill("36");
    await add.getByRole("button", { name: "Adicionar" }).click();
    await expect(add.locator(".error-box")).toBeVisible();

    await add.getByLabel("Código SETA ou CPF").fill("abc!");
    await add.getByRole("button", { name: "Adicionar" }).click();
    await expect(add.locator(".error-box")).toBeVisible();
    await expect(add.locator(".success-box")).toHaveCount(0);
  });

  test("colar lista: separadores, já existentes e inválidos", async ({ page }) => {
    const lote = card(page, "Colar lista");
    const botao = lote.getByRole("button", { name: "Adicionar lista" });
    await expect(botao).toBeDisabled();
    await lote.getByLabel(/Documentos/).fill("35\n123.456.789-09; 36, xyz");
    await botao.click();
    await expect(lote.locator(".success-box")).toContainText("já estavam na lista");
    await expect(lote).toContainText("xyz");
    await expect(card(page, /Registros/).locator("tbody tr")).toHaveCount(3);
  });

  test("buscar filtra a lista e 'Nenhum registro' quando não acha", async ({ page }) => {
    const tabela = card(page, /Registros/);
    await tabela.getByPlaceholder("Buscar por código ou CPF...").fill("35");
    await expect(tabela.locator("tbody tr")).toHaveCount(1);
    await tabela.getByPlaceholder("Buscar por código ou CPF...").fill("99999999");
    await expect(tabela.getByText("Nenhum registro encontrado")).toBeVisible();
    await tabela.getByPlaceholder("Buscar por código ou CPF...").fill("");
    await expect(tabela.locator("tbody tr")).toHaveCount(3);
  });

  test("remover: cancelar e confirmar", async ({ page }) => {
    const tabela = card(page, /Registros/);
    const linha = tabela.locator("tbody tr", { hasText: "123.456.789-09" });
    let msg = responderDialogo(page, false);
    await linha.getByRole("button", { name: "Remover" }).click();
    expect(await msg).toContain("Remover");
    await expect(linha).toBeVisible();
    msg = responderDialogo(page, true);
    await linha.getByRole("button", { name: "Remover" }).click();
    await msg;
    await expect(tabela.locator("tbody tr")).toHaveCount(2);
  });
});
