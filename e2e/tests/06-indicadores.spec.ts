import { card, expect, permitirErrosConsole, test } from "./fixtures";

const hoje = new Date();

test.describe("Configurações → Indicadores", { tag: "@indicadores" }, () => {
  test.beforeEach(async ({ page }) => {
    await page.goto("/configuracoes?aba=indicadores");
  });

  test("clusters e faixas padrão carregados; regra do WhatsApp em matriz", async ({ page }) => {
    const r = card(page, "Regras de cobrança");
    await expect(r.getByLabel("Nome do cluster")).toHaveCount(6);
    await expect(r.getByLabel("Nome do cluster").first()).toHaveValue("ESPECIAL");
    await expect(r.getByLabel("Nome da faixa")).toHaveCount(13);
    await expect(r.getByLabel("Dia máximo").last()).toHaveValue("");
    await expect(r.getByLabel("ESPECIAL entra no WhatsApp na faixa 3 A 10")).toBeVisible();
  });

  test("adicionar cluster vazio e salvar mostra erro; remover volta ao normal", async ({ page }) => {
    permitirErrosConsole(page, /4\d\d/);
    const r = card(page, "Regras de cobrança");
    await r.getByRole("button", { name: "Adicionar cluster" }).click();
    await expect(r.getByLabel("Nome do cluster")).toHaveCount(7);
    await r.getByRole("button", { name: "Salvar clusters" }).click();
    await expect(page.locator(".error-box").first()).toBeVisible();
    await r.getByTitle("Remover cluster").last().click();
    await r.getByRole("button", { name: "Salvar clusters" }).click();
    await expect(page.locator(".success-box").first()).toContainText("Clusters salvos");
  });

  test("faixas sobrepostas são recusadas", async ({ page }) => {
    permitirErrosConsole(page, /4\d\d/);
    const r = card(page, "Regras de cobrança");
    await r.getByLabel("Dia máximo").nth(2).fill("15"); // "3 A 10" passa a invadir "11 A 20"
    await r.getByRole("button", { name: "Salvar faixas" }).click();
    await expect(page.locator(".error-box").first()).toBeVisible();
  });

  test("salvar um bloco não descarta o que foi digitado (e não salvo) em outro bloco", async ({ page }) => {
    const r = card(page, "Regras de cobrança");
    await r.getByLabel("Nome da faixa").nth(2).fill("3 A 10 EDITADA");
    await r.getByRole("button", { name: "Salvar clusters" }).click();
    await expect(page.locator(".success-box").first()).toContainText("Clusters salvos");
    await expect(r.getByLabel("Nome da faixa").nth(2)).toHaveValue("3 A 10 EDITADA");
  });

  test("regra do WhatsApp: marcar, salvar e desfazer", async ({ page }) => {
    const r = card(page, "Regras de cobrança");
    const cel = r.getByLabel("HEAVY USER entra no WhatsApp na faixa 151+");
    const antes = await cel.isChecked();
    await cel.setChecked(!antes);
    await r.getByRole("button", { name: "Salvar regra do WhatsApp" }).click();
    await expect(page.locator(".success-box").first()).toContainText("Regra do WhatsApp salva");
    await page.reload();
    await expect(card(page, "Regras de cobrança").getByLabel("HEAVY USER entra no WhatsApp na faixa 151+")).toBeChecked({ checked: !antes });
    await card(page, "Regras de cobrança").getByLabel("HEAVY USER entra no WhatsApp na faixa 151+").setChecked(antes);
    await card(page, "Regras de cobrança").getByRole("button", { name: "Salvar regra do WhatsApp" }).click();
    await expect(page.locator(".success-box").first()).toBeVisible();
  });

  test("juros e multa: texto de carência acompanha o campo, valores fora da faixa são recusados, salvar", async ({ page }) => {
    permitirErrosConsole(page, "400");
    const j = card(page, "Juros e multa");
    await expect(j.getByLabel("Juros ao mês (%)")).not.toHaveValue(""); // espera a config carregar
    await j.getByLabel("Carência (dias de atraso)").fill("5");
    await expect(j).toContainText("mais de 5 dia(s) de atraso (a partir de 6 dias)");
    await j.getByLabel("Multa (%)").fill("150");
    await j.getByRole("button", { name: "Salvar juros e multa" }).click();
    await expect(j.locator(".error-box")).toBeVisible();
    await j.getByLabel("Multa (%)").fill("2");
    await j.getByLabel("Juros ao mês (%)").fill("15.99");
    await j.getByLabel("Carência (dias de atraso)").fill("2");
    await j.getByRole("button", { name: "Salvar juros e multa" }).click();
    await expect(j.locator(".success-box")).toContainText("Juros e multa salvos");
    await expect(j.locator(".error-box")).toHaveCount(0);
  });

  test("juros em branco não deveria virar 0% sem aviso", async ({ page }) => {
    const j = card(page, "Juros e multa");
    await expect(j.getByLabel("Juros ao mês (%)")).not.toHaveValue("");
    await j.getByLabel("Juros ao mês (%)").fill("");
    await j.getByRole("button", { name: "Salvar juros e multa" }).click();
    await expect(j.locator(".error-box")).toBeVisible({ timeout: 3_000 });
  });

  test("restaura juros padrão após o cenário anterior", async ({ page }) => {
    const j = card(page, "Juros e multa");
    await expect(j.getByLabel("Multa (%)")).not.toHaveValue("");
    await j.getByLabel("Juros ao mês (%)").fill("15.99");
    await j.getByRole("button", { name: "Salvar juros e multa" }).click();
    await expect(j.locator(".success-box")).toBeVisible();
  });

  test("orçamento: 12 meses, total do ano e salvar", async ({ page }) => {
    const o = card(page, "Orçamento");
    await expect(o.getByLabel(/Valor orçado para/)).toHaveCount(12);
    const nomes = ["Janeiro", "Fevereiro", "Março", "Abril", "Maio", "Junho", "Julho", "Agosto", "Setembro", "Outubro", "Novembro", "Dezembro"];
    const mesAtual = nomes[hoje.getMonth()];
    await o.getByLabel(`Valor orçado para ${mesAtual}`).fill("100");
    await o.getByLabel(`Valor orçado para ${nomes[(hoje.getMonth() + 1) % 12]}`).fill("50.5");
    await expect(o).toContainText("Total do ano: R$");
    await o.getByRole("button", { name: "Salvar orçamento" }).click();
    await expect(o.locator(".success-box")).toContainText("Orçamento salvo");
    await page.reload();
    await expect(card(page, "Orçamento").getByLabel(`Valor orçado para ${mesAtual}`)).toHaveValue(/^100(\.00?)?$/);
  });

  test("orçamento: valor negativo é recusado", async ({ page }) => {
    permitirErrosConsole(page, /4\d\d/);
    const o = card(page, "Orçamento");
    await o.getByLabel("Valor orçado para Janeiro").fill("-10");
    await o.getByRole("button", { name: "Salvar orçamento" }).click();
    await expect(o.locator(".error-box")).toBeVisible();
  });

  test("orçamento: trocar o ano carrega outro ano sem erros", async ({ page }) => {
    const o = card(page, "Orçamento");
    await o.getByLabel("Ano").fill(String(hoje.getFullYear() + 1));
    await expect(o.getByLabel("Valor orçado para Janeiro")).toHaveValue(/^0(\.00?)?$/);
    await expect(o.locator(".error-box")).toHaveCount(0);
  });
});
