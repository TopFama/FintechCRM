import { apiGet, campo, card, expect, permitirErrosConsole, responderDialogo, test } from "./fixtures";

test.describe("Configurações → Faixas de cobrança", () => {
  test("lista vazia e sincronizar com as faixas de atraso (e de novo, sem duplicar)", async ({ page }) => {
    await page.goto("/configuracoes?aba=faixas");
    await expect(page.getByText("Nenhuma faixa cadastrada")).toBeVisible();
    await page.getByRole("button", { name: "Sincronizar com faixas de atraso" }).click();
    await expect(page.locator(".success-box")).toContainText("13 faixa(s) criada(s)");
    await expect(page.locator(".faixa-row")).toHaveCount(13);
    await expect(page.locator(".faixa-row", { hasText: "3 A 10" })).toContainText("Sem número/template atribuído");
    await expect(page.locator(".faixa-row", { hasText: "3 A 10" }).locator(".status-pill")).toHaveText("Pausado");
    await page.getByRole("button", { name: "Sincronizar com faixas de atraso" }).click();
    await expect(page.locator(".success-box")).toContainText("Todas as faixas de atraso já têm");
    await expect(page.locator(".faixa-row")).toHaveCount(13);
  });

  test("assistente de nova faixa: validação por etapa, voltar e criar", async ({ page }) => {
    await page.goto("/configuracoes?aba=faixas");
    await page.getByRole("button", { name: "Nova faixa" }).first().click();
    await expect(page).toHaveURL("/faixas/nova");
    const proximo = page.getByRole("button", { name: "Próximo" });
    await expect(proximo).toBeDisabled();
    await campo(page, "Nome da faixa").fill("RENEGOCIE");
    await expect(proximo).toBeDisabled();
    await campo(page, "Template aprovado").selectOption({ label: "cobranca_atraso (pt_BR)" });
    await proximo.click();

    await expect(page.getByRole("heading", { name: "Números de envio" })).toBeVisible();
    await expect(proximo).toBeDisabled();
    await page.getByLabel(/Cobrança 01/).check();
    await page.getByRole("button", { name: "Voltar" }).click();
    await expect(campo(page, "Nome da faixa")).toHaveValue("RENEGOCIE");
    await proximo.click();
    await expect(page.getByLabel(/Cobrança 01/)).toBeChecked();
    await proximo.click();

    await expect(page.getByText("Variável interna: variavel_1")).toBeVisible();
    await page.getByRole("button", { name: "Criar faixa" }).click();
    await expect(page).toHaveURL(/\/faixas\/[0-9a-f-]{36}$/);
    await expect(page.getByRole("heading", { level: 2, name: "RENEGOCIE" })).toBeVisible();
    await expect(page.locator("tbody tr", { hasText: "Cobrança 01" })).toContainText("cobranca_atraso");
  });

  test("assistente: nome repetido mostra erro de conflito", async ({ page }) => {
    permitirErrosConsole(page, "409");
    await page.goto("/faixas/nova");
    await campo(page, "Nome da faixa").fill("RENEGOCIE");
    await campo(page, "Template aprovado").selectOption({ index: 1 });
    await page.getByRole("button", { name: "Próximo" }).click();
    await page.locator(".option-item").first().locator("input").check();
    await page.getByRole("button", { name: "Próximo" }).click();
    await page.getByRole("button", { name: "Criar faixa" }).click();
    await expect(page.locator(".error-box")).toContainText("Já existe uma faixa com esse nome");
    await expect(page).toHaveURL("/faixas/nova");
  });

  test("assistente: só oferece templates aprovados (campo diz 'Template aprovado')", async ({ page }) => {
    await page.goto("/faixas/nova");
    await expect(campo(page, "Template aprovado").locator("option")).not.toHaveCount(1);
    const opcoes = await campo(page, "Template aprovado").locator("option").allInnerTexts();
    expect(opcoes.filter((o) => /rejected|draft|pending/.test(o))).toEqual([]);
  });

  test("detalhe da faixa: adicionar envio, pré-visualizar, validar variáveis, editar e remover", async ({ page }) => {
    await page.goto("/configuracoes?aba=faixas");
    await page.locator(".faixa-row", { hasText: "3 A 10" }).getByRole("link").click();
    await expect(page.getByRole("heading", { level: 2, name: "3 A 10" })).toBeVisible();
    await expect(page.getByText("Nenhum número/template atribuído ainda")).toBeVisible();
    await expect(page.getByText("Fila vazia")).toBeVisible();

    await page.getByRole("button", { name: "Adicionar número e template" }).click();
    const form = page.locator(".sub-card");
    const salvar = form.getByRole("button", { name: "Salvar envio" });
    await expect(salvar).toBeDisabled();
    await campo(form, "Número de envio").selectOption({ label: "Cobrança 01 (+55 11 4000-0001)" });
    // só templates aprovados no seletor
    const templates = await campo(form, "Template").locator("option").allInnerTexts();
    expect(templates.slice(1).sort()).toEqual(["cobranca_atraso", "lembrete_vencimento"]);
    await campo(form, "Template").selectOption({ label: "lembrete_vencimento" });
    // variável sem campo sugerido fica sem origem → erro ao salvar
    await salvar.click();
    await expect(page.locator(".error-box")).toContainText("Selecione a origem de todas as variáveis");
    await campo(form, "Template").selectOption({ label: "cobranca_atraso" });
    await form.getByRole("button", { name: "Pré-visualizar" }).click();
    await expect(form.locator(".template-preview-bubble")).not.toContainText("campo não escolhido");
    await salvar.click();
    await expect(page.locator(".success-box")).toContainText("Envio adicionado");
    const linha = page.locator("tbody tr", { hasText: "Cobrança 01" });
    await expect(linha).toContainText("cobranca_atraso");
    await expect(linha.locator(".badge")).toHaveText("ativo");

    // número já usado some das opções do próximo envio
    await page.getByRole("button", { name: "Adicionar número e template" }).click();
    const numeros = await campo(form, "Número de envio").locator("option").allInnerTexts();
    expect(numeros.some((n) => n.includes("Cobrança 01"))).toBe(false);
    await form.getByRole("button", { name: "Cancelar" }).click();

    // editar: desativar e reativar
    await linha.getByRole("button", { name: "Editar" }).click();
    await form.getByLabel("Envio ativo (entra na fila e no disparo)").uncheck();
    await form.getByRole("button", { name: "Salvar envio" }).click();
    await expect(page.locator(".success-box")).toContainText("Envio atualizado");
    await expect(linha.locator(".badge")).toHaveText("inativo");
    await linha.getByRole("button", { name: "Editar" }).click();
    await form.getByLabel("Envio ativo (entra na fila e no disparo)").check();
    await form.getByRole("button", { name: "Salvar envio" }).click();
    await expect(linha.locator(".badge")).toHaveText("ativo");

    // remover (cancelado)
    const msg = responderDialogo(page, false);
    await linha.locator("button.danger").click();
    expect(await msg).toContain("Remover Cobrança 01 (cobranca_atraso) desta faixa?");
    await expect(linha).toBeVisible();
  });

  test("detalhe: mensagem de erro some depois de um salvamento bem-sucedido", async ({ page }) => {
    await page.goto("/configuracoes?aba=faixas");
    await page.locator(".faixa-row", { hasText: "11 A 20" }).getByRole("link").click();
    await page.getByRole("button", { name: "Adicionar número e template" }).click();
    const form = page.locator(".sub-card");
    await campo(form, "Número de envio").selectOption({ label: "Lembrete 02 (+55 11 4000-0002)" });
    await campo(form, "Template").selectOption({ label: "lembrete_vencimento" });
    await form.getByRole("button", { name: "Salvar envio" }).click();
    await expect(page.locator(".error-box")).toBeVisible();
    await campo(form, "Template").selectOption({ label: "cobranca_atraso" });
    await form.getByRole("button", { name: "Salvar envio" }).click();
    await expect(page.locator(".success-box")).toContainText("Envio adicionado");
    await expect(page.locator(".error-box")).toHaveCount(0);
  });

  test("detalhe de faixa inexistente mostra erro em vez de carregar para sempre", async ({ page }) => {
    permitirErrosConsole(page, /40[04]|422/);
    await page.goto("/faixas/00000000-0000-0000-0000-000000000000");
    await expect(page.getByText(/não encontrada|erro/i)).toBeVisible({ timeout: 8_000 });
  });

  test("detalhe: link de voltar leva para a lista de faixas em Configurações", async ({ page }) => {
    const faixas = await apiGet(page, "/faixas");
    await page.goto(`/faixas/${faixas.find((f: any) => f.name === "RENEGOCIE").id}`);
    await page.getByRole("link", { name: "← Faixas de cobrança" }).click();
    await expect(page).toHaveURL("/configuracoes?aba=faixas");
  });

  test("excluir faixa: cancelar mantém, confirmar remove", async ({ page }) => {
    await page.goto("/configuracoes?aba=faixas");
    const linha = page.locator(".faixa-row", { hasText: "RENEGOCIE" });
    let msg = responderDialogo(page, false);
    await linha.getByTitle("Excluir faixa").click();
    expect(await msg).toContain('Excluir a faixa "RENEGOCIE"?');
    await expect(linha).toBeVisible();
    msg = responderDialogo(page, true);
    await linha.getByTitle("Excluir faixa").click();
    await msg;
    await expect(linha).toHaveCount(0);
  });
});
