import { apiGet, campo, card, expect, permitirErrosConsole, test } from "./fixtures";

test.describe("Configurações → Templates", () => {
  test.beforeEach(async ({ page }) => {
    await page.goto("/configuracoes?aba=templates");
  });

  test("sincronizar com a Meta traz os templates e mostra o status", async ({ page }) => {
    await expect(page.getByText("Nenhum template cadastrado")).toBeVisible();
    await page.getByRole("button", { name: "Sincronizar", exact: true }).click();
    const tabela = card(page, "Templates cadastrados");
    await expect(tabela.locator("tbody tr")).toHaveCount(3);
    await expect(tabela.locator("tbody tr", { hasText: "cobranca_atraso" })).toContainText("variavel_1, variavel_2, variavel_3, variavel_4");
    await expect(tabela.locator("tbody tr", { hasText: "promo_reprovada" }).locator(".badge")).toHaveText(/rejected|reprovado/i);
  });

  test("ordenar a tabela por nome e por status", async ({ page }) => {
    const tabela = card(page, "Templates cadastrados");
    const nomes = () => tabela.locator("tbody tr td:first-child").allInnerTexts();
    await tabela.getByRole("columnheader", { name: /Nome/ }).click();
    const asc = await nomes();
    expect(asc).toEqual([...asc].sort((a, b) => a.localeCompare(b)));
    await tabela.getByRole("columnheader", { name: /Nome/ }).click();
    expect(await nomes()).toEqual([...asc].reverse());
  });

  test("pré-visualizar e mapear variável para campo do cliente", async ({ page }) => {
    const tabela = card(page, "Templates cadastrados");
    const linha = tabela.locator("tbody tr", { hasText: "cobranca_atraso" });
    await linha.getByRole("button", { name: "Pré-visualizar" }).click();
    const bolha = tabela.locator(".template-preview-bubble");
    await expect(bolha).toContainText("(não mapeado)");
    const sel = campo(tabela, "{{1}} (variavel_1)");
    const opcoes = await sel.locator("option").allInnerTexts();
    expect(opcoes.length).toBeGreaterThan(2);
    await sel.selectOption({ label: opcoes.find((o) => /nome/i.test(o))! });
    await expect(bolha).not.toContainText("{{1}} (não mapeado)");
    // persistiu no backend
    const t = (await apiGet(page, "/templates")).find((x: any) => x.name === "cobranca_atraso" || x.meta_template_name === "cobranca_atraso");
    expect(t.variables.find((v: any) => v.position === 1).campo_sugerido).toBeTruthy();
    await linha.getByRole("button", { name: "Fechar" }).click();
    await expect(bolha).toHaveCount(0);
  });

  test("mapeia todas as variáveis do template de cobrança (usado nas próximas etapas)", async ({ page }) => {
    const tabela = card(page, "Templates cadastrados");
    await tabela.locator("tbody tr", { hasText: "cobranca_atraso" }).getByRole("button", { name: "Pré-visualizar" }).click();
    const alvo: [number, RegExp][] = [[2, /valor/i], [3, /vencimento/i], [4, /c[óo]digo/i]];
    for (const [pos, re] of alvo) {
      const sel = campo(tabela, `{{${pos}}} (variavel_${pos})`);
      const rotulo = (await sel.locator("option").allInnerTexts()).find((o) => re.test(o));
      expect(rotulo, `campo para {{${pos}}}`).toBeTruthy();
      await sel.selectOption({ label: rotulo! });
    }
    await expect(tabela.locator(".template-preview-bubble")).not.toContainText("não mapeado");
  });

  test("criar template: detecta variáveis, valida obrigatórios e cancela", async ({ page }) => {
    const novo = card(page, "Novo template");
    await novo.getByRole("button", { name: "Criar template" }).click();
    await campo(novo, /Corpo do template/).fill("Olá {{1}}, pague {{2}} até {{1}}.");
    await expect(novo.getByText("Variáveis detectadas: variavel_1, variavel_2")).toBeVisible();
    await novo.getByRole("button", { name: "Salvar template" }).click();
    expect(await campo(novo, "Nome interno").evaluate((e: HTMLInputElement) => e.validity.valid)).toBe(false);
    await novo.getByRole("button", { name: "Cancelar" }).click();
    await expect(novo.getByRole("button", { name: "Salvar template" })).toHaveCount(0);
  });

  test("criar template local (rascunho) e enviar outro para análise na Meta", async ({ page }) => {
    const novo = card(page, "Novo template");
    await novo.getByRole("button", { name: "Criar template" }).click();
    await campo(novo, "Nome interno").fill("Rascunho teste");
    await campo(novo, /Nome do template na Meta/).fill("rascunho_teste");
    await campo(novo, /Corpo do template/).fill("Oi {{1}}");
    await novo.getByRole("button", { name: "Salvar template" }).click();
    const tabela = card(page, "Templates cadastrados");
    await expect(tabela.locator("tbody tr", { hasText: "Rascunho teste" }).locator(".badge")).toHaveText(/draft|rascunho/i);

    await novo.getByRole("button", { name: "Criar template" }).click();
    await campo(novo, "Nome interno").fill("Enviado Meta");
    await campo(novo, /Nome do template na Meta/).fill("enviado_meta");
    await campo(novo, /Corpo do template/).fill("Oi {{1}}, sua fatura {{2}}");
    await novo.getByLabel("Enviar já para análise na Meta").check();
    await novo.getByRole("button", { name: "Salvar template" }).click();
    const linha = tabela.locator("tbody tr", { hasText: "Enviado Meta" });
    await expect(linha.locator(".badge")).toHaveText(/pending|pendente/i);
    await linha.getByRole("button", { name: "Atualizar status" }).click();
    await expect(linha.locator(".badge")).toHaveText(/pending|pendente/i);
  });

  test("atualizar status de template nunca enviado à Meta mostra erro", async ({ page }) => {
    permitirErrosConsole(page, "400");
    const linha = card(page, "Templates cadastrados").locator("tbody tr", { hasText: "Rascunho teste" });
    await linha.getByRole("button", { name: "Atualizar status" }).click();
    await expect(page.locator(".error-box").first()).toContainText("não foi submetido");
  });

  test("falha na sincronização aparece como erro e o botão volta ao normal", async ({ page }) => {
    permitirErrosConsole(page, "400");
    await page.route("**/templates/meta/sync", (r) =>
      r.fulfill({ status: 400, contentType: "application/json", body: JSON.stringify({ detail: "Nenhuma WABA sincronizou — WABA 1: token expirado" }) })
    );
    await page.getByRole("button", { name: "Sincronizar", exact: true }).click();
    await expect(page.locator(".error-box").first()).toContainText("token expirado");
    await expect(page.getByRole("button", { name: "Sincronizar", exact: true })).toBeEnabled();
  });
});

test.describe("Conexões → Chatwoot: testar envio de template", () => {
  test("envia teste e mostra o resultado; botão só libera com tudo preenchido", async ({ page }) => {
    await page.goto("/configuracoes?aba=conexoes");
    const cw = card(page, "Chatwoot");
    const enviar = cw.getByRole("button", { name: "Enviar teste" });
    await expect(enviar).toBeDisabled();
    await campo(cw, "Template").selectOption({ label: "cobranca_atraso" });
    await expect(cw.locator(".template-preview-bubble")).toBeVisible();
    await campo(cw, "Número de origem").selectOption({ index: 1 });
    await expect(enviar).toBeDisabled();
    await campo(cw, "Celular de destino").fill("5511999990000");
    await expect(enviar).toBeEnabled();
    await enviar.click();
    await expect(cw.locator(".field-success, .field-error")).toBeVisible();
    await expect(cw.locator(".field-success")).toBeVisible();
    const envios = await apiGet(page, "/__e2e/envios");
    expect(envios.some((e: any) => e.canal === "chatwoot")).toBeTruthy();
  });
});
