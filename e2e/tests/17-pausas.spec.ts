import { apiGet, expect, test } from "./fixtures";
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
    // item da régua 11 A 20: o de remarketing que o cenário anterior pôs na fila pode ser enviado pelo worker a qualquer momento
    const linha = tabela(page).locator("tbody tr", { hasText: "11 A 20" }).first();
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

  test("Pausar faixa: lista as faixas da fila, pausa as marcadas e oferece editar e aplicar variáveis", async ({ page }) => {
    await page.getByRole("button", { name: "Pausar faixa" }).click();
    const painel = page.getByRole("dialog");
    const opcao = painel.locator("li", { hasText: "11 A 20" });
    await expect(opcao).toContainText(/\d+ pendente\(s\)/);
    const botao = painel.getByRole("button", { name: /^Pausar \d+ faixa/ });
    await expect(botao).toBeDisabled();
    await opcao.getByRole("checkbox").check();
    await painel.getByLabel("Motivo").fill("Corrigir variáveis do template");
    const amanha = new Date(Date.now() + 86_400_000).toLocaleDateString("sv-SE");
    await painel.getByLabel("Até (opcional)").fill(amanha);
    await expect(botao).toHaveText(/Pausar 1 faixa\(s\) · \d+ pendente\(s\)/);
    await botao.click();
    await expect(page.locator(".success-box")).toContainText("1 faixa(s) pausada(s): 11 A 20");
    const linhaPausa = blocoPausas(page).locator("tbody tr", { hasText: "Régua" });
    await expect(linhaPausa).toContainText("11 A 20");
    const itensFaixa = tabela(page).locator("tbody tr", { hasText: "11 A 20" });
    // A tabela pode ainda estar recarregando: espera ter itens pausados e nenhum item da faixa sem o selo.
    await expect(itensFaixa.locator(".badge.pausado").first()).toBeVisible();
    await expect(itensFaixa.filter({ hasNot: page.locator(".badge.pausado") })).toHaveCount(0);
    // já pausada aparece desabilitada numa segunda tentativa
    await page.getByRole("button", { name: "Pausar faixa" }).click();
    await expect(page.getByRole("dialog").locator("li", { hasText: "11 A 20" })).toContainText("já pausada");
    await expect(page.getByRole("dialog").locator("li", { hasText: "11 A 20" }).getByRole("checkbox")).toBeDisabled();
    await page.getByRole("dialog").getByRole("button", { name: "Cancelar" }).click();
    // editar variáveis leva para a faixa; aplicar atualiza os pendentes com o mapeamento atual
    await expect(linhaPausa.getByRole("link", { name: "Editar variáveis" })).toHaveAttribute("href", /\/faixas\/.+/);
    await linhaPausa.getByRole("button", { name: /Aplicar variáveis atuais/ }).click();
    await expect(page.locator(".success-box")).toContainText("Variáveis atuais aplicadas a");
    await linhaPausa.getByRole("button", { name: "Retomar 11 A 20" }).click();
    await expect(blocoPausas(page)).toHaveCount(0);
  });

  test("Pausar loja: marcar todas pausa cada loja com pendentes; retomar", async ({ page }) => {
    await page.getByRole("button", { name: "Pausar loja" }).click();
    const painel = page.getByRole("dialog");
    await expect(painel.locator("li").first()).toBeVisible();
    const n = await painel.locator("li").count();
    await painel.getByRole("button", { name: "Marcar todas" }).click();
    await painel.getByLabel("Motivo").fill("Mutirão nas lojas");
    await painel.getByRole("button", { name: new RegExp(`^Pausar ${n} loja`) }).click();
    await expect(page.locator(".success-box")).toContainText(`${n} loja(s) pausada(s)`);
    await expect(blocoPausas(page).locator("tbody tr", { hasText: "Mutirão nas lojas" })).toHaveCount(n);
    const pausasLoja = blocoPausas(page).locator("tbody tr", { hasText: "Mutirão nas lojas" });
    for (let i = 0; i < n; i++) {
      await pausasLoja.first().getByRole("button", { name: /^Retomar/ }).click();
      // espera a linha sumir antes do próximo clique; senão o clique pode cair na mesma pausa
      await expect(pausasLoja).toHaveCount(n - i - 1);
    }
    await expect(blocoPausas(page)).toHaveCount(0);
  });

  test("parar pede confirmação na tela com a quantidade e tira o item dos pendentes", async ({ page }) => {
    const total = async () => Number((await page.locator(".paginacao-info").innerText()).match(/de (\d+)/)![1]);
    const antes = await total();
    // item da régua 11 A 20: o de remarketing que o cenário anterior pôs na fila pode ser enviado pelo worker a qualquer momento
    const linha = tabela(page).locator("tbody tr", { hasText: "11 A 20" }).first();
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
    await expect.poll(total).toBe(antes - 1); // o total da paginação recarrega depois da linha
  });

  test("descartar fila tira da fila os pendentes do filtro, sem registro de parado", async ({ page }) => {
    const primeiro = (await apiGet(page, "/reports/pendentes?limit=1&offset=0")).itens[0];
    const daFaixa = await apiGet(page, `/reports/pendentes?faixa_id=${primeiro.faixa_id}&limit=500&offset=0`);
    await page.goto(`/relatorios?aba=pendentes&faixa_id=${primeiro.faixa_id}`);
    await page.getByRole("button", { name: "Descartar fila" }).click();
    const confirmar = page.getByRole("alertdialog");
    await expect(confirmar).toContainText("Descartar a fila (os pendentes com os filtros desta tela)?");
    await expect(confirmar).toContainText("Diferente de Parar");
    const botao = confirmar.getByRole("button", { name: /^Descartar \d+ pendente\(s\)$/ });
    await expect(botao).toBeEnabled();
    const qtd = Number((await botao.innerText()).match(/\d+/)![0]);
    expect(qtd).toBeGreaterThan(0);
    expect(qtd).toBeLessThanOrEqual(daFaixa.total);
    await botao.click();
    await expect(page.locator(".success-box")).toContainText(`Fila descartada: ${qtd} pendente(s) saíram da fila.`);
    await expect
      .poll(async () => (await apiGet(page, `/reports/pendentes?faixa_id=${primeiro.faixa_id}&limit=1&offset=0`)).total)
      .toBeLessThanOrEqual(daFaixa.total - qtd);
  });
});
