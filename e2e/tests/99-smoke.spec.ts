import { EMAIL, SENHA } from "./ambiente";
import { card, expect, test } from "./fixtures";
import { prepararOperacao } from "./preparo";

// Roda por último (99): não deixa estado para os specs que começam de um banco vazio.
// Fumaça: cada tela principal abre e mostra dados. Roda quando a mudança é ampla
// demais para apontar uma tela (estilos, contratos) e junto com as demais seleções.
test.beforeAll(prepararOperacao);

test.describe("Fumaça", { tag: "@smoke" }, () => {
  test("login: entra com o admin e chega ao Dashboard", async ({ browser }) => {
    const contexto = await browser.newContext({ storageState: { cookies: [], origins: [] } });
    const page = await contexto.newPage();
    await page.goto("/login");
    await page.getByPlaceholder("voce@empresa.com").fill(EMAIL);
    await page.getByPlaceholder("••••••••").fill(SENHA);
    await page.getByRole("button", { name: "Entrar" }).click();
    await expect(page).not.toHaveURL(/\/login$/);
    await contexto.close();
  });

  test("Dashboard: resumo de hoje e tabela por faixa", async ({ page }) => {
    await page.goto("/");
    await expect(page.locator(".periodo-card", { hasText: "Hoje" }).first()).toHaveAttribute("aria-pressed", "true");
    await expect(card(page, "Por faixa").locator("tbody tr", { hasText: "3 A 10" })).toBeVisible();
  });

  test("Cobrança: aplicar os filtros lista clientes do SETA", async ({ page }) => {
    await page.goto("/cobranca");
    await page.getByRole("button", { name: "Aplicar filtros" }).click();
    await expect(card(page, /^Clientes/)).toContainText(/Mostrando 1–\d+ de \d+/, { timeout: 30_000 });
  });

  test("Relatórios: abre em Pendentes com a fila", async ({ page }) => {
    await page.goto("/relatorios");
    await expect(page.locator(".card").first().getByRole("button").first()).toHaveText("Pendentes");
    await expect(page.locator(".card table tbody tr").first()).toBeVisible();
  });

  test("Configurações: Conexões lista o token e os números", async ({ page }) => {
    await page.goto("/configuracoes?aba=conexoes");
    await expect(page.getByText("1111111111").first()).toBeVisible();
  });
});
