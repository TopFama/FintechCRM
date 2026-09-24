import { expect, test } from "./fixtures";
import type { Page } from "@playwright/test";

// Roda depois da importação/disparo: a fila de hoje ainda tem pendentes da faixa 11 A 20.
const tabela = (page: Page) => page.locator(".card table").last();
const blocoPausas = (page: Page) => page.locator("section.pausas-ativas");
const resumo = (page: Page) => page.getByText(/pendente\(s\) · \d+ pausado\(s\)/);

test.describe.serial("Pendentes: pausar, retomar e parar", () => {
  test.beforeEach(async ({ page }) => {
    await page.goto("/relatorios?aba=pendentes");
    await expect(page.getByText("Carregando...")).toHaveCount(0);
  });

  test("pausar um cliente pede motivo, mostra o bloco de pausas e o badge; retomar desfaz", async ({ page }) => {
    const linha = tabela(page).locator("tbody tr").first();
    const codigo = (await linha.locator("td").first().innerText()).trim();
    await linha.getByRole("button", { name: "Pausar cliente" }).click();
    const painel = page.getByRole("dialog");
    await expect(painel).toContainText(`Pausar o envio para o cliente ${codigo}`);
    await expect(painel.getByRole("button", { name: "Pausar" })).toBeDisabled();
    await painel.getByLabel("Motivo").fill("Cliente vai negociar na loja");
    await painel.getByRole("button", { name: "Pausar" }).click();
    await expect(page.locator(".success-box")).toContainText(`Envio pausado para o cliente ${codigo}`);
    const pausas = blocoPausas(page);
    await expect(pausas.locator("tbody tr")).toHaveCount(1);
    await expect(pausas).toContainText("Cliente vai negociar na loja");
    await expect(pausas).toContainText("admin@topfama.com.br");
    await expect(pausas).toContainText("Sem data");
    await expect(tabela(page).locator("tbody tr", { hasText: codigo }).locator(".badge.pausado")).toHaveText("Pausado");
    await expect(resumo(page)).toContainText("· 1 pausado(s)");

    // O card do Dashboard conta o mesmo pausado
    await page.goto("/");
    await expect(page.locator("a.stat-link").first()).toContainText(/pendentes · 1 pausados/);
    await page.goto("/relatorios?aba=pendentes");

    await blocoPausas(page).getByRole("button", { name: /^Retomar/ }).click();
    await expect(page.locator(".success-box")).toContainText("Envio retomado");
    await expect(blocoPausas(page)).toHaveCount(0);
    await expect(tabela(page).locator(".badge.pausado")).toHaveCount(0);
  });

  test("com faixa filtrada: pausar esta régua (com data final) segura todos os itens dela", async ({ page }) => {
    await page.getByLabel("Faixa", { exact: true }).selectOption({ label: "11 A 20" });
    await expect(page).toHaveURL(/faixa_id=/);
    await expect(page.getByText("Carregando...")).toHaveCount(0);
    const n = await tabela(page).locator("tbody tr").count();
    await page.getByRole("button", { name: "Pausar esta régua" }).click();
    const painel = page.getByRole("dialog");
    await expect(painel).toContainText("a régua 11 A 20");
    await painel.getByLabel("Motivo").fill("Revisar o template");
    const amanha = new Date(Date.now() + 86_400_000).toLocaleDateString("sv-SE");
    await painel.getByLabel("Até (opcional)").fill(amanha);
    await painel.getByRole("button", { name: "Pausar" }).click();
    const pausas = blocoPausas(page);
    await expect(pausas.locator("tbody tr", { hasText: "Régua" })).toContainText("11 A 20");
    await expect(tabela(page).locator(".badge.pausado")).toHaveCount(n);
    await pausas.getByRole("button", { name: "Retomar 11 A 20" }).click();
    await expect(blocoPausas(page)).toHaveCount(0);
  });

  test("com loja filtrada: botões da loja aparecem e a pausa mostra o nome da loja", async ({ page }) => {
    const loja = page.getByLabel("Loja", { exact: true });
    await expect(loja.locator("option").nth(1)).toBeAttached();
    await loja.selectOption({ index: 1 });
    await expect(page).toHaveURL(/loja=/);
    await expect(page.getByRole("button", { name: "Parar esta loja" })).toBeVisible();
    await page.getByRole("button", { name: "Pausar esta loja" }).click();
    await page.getByRole("dialog").getByLabel("Motivo").fill("Mutirão na loja");
    await page.getByRole("dialog").getByRole("button", { name: "Pausar" }).click();
    const pausas = blocoPausas(page);
    await expect(pausas.locator("tbody tr", { hasText: "Loja" })).toContainText("Mutirão na loja");
    await pausas.getByRole("button", { name: /^Retomar/ }).click();
    await expect(blocoPausas(page)).toHaveCount(0);
  });

  test("parar pede confirmação na tela com a quantidade e tira o item dos pendentes", async ({ page }) => {
    const total = async () => Number((await page.locator(".paginacao-info").innerText()).match(/de (\d+)/)![1]);
    const antes = await total();
    const linha = tabela(page).locator("tbody tr").first();
    const codigo = (await linha.locator("td").first().innerText()).trim();
    await linha.getByRole("button", { name: `Parar ${codigo}` }).click();
    const confirmar = page.getByRole("alertdialog");
    await expect(confirmar).toContainText(`Parar o envio para o cliente ${codigo}`);
    await expect(confirmar).toContainText("1 pendente(s) serão cancelados");
    await confirmar.getByRole("button", { name: "Cancelar" }).click();
    await expect(page.getByRole("alertdialog")).toHaveCount(0);
    await linha.getByRole("button", { name: `Parar ${codigo}` }).click();
    await page.getByRole("alertdialog").getByRole("button", { name: "Parar 1 envio(s)" }).click();
    await expect(page.locator(".success-box")).toContainText(`Envio parado para o cliente ${codigo}`);
    await expect(page.locator(".success-box")).toContainText("1 pendente(s) cancelado(s)");
    await expect(tabela(page).locator("tbody tr", { hasText: codigo })).toHaveCount(0);
    expect(await total()).toBe(antes - 1);
  });
});
