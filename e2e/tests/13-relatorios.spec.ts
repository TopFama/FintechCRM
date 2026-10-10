import { baixar, card, expect, permitirErrosConsole, test } from "./fixtures";
import type { Page } from "@playwright/test";
import { prepararOperacao } from "./preparo";

const aba = (page: Page, nome: string) => page.getByRole("button", { name: nome, exact: true });
const tabela = (page: Page) => page.locator(".card table").first();

test.beforeAll(prepararOperacao);

test.describe("Relatórios", { tag: "@relatorios" }, () => {
  test.beforeEach(async ({ page }) => {
    await page.goto("/relatorios");
  });

  test("abas na ordem dos cards do Dashboard, começando por Pendentes", async ({ page }) => {
    const rotulos = ["Pendentes", "Envios realizados", "Erros", "Telefones inválidos", "Quem pagou"];
    const botoes = page.locator(".card").first().getByRole("button");
    await expect(botoes.first()).toHaveText("Pendentes");
    await expect(botoes.first()).not.toHaveClass(/secondary/);
    for (let i = 0; i < rotulos.length; i++) await expect(botoes.nth(i)).toHaveText(rotulos[i]);
  });

  test("telefones inválidos: lista o que foi recusado na importação e baixa Excel", async ({ page }) => {
    await aba(page, "Telefones inválidos").click();
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
    expect(linhas[0]).toContain("Lojas");
  });

  test("envios realizados: coluna Loja ordena no servidor", async ({ page }) => {
    await aba(page, "Envios realizados").click();
    await expect(tabela(page).locator("tbody tr").first()).toBeVisible();
    const pedido = page.waitForRequest((r) => r.url().includes("/relatorios/envios?") && r.url().includes("sort_by=loja"));
    await tabela(page).getByRole("columnheader", { name: /^Loja/ }).click();
    await pedido;
    await expect(page.getByText("Carregando...")).toHaveCount(0);
    await expect(tabela(page).locator("tbody tr").first()).toBeVisible();
  });

  test("envios: filtro por faixa e por período", async ({ page }) => {
    await aba(page, "Envios realizados").click();
    await expect(tabela(page).locator("tbody tr").first()).toBeVisible();
    await page.locator("select").first().selectOption({ label: "11 A 20" });
    await expect(page.getByText("Nenhum envio encontrado com esses filtros")).toBeVisible();
    await page.locator("select").first().selectOption({ label: "Todas as faixas" });
    await expect(tabela(page).locator("tbody tr").first()).toBeVisible();
    await page.locator('input[type="date"]').first().fill("2020-01-01");
    await page.locator('input[type="date"]').nth(1).fill("2020-01-02");
    await expect(page.getByText("Nenhum envio encontrado com esses filtros")).toBeVisible();
  });

  test("estado vazio de envios com filtro não diz 'ainda' como se nunca tivesse havido envio", async ({ page }) => {
    await aba(page, "Envios realizados").click();
    await expect(tabela(page).locator("tbody tr").first()).toBeVisible();
    await page.locator("select").first().selectOption({ label: "11 A 20" });
    await expect(page.getByText("Carregando...")).toHaveCount(0);
    await expect(page.locator(".empty-state")).toBeVisible();
    await expect(page.getByText("Nenhum envio realizado ainda")).toHaveCount(0);
  });

  test("quem pagou: totais, filtro de pagamento e Excel", { tag: ["@pagamentos"] }, async ({ page }) => {
    await aba(page, "Quem pagou").click();
    await expect(page.getByText("Pago de")).toBeVisible();
    await expect(page.locator(".stat", { hasText: "Clientes que pagaram" })).toBeVisible({ timeout: 30_000 });
    const n = Number((await page.locator(".stat", { hasText: "Clientes que pagaram" }).locator(".value").innerText()).replace(/\./g, ""));
    expect(n).toBeGreaterThan(0);
    await expect(tabela(page).locator("tbody tr")).toHaveCount(n);
    const { linhas } = await baixar(page, () => page.getByRole("button", { name: /Baixar Excel/ }).click());
    expect(linhas.length).toBeGreaterThan(1);
    const inputs = page.locator('input[type="date"]');
    await inputs.nth(2).fill("2020-01-01");
    await inputs.nth(3).fill("2020-01-02");
    await expect(page.getByText("Ninguém pagou no período")).toBeVisible({ timeout: 30_000 });
  });

  test("quem pagou: janela da URL fora da lista abre em Outro e trocar a janela vai para a URL", { tag: ["@pagamentos"] }, async ({ page }) => {
    await page.goto("/relatorios?aba=pagamentos&dias_janela=10");
    await expect(page.getByLabel("Janela de pagamento")).toHaveValue("outro");
    await expect(page.getByLabel("Dias (0–365)")).toHaveValue("10");
    await page.getByLabel("Janela de pagamento").selectOption({ label: "Até 3 dias" });
    await expect(page).toHaveURL(/dias_janela=3(&|$)/);
    await page.getByLabel("Janela de pagamento").selectOption({ label: "Qualquer data após a cobrança" });
    await expect(page).not.toHaveURL(/dias_janela/);
  });

  test("trocar de aba mantém datas e mostra carregando", async ({ page }) => {
    await page.locator('input[type="date"]').first().fill("2020-01-01");
    await page.locator('input[type="date"]').nth(1).fill("2020-01-02");
    await aba(page, "Envios realizados").click();
    await expect(page.locator('input[type="date"]').first()).toHaveValue("2020-01-01");
    await expect(page.getByText("Nenhum envio encontrado com esses filtros")).toBeVisible();
  });

  test("abre direto pela URL na aba e período certos e F5 mantém", async ({ page }) => {
    await page.goto("/relatorios?aba=envios&de=2020-01-01&ate=2020-01-02");
    await expect(aba(page, "Envios realizados")).not.toHaveClass(/secondary/);
    await expect(page.locator('input[type="date"]').first()).toHaveValue("2020-01-01");
    await expect(page.getByText("Nenhum envio encontrado com esses filtros")).toBeVisible();
    await page.reload();
    await expect(page.locator('input[type="date"]').nth(1)).toHaveValue("2020-01-02");
    await aba(page, "Pendentes").click();
    await expect(page).toHaveURL(/aba=pendentes/);
    await page.goBack();
    await expect(page).toHaveURL(/aba=envios/);
  });

  test("pendentes: lista a fila, ordena, exporta com o mesmo total", async ({ page }) => {
    await aba(page, "Pendentes").click();
    await expect(page.getByText("Entrou na fila de")).toBeVisible();
    await expect(page.getByText("Carregando...")).toHaveCount(0);
    const linhasTela = tabela(page).locator("tbody tr");
    await expect(linhasTela.first()).toBeVisible();
    await tabela(page).getByRole("columnheader", { name: /^Código/ }).click();
    await expect(page.getByText("Carregando...")).toHaveCount(0);
    const cods = await tabela(page).locator("tbody tr td:nth-child(1)").allInnerTexts();
    expect(cods).toEqual([...cods].sort());
    const { nome, linhas } = await baixar(page, () => page.getByRole("button", { name: /Baixar Excel/ }).click());
    expect(nome).toBe("relatorio_pendentes.xlsx");
    const total = Number((await page.locator(".paginacao-info").innerText()).match(/de (\d+)/)![1]);
    expect(linhas.length - 1).toBe(total);
  });

  test("erros: mostra a mensagem do erro e exporta", async ({ page }) => {
    await page.goto("/relatorios?aba=erros");
    await expect(tabela(page).locator("tbody tr", { hasText: "Lúcia" })).toContainText("Faltando coluna");
    const { nome, linhas } = await baixar(page, () => page.getByRole("button", { name: /Baixar Excel/ }).click());
    expect(nome).toBe("relatorio_erros.xlsx");
    expect(linhas[0]).toContain("Mensagem de erro");
  });

  test("erro do servidor aparece no topo e some ao trocar de aba com sucesso", async ({ page }) => {
    permitirErrosConsole(page, "500");
    await page.route("**/relatorios/pendentes?*", (r) =>
      r.fulfill({ status: 500, contentType: "application/json", body: JSON.stringify({ detail: "Falha interna" }) })
    );
    await page.reload();
    await expect(page.locator(".error-box")).toContainText("Falha interna");
    await aba(page, "Envios realizados").click();
    await expect(page.locator(".error-box")).toHaveCount(0);
  });
});
