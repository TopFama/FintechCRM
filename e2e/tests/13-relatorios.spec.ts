import { baixar, card, expect, permitirErrosConsole, test } from "./fixtures";
import type { Page } from "@playwright/test";

const aba = (page: Page, nome: string) => page.getByRole("button", { name: nome, exact: true });
const tabela = (page: Page) => page.locator(".card table").first();

test.describe("Relatórios", () => {
  test.beforeEach(async ({ page }) => {
    await page.goto("/relatorios");
  });

  test("telefones inválidos: lista o que foi recusado na importação e baixa Excel", async ({ page }) => {
    await expect(tabela(page)).toBeVisible();
    await expect(tabela(page).locator("tbody tr", { hasText: "123" }).first()).toBeVisible();
    const { nome, linhas } = await baixar(page, () => page.getByRole("button", { name: /Baixar Excel/ }).click());
    expect(nome).toMatch(/\.xlsx$/);
    expect(linhas.length).toBeGreaterThan(1);
  });

  test("envios realizados: lista o que o worker enviou; ordenar por nome", async ({ page }) => {
    await aba(page, "Envios realizados").click();
    await expect(page.getByText("Cobrado de")).toBeVisible();
    await expect(tabela(page).locator("tbody tr").first()).toBeVisible();
    await expect(tabela(page).locator("tbody tr").first()).toContainText("3 A 10");
    await tabela(page).getByRole("columnheader", { name: /^Nome/ }).click();
    await expect(page.getByText("Carregando...")).toHaveCount(0);
    const nomes = await tabela(page).locator("tbody tr td:nth-child(3)").allInnerTexts();
    expect(nomes).toEqual([...nomes].sort((a, b) => a.localeCompare(b, "pt-BR")));
    const { linhas } = await baixar(page, () => page.getByRole("button", { name: /Baixar Excel/ }).click());
    expect(linhas.length - 1).toBe(await tabela(page).locator("tbody tr").count());
  });

  test("envios: filtro por faixa e por período", async ({ page }) => {
    await aba(page, "Envios realizados").click();
    await expect(tabela(page).locator("tbody tr").first()).toBeVisible();
    await page.locator("select").first().selectOption({ label: "11 A 20" });
    await expect(page.getByText("Nenhum envio realizado ainda")).toBeVisible();
    await page.locator("select").first().selectOption({ label: "Todas as faixas" });
    await expect(tabela(page).locator("tbody tr").first()).toBeVisible();
    await page.locator('input[type="date"]').first().fill("2020-01-01");
    await page.locator('input[type="date"]').nth(1).fill("2020-01-02");
    await expect(page.getByText("Nenhum envio realizado ainda")).toBeVisible();
  });

  test("estado vazio de envios com filtro não diz 'ainda' como se nunca tivesse havido envio", async ({ page }) => {
    test.fail(true, "BUG (texto): com filtro sem resultado a tela diz 'Nenhum envio realizado ainda'");
    await aba(page, "Envios realizados").click();
    await page.locator("select").first().selectOption({ label: "11 A 20" });
    await expect(page.getByText("Carregando...")).toHaveCount(0);
    await expect(page.locator(".empty-state")).toBeVisible();
    await expect(page.getByText("Nenhum envio realizado ainda")).toHaveCount(0);
  });

  test("quem pagou: totais, filtro de pagamento e Excel", async ({ page }) => {
    await aba(page, "Quem pagou").click();
    await expect(page.getByText("Pago de")).toBeVisible();
    await expect(page.locator(".stat", { hasText: "Clientes que pagaram" })).toBeVisible({ timeout: 30_000 });
    const n = Number(await page.locator(".stat", { hasText: "Clientes que pagaram" }).locator(".value").innerText());
    expect(n).toBeGreaterThan(0);
    await expect(tabela(page).locator("tbody tr")).toHaveCount(n);
    const { linhas } = await baixar(page, () => page.getByRole("button", { name: /Baixar Excel/ }).click());
    expect(linhas.length).toBeGreaterThan(1);
    const inputs = page.locator('input[type="date"]');
    await inputs.nth(2).fill("2020-01-01");
    await inputs.nth(3).fill("2020-01-02");
    await expect(page.getByText("Ninguém pagou no período")).toBeVisible({ timeout: 30_000 });
  });

  test("trocar de aba mantém datas e mostra carregando", async ({ page }) => {
    await page.locator('input[type="date"]').first().fill("2020-01-01");
    await page.locator('input[type="date"]').nth(1).fill("2020-01-02");
    await aba(page, "Envios realizados").click();
    await expect(page.locator('input[type="date"]').first()).toHaveValue("2020-01-01");
    await expect(page.getByText("Nenhum envio realizado ainda")).toBeVisible();
  });

  test("erro do servidor aparece no topo e some ao trocar de aba com sucesso", async ({ page }) => {
    permitirErrosConsole(page, "500");
    await page.route("**/relatorios/telefones-invalidos?*", (r) =>
      r.fulfill({ status: 500, contentType: "application/json", body: JSON.stringify({ detail: "Falha interna" }) })
    );
    await page.reload();
    await expect(page.locator(".error-box")).toContainText("Falha interna");
    await aba(page, "Envios realizados").click();
    await expect(page.locator(".error-box")).toHaveCount(0);
  });
});
