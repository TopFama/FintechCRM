import { test, expect } from "./fixtures";

test.describe("06. Configurações", () => {
  test("ERP card shows connected, 'Somente leitura', latency in ms, and 'Testar conexão' works", async ({ page }) => {
    await page.goto("/configuracoes");
    await expect(page.getByRole("heading", { level: 2, name: "Configurações" })).toBeVisible();

    const erpCard = page.locator(".card").filter({ hasText: "ERP SETA" });
    await expect(erpCard).toBeVisible();

    // Verify connected status, "Somente leitura", and latency in ms
    await expect(erpCard.locator(".status-pill")).toContainText(/Conectado/i);
    await expect(erpCard).toContainText(/Somente leitura/i);
    await expect(erpCard.locator("text=/\\d+\\s*ms/")).toBeVisible();

    // "Testar conexão" works
    const testarBtn = erpCard.getByRole("button", { name: "Testar conexão" });
    await expect(testarBtn).toBeVisible();
    await testarBtn.click();

    // After testing connection, status remains connected and latency is present
    await expect(erpCard.locator(".status-pill")).toContainText(/Conectado/i);
    await expect(erpCard.locator("text=/\\d+\\s*ms/")).toBeVisible();
  });

  test("Google card explains missing GOOGLE_CLIENT_ID/SECRET and shows redirect URI", async ({ page }) => {
    await page.goto("/configuracoes");

    const googleCard = page.locator(".card").filter({ hasText: "Google" });
    await expect(googleCard).toBeVisible();
    await expect(googleCard).toContainText("GOOGLE_CLIENT_ID");
    await expect(googleCard).toContainText("GOOGLE_CLIENT_SECRET");
    await expect(googleCard.getByText(/URI de redirecionamento/i)).toBeVisible();

    const redirectCode = googleCard.locator("code").filter({ hasText: /callback|\/google/i });
    await expect(redirectCode).toBeVisible();
    const redirectUri = await redirectCode.innerText();
    expect(redirectUri).toMatch(/^https?:\/\/.+/);
  });

  test("opening /configuracoes?google=erro&motivo=Teste%20e2e shows error box with 'Teste e2e' and query string is removed", async ({ page }) => {
    await page.goto("/configuracoes?google=erro&motivo=Teste%20e2e");

    // Query string should be removed from URL
    await expect(page).toHaveURL("/configuracoes");

    // Shows error box with "Teste e2e"
    const errorBox = page.locator(".error-box");
    await expect(errorBox).toBeVisible({ timeout: 5000 });
    await expect(errorBox).toContainText("Teste e2e");
  });
});
