import { EMAIL, SENHA } from "./ambiente";
import { expect, permitirErrosConsole, test } from "./fixtures";

test.describe("Login e navegação", () => {
  test.use({ storageState: { cookies: [], origins: [] } });

  test("sem sessão, qualquer tela manda para o login", async ({ page }) => {
    for (const rota of ["/", "/cobranca", "/relatorios", "/configuracoes", "/faixas/nova"]) {
      await page.goto(rota);
      await expect(page).toHaveURL(/\/login$/);
    }
  });

  test("campos do login têm rótulo ligado (clicar no título foca o campo)", async ({ page }) => {
    await page.goto("/login");
    await expect(page.getByLabel("Email")).toBeVisible();
    await page.getByText("Senha", { exact: true }).click();
    await expect(page.getByLabel("Senha")).toBeFocused();
  });

  test("senha errada mostra erro e mantém na tela de login", async ({ page }) => {
    permitirErrosConsole(page, "401");
    await page.goto("/login");
    await page.getByPlaceholder("voce@empresa.com").fill(EMAIL);
    await page.getByPlaceholder("••••••••").fill("senha-errada");
    await page.getByRole("button", { name: "Entrar" }).click();
    await expect(page.locator(".error-box")).toBeVisible();
    await expect(page.locator(".error-box")).not.toBeEmpty();
    await expect(page).toHaveURL(/\/login$/);
  });

  test("campos obrigatórios bloqueiam envio vazio (validação do navegador)", async ({ page }) => {
    await page.goto("/login");
    await page.getByRole("button", { name: "Entrar" }).click();
    await expect(page).toHaveURL(/\/login$/);
    const valido = await page.getByPlaceholder("voce@empresa.com").evaluate((el: HTMLInputElement) => el.validity.valid);
    expect(valido).toBe(false);
  });

  test("botão mostra 'Entrando...' enquanto autentica", async ({ page }) => {
    await page.route("**/auth/login", async (r) => {
      await new Promise((res) => setTimeout(res, 800));
      await r.continue();
    });
    await page.goto("/login");
    await page.getByPlaceholder("voce@empresa.com").fill(EMAIL);
    await page.getByPlaceholder("••••••••").fill(SENHA);
    await page.getByRole("button", { name: "Entrar" }).click();
    await expect(page.getByRole("button", { name: "Entrando..." })).toBeDisabled();
    await expect(page).toHaveURL("/");
  });

  test("login, menu lateral e logout", async ({ page }) => {
    await page.goto("/login");
    await page.getByPlaceholder("voce@empresa.com").fill(EMAIL);
    await page.getByPlaceholder("••••••••").fill(SENHA);
    await page.getByRole("button", { name: "Entrar" }).click();
    await expect(page).toHaveURL("/");

    const menu = page.locator("aside nav");
    for (const [item, url, titulo] of [
      ["Cobrança", "/cobranca", "Cobrança"],
      ["Relatórios", "/relatorios", "Relatórios"],
      ["Configurações", "/configuracoes", "Configurações"],
      ["Dashboard", "/", "Dashboard"],
    ] as const) {
      await menu.getByRole("link", { name: item }).click();
      await expect(page).toHaveURL(url);
      await expect(page.getByRole("heading", { level: 2, name: titulo })).toBeVisible();
      await expect(menu.getByRole("link", { name: item })).toHaveClass(/active/);
    }

    // rotas antigas redirecionam
    await page.goto("/leads");
    await expect(page).toHaveURL("/cobranca");
    await page.goto("/blacklist");
    await expect(page).toHaveURL("/configuracoes?aba=blacklist");

    await page.getByRole("button", { name: "Sair" }).click();
    await expect(page).toHaveURL(/\/login$/);
    await page.goto("/");
    await expect(page).toHaveURL(/\/login$/);
  });

  test("sessão expirada no servidor: a tela volta para o login", async ({ page, context }) => {
    permitirErrosConsole(page, "401");
    await page.goto("/login");
    await page.getByPlaceholder("voce@empresa.com").fill(EMAIL);
    await page.getByPlaceholder("••••••••").fill(SENHA);
    await page.getByRole("button", { name: "Entrar" }).click();
    await expect(page).toHaveURL("/");
    // cookie some (expirou), mas a marca de "logado" continua no navegador
    await context.clearCookies();
    // o redirecionamento para /login acontece durante a navegação
    await page.goto("/cobranca").catch(() => undefined);
    await expect(page).toHaveURL(/\/login$/, { timeout: 10_000 });
  });
});
