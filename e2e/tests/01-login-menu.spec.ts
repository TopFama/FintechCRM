import { EMAIL, SENHA } from "./ambiente";
import { test, expect, allowConsoleErrors } from "./fixtures";

test.describe("01. Login & menu", () => {
  test.use({
    storageState: { cookies: [], origins: [] },
  });

  test("wrong password shows error", async ({ page }) => {
    allowConsoleErrors(page, /401/, /status of 401/);

    await page.goto("/login");

    // Attempt login with wrong password
    await page.locator('input[type="email"]').fill(EMAIL);
    await page.locator('input[type="password"]').fill("senha-errada-123");
    await page.getByRole("button", { name: "Entrar" }).click();

    // Verify error message is visible
    const errorBox = page.locator(".error-box");
    await expect(errorBox).toBeVisible({ timeout: 5000 });
    await expect(errorBox).toContainText(/Email ou senha (incorretos|inválidos)/i);
  });

  test("correct login lands on dashboard, sidebar has exact items", async ({ page }) => {
    // o Dashboard carrega as lojas; sem Google conectado /lojas responde 503 (esperado neste ambiente)
    allowConsoleErrors(page, /503/, /status of 503/);
    await page.goto("/login");

    // Login with correct password
    await page.locator('input[type="email"]').fill(EMAIL);
    await page.locator('input[type="password"]').fill(SENHA);
    await page.getByRole("button", { name: "Entrar" }).click();

    // Verify lands on dashboard
    await expect(page).toHaveURL("/");
    await expect(page.getByRole("heading", { name: "Dashboard" })).toBeVisible();

    // Check sidebar navigation items in exact order:
    // Dashboard, Cobrança, Leads, Blacklist, Números, Templates, Faixas de cobrança, Relatórios, Configurações
    const expectedMenuItems = [
      "Dashboard",
      "Cobrança",
      "Leads",
      "Blacklist",
      "Números",
      "Templates",
      "Faixas de cobrança",
      "Relatórios",
      "Configurações",
    ];

    const navLinks = page.locator(".sidebar nav a");
    await expect(navLinks).toHaveCount(expectedMenuItems.length);

    const actualTexts: string[] = [];
    const count = await navLinks.count();
    for (let i = 0; i < count; i++) {
      const text = (await navLinks.nth(i).innerText()).trim();
      actualTexts.push(text);
    }

    expect(actualTexts).toEqual(expectedMenuItems);
  });
});
