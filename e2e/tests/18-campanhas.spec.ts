import path from "node:path";
import { fileURLToPath } from "node:url";
import type { Page } from "@playwright/test";
import { API_URL } from "./ambiente";
import { apiGet, apiSend, card, expect, responderDialogo, test } from "./fixtures";

const DADOS = path.join(path.dirname(fileURLToPath(import.meta.url)), "dados");
const SCREENSHOTS = process.env.E2E_SCREENSHOTS;

async function foto(page: Page, nome: string) {
  if (SCREENSHOTS) await page.screenshot({ path: path.join(SCREENSHOTS, `${nome}.png`), fullPage: true });
}

async function garantirNumero(page: Page) {
  if ((await apiGet(page, "/numbers")).length === 0) {
    const token = await apiSend(page, "POST", "/meta-tokens", {
      nome: "Token Campanhas",
      token: "EAA-token-campanhas-1234",
      waba_id: "1111111111",
    });
    expect(token.status).toBe(201);
    const r = await apiSend(page, "POST", `/meta-tokens/${token.corpo.id}/importar-numeros`, { phone_number_ids: ["900001"] });
    expect(r.status).toBe(200);
  }
  if (!(await apiGet(page, "/templates")).some((t: any) => t.name === "lembrete_vencimento")) {
    expect((await apiSend(page, "POST", "/templates/meta/sync?waba_id=1111111111")).status).toBe(200);
  }
}

async function atribuirTemplate(page: Page, template: string, origem: string) {
  const bloco = card(page, "Template e número da campanha");
  await bloco.getByRole("button", { name: "Adicionar número e template" }).click();
  await bloco.getByLabel("Número de envio").selectOption({ index: 1 });
  await bloco.locator("#faixa-template").selectOption({ label: template });
  await bloco.locator("select[id^='faixa-var-']").first().selectOption({ label: origem });
  await bloco.getByRole("button", { name: "Salvar envio" }).click();
  await expect(bloco.locator(".success-box")).toContainText("Envio adicionado");
}

// SETA falso: lojas 01 e 06 com valor em atraso (com juros) entre 200 e 900 são
// 00000025, 23, 21, 15, 33, 13, 31, 09, 07 e 05 (21 e 07 sem celular).
test.describe.serial("Campanhas", () => {
  test("menu: Campanhas logo abaixo de Cobrança, Remarketing vira aba", async ({ page }) => {
    await page.goto("/");
    const itens = await page.locator(".nav-link").allInnerTexts();
    const i = itens.findIndex((t) => t.includes("Cobrança"));
    expect(itens[i + 1]).toContain("Campanhas");
    expect(itens.join(" ")).not.toContain("Remarketing");

    await page.goto("/remarketing");
    await expect(page).toHaveURL(/\/campanhas\?aba=remarketing/);
    await expect(card(page, "Remarketing do Renegocie")).toBeVisible();
    await foto(page, "campanhas-remarketing");
  });

  test("cria a campanha com lojas importadas e filtro de valor em atraso", async ({ page }) => {
    await garantirNumero(page);
    await page.goto("/campanhas");
    await page.getByRole("button", { name: "Nova campanha" }).click();
    await page.getByLabel("Nome da campanha").fill("Feirão lojas 01 e 06");

    await page.locator('input[aria-label="Planilha de lojas"]').setInputFiles(path.join(DADOS, "lojas_campanha.xlsx"));
    await expect(page.getByRole("status")).toContainText("2 loja(s) marcada(s). Não encontrei na base de lojas: 99");

    await page.getByLabel("Valor em atraso de (R$)").fill("200");
    await page.getByLabel("Valor em atraso até (R$)").fill("900");
    await page.getByLabel("Valor considerado").selectOption({ label: "Corrigido com multa e juros" });
    await page.getByRole("button", { name: "Criar campanha" }).click();
    await expect(page.getByRole("heading", { name: "Feirão lojas 01 e 06" })).toBeVisible();
    await expect(page.locator(".status-pill").first()).toHaveText("Desligada");

    const campanha = (await apiGet(page, "/campanhas")).find((c: any) => c.nome === "Feirão lojas 01 e 06");
    expect(campanha.filtros.loja).toEqual(["01", "06"]);
    expect(campanha.filtros.valor_atraso_com_juros).toBe(true);
  });

  test("template atribuído na campanha, fora da lista de faixas de atraso", async ({ page }) => {
    const campanha = (await apiGet(page, "/campanhas")).find((c: any) => c.nome === "Feirão lojas 01 e 06");
    await page.goto(`/campanhas/${campanha.id}`);
    await atribuirTemplate(page, "lembrete_vencimento", "Primeiro nome");
    await expect(card(page, "Template e número da campanha").locator("tbody")).toContainText("lembrete_vencimento");

    await page.goto("/configuracoes?aba=faixas");
    await expect(page.locator(".faixa-row", { hasText: "Feirão" })).toHaveCount(0);
    await page.goto("/campanhas");
    await expect(page.locator(".faixa-row", { hasText: "Feirão lojas 01 e 06" })).toContainText("lembrete_vencimento");
    await foto(page, "campanhas-lista");
  });

  test("prévia ordenada no servidor e colocar na fila não repete o cliente", async ({ page }) => {
    const campanha = (await apiGet(page, "/campanhas")).find((c: any) => c.nome === "Feirão lojas 01 e 06");
    await page.goto(`/campanhas/${campanha.id}`);
    const previa = card(page, "Quem entraria agora");
    await previa.getByRole("button", { name: "Ver prévia" }).click();
    await expect(previa).toContainText("10 cliente(s) entrariam");
    await previa.locator("th", { hasText: "Valor a cobrar" }).click();
    await expect(previa.locator("th", { hasText: "Valor a cobrar" })).toHaveAttribute("aria-sort", "ascending");
    const valores = (await previa.locator("tbody tr td:nth-child(4)").allInnerTexts()).map((t) =>
      Number(t.replace(/[^\d,]/g, "").replace(",", ".")),
    );
    expect(valores).toEqual([...valores].sort((x, y) => x - y));
    await foto(page, "campanha-detalhe");

    const confirmou = responderDialogo(page);
    await previa.getByRole("button", { name: "Colocar na fila agora" }).click();
    await confirmou;
    await expect(page.locator(".success-box", { hasText: "encontrado" })).toContainText(/\d+ cliente\(s\) colocado\(s\) na fila \(de 10 encontrado\(s\)\)/);

    const fila = await apiGet(page, `/faixas/${campanha.faixa_id}/queue?limit=100&offset=0`);
    const codigos = fila.itens.map((i: any) => i.codigo_cliente);
    expect(codigos).not.toContain("00000021"); // sem celular
    expect(codigos).not.toContain("00000027"); // loja 06, mas valor acima de 900

    await previa.getByRole("button", { name: "Ver prévia" }).click();
    await expect(previa).toContainText(`${10 - codigos.length} cliente(s) entrariam`);
  });

  test("planilha de clientes com os valores da planilha nas variáveis", async ({ page }) => {
    await page.goto("/campanhas/nova");
    await page.getByLabel("Nome da campanha").fill("Planilha promo");
    await page.getByRole("button", { name: "Criar campanha" }).click();
    await expect(page.getByRole("heading", { name: "Planilha promo" })).toBeVisible();

    await page.locator('input[aria-label="Planilha de clientes"]').setInputFiles(path.join(DADOS, "clientes_campanha.xlsx"));
    await expect(page.locator(".success-box")).toContainText("coluna Código: 3 cliente(s), 1 linha(s) sem cliente");
    await page.getByLabel("Valor, celular e variáveis vêm").selectOption("planilha");
    await page.getByLabel("Frequência").selectOption("recorrente");
    await page.getByLabel("Início").fill("2026-01-01");
    await page.getByRole("button", { name: "Salvar" }).click();
    await expect(page.locator(".success-box")).toContainText("Campanha salva");

    await atribuirTemplate(page, "lembrete_vencimento", "Obs");
    const previa = card(page, "Quem entraria agora");
    await previa.getByRole("button", { name: "Ver prévia" }).click();
    await expect(previa).toContainText("2 cliente(s) entrariam"); // 99999 não existe no SETA
    await expect(previa.locator("tbody")).toContainText("R$ 99,90");

    const confirmou = responderDialogo(page);
    await previa.getByRole("button", { name: "Colocar na fila agora" }).click();
    await confirmou;
    await expect(page.locator(".success-box", { hasText: "encontrado" })).toContainText("2 cliente(s) colocado(s) na fila (de 2 encontrado(s))");

    const campanha = (await apiGet(page, "/campanhas")).find((c: any) => c.nome === "Planilha promo");
    const fila = await apiGet(page, `/faixas/${campanha.faixa_id}/queue?limit=100&offset=0`);
    const item = fila.itens.find((i: any) => i.codigo_cliente === "00000027");
    if (item) {
      expect(item.valor).toBe("99.90");
      expect(item.status).toBe("pending");
    }
  });

  test("excluir arquiva a campanha e mantém o histórico", async ({ page }) => {
    const campanha = (await apiGet(page, "/campanhas")).find((c: any) => c.nome === "Planilha promo");
    await page.goto(`/campanhas/${campanha.id}`);
    const confirmou = responderDialogo(page);
    await page.getByRole("button", { name: "Excluir campanha" }).click();
    await confirmou;
    await expect(page).toHaveURL(/\/campanhas$/);
    await expect(page.locator(".faixa-row", { hasText: "Planilha promo" })).toHaveCount(0);
    expect((await page.request.get(`${API_URL}/campanhas/${campanha.id}`)).status()).toBe(404);
  });
});
