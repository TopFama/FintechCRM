import { card, expect, permitirErrosConsole, responderDialogo, test } from "./fixtures";

test.describe("Configurações → Usuários", { tag: "@usuarios" }, () => {
  test("criar usuário padrão, e-mail repetido e senha curta", async ({ page }) => {
    permitirErrosConsole(page, /4\d\d/);
    await page.goto("/configuracoes?aba=usuarios");
    const form = card(page, "Criar usuário");
    await form.getByLabel("Email").fill("operador@topfama.com.br");
    await form.getByLabel("Senha").fill("curta");
    await form.getByRole("button", { name: "Criar usuário" }).click();
    expect(await form.getByLabel("Senha").evaluate((e: HTMLInputElement) => e.validity.valid)).toBe(false);
    await form.getByLabel("Senha").fill("operador-123");
    await form.getByRole("button", { name: "Criar usuário" }).click();
    await expect(form.locator(".success-box")).toContainText('Usuário "operador@topfama.com.br" criado.');
    const lista = card(page, /Usuários \(/);
    await expect(lista.getByRole("heading")).toHaveText("Usuários (2)");
    await expect(lista.locator("tbody tr", { hasText: "operador@" })).toContainText("Padrão");

    await form.getByLabel("Email").fill("operador@topfama.com.br");
    await form.getByLabel("Senha").fill("operador-123");
    await form.getByRole("button", { name: "Criar usuário" }).click();
    await expect(form.locator(".error-box")).toBeVisible();
  });

  test("admin não tem botão de excluir; ordenar por e-mail", async ({ page }) => {
    await page.goto("/configuracoes?aba=usuarios");
    const lista = card(page, /Usuários \(/);
    await expect(lista.locator("tbody tr", { hasText: "admin@" }).getByRole("button", { name: "Excluir" })).toHaveCount(0);
    await lista.getByRole("columnheader", { name: /Email/ }).click();
    await expect(lista.locator("tbody tr").first()).toContainText("admin@");
    await lista.getByRole("columnheader", { name: /Email/ }).click();
    await expect(lista.locator("tbody tr").first()).toContainText("operador@");
  });
});

test.describe("Usuário padrão", { tag: "@usuarios" }, () => {
  test.use({ storageState: { cookies: [], origins: [] } });

  test("não vê a aba Usuários nem abre por URL", async ({ page }) => {
    await page.goto("/login");
    await page.getByPlaceholder("voce@empresa.com").fill("operador@topfama.com.br");
    await page.getByPlaceholder("••••••••").fill("operador-123");
    await page.getByRole("button", { name: "Entrar" }).click();
    await expect(page).toHaveURL("/");
    await page.goto("/configuracoes?aba=usuarios");
    await expect(page.locator(".tabs").getByRole("button", { name: "Usuários" })).toHaveCount(0);
    await expect(page.getByRole("heading", { name: "Criar usuário" })).toHaveCount(0);
  });
});

test.describe("Excluir usuário", { tag: "@usuarios" }, () => {
  test("cancelar mantém; confirmar remove", async ({ page }) => {
    await page.goto("/configuracoes?aba=usuarios");
    const lista = card(page, /Usuários \(/);
    const linha = lista.locator("tbody tr", { hasText: "operador@" });
    let msg = responderDialogo(page, false);
    await linha.getByRole("button", { name: "Excluir" }).click();
    expect(await msg).toContain('Excluir o usuário "operador@topfama.com.br"?');
    await expect(linha).toBeVisible();
    msg = responderDialogo(page, true);
    await linha.getByRole("button", { name: "Excluir" }).click();
    await msg;
    await expect(lista.getByRole("heading")).toHaveText("Usuários (1)");
  });
});
