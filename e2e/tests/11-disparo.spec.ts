import { apiGet, card, expect, test } from "./fixtures";

test.describe("Disparo pelo worker (Meta simulada)", () => {
  test("faixa com disparo ativo: itens da fila passam para enviado na tela, sem recarregar", async ({ page }) => {
    const f = (await apiGet(page, "/faixas")).find((x: any) => x.name === "3 A 10");
    await page.goto(`/faixas/${f.id}`);
    await expect(page.locator(".status-pill").first()).toHaveText("Agendado");
    const fila = card(page, "Fila desta faixa");
    await expect(fila.locator("tbody tr").first()).toBeVisible();
    // a fila se atualiza sozinha a cada 4s; o worker roda a cada 2s no ambiente de teste
    await expect(fila.locator("tbody .badge", { hasText: /sent|enviad/ }).first()).toBeVisible({ timeout: 45_000 });
    await expect(fila.locator("tbody .badge", { hasText: /pending|pendente/ })).toHaveCount(0, { timeout: 45_000 });
  });

  test("mensagens saíram (Chatwoot simulado, pois o número tem inbox) com o template e as variáveis preenchidas", async ({ page }) => {
    // "Cobrança 01" tem inbox do Chatwoot (cenário de Conexões), então o envio vai pelo Chatwoot
    const envios = (await apiGet(page, "/__e2e/envios")).filter(
      (e: any) => e.canal === "chatwoot" && !String(e.template_params?.processed_params?.body?.["1"]).startsWith("Maria da Silva")
    ); // ignora o "Enviar teste" da tela de Conexões
    expect(envios.length).toBeGreaterThan(0);
    for (const e of envios) {
      expect(e.template_params.name).toBe("cobranca_atraso");
      const params = Object.values(e.template_params.processed_params.body) as string[];
      expect(params).toHaveLength(4);
      for (const p of params) expect(p).not.toMatch(/^(None|null|undefined|)$/);
    }
    expect((await apiGet(page, "/__e2e/envios")).filter((e: any) => e.canal === "meta")).toEqual([]);
  });

  test("faixa com disparo pausado não envia nada", async ({ page }) => {
    const f = (await apiGet(page, "/faixas")).find((x: any) => x.name === "11 A 20");
    const fila = await apiGet(page, `/faixas/${f.id}/queue?limit=100&offset=0`);
    // o item com erro de importação (variável em branco) nunca é enviado
    expect(fila.itens.filter((i: any) => i.status !== "error").every((i: any) => i.status === "pending")).toBe(true);
  });

  test("mesmo cliente não é cobrado duas vezes no dia ao reenviar para a fila", async ({ page }) => {
    const antes = (await apiGet(page, "/__e2e/envios")).length;
    await page.goto("/cobranca");
    const filtros = card(page, "Filtros");
    await filtros.locator(".field", { hasText: "Faixa de atraso" }).locator(".ms-btn").click();
    await filtros.getByRole("option", { name: "3 A 10", exact: true }).locator("input").check();
    await filtros.locator(".field", { hasText: "Faixa de atraso" }).locator(".ms-btn").click();
    await filtros.getByLabel("Somente o primeiro dia da faixa").uncheck();
    await filtros.getByLabel("Somente clientes da regra WhatsApp").uncheck();
    await filtros.getByRole("button", { name: "Aplicar filtros" }).click();
    await expect(page.getByText("Consultando o SETA")).toHaveCount(0, { timeout: 30_000 });
    page.once("dialog", (d) => d.accept());
    await filtros.getByRole("button", { name: "Enviar para fila de cobrança" }).click();
    await expect(filtros.locator(".success-box, .error-box")).toBeVisible({ timeout: 30_000 });
    await page.waitForTimeout(8_000); // algumas voltas do worker
    expect((await apiGet(page, "/__e2e/envios")).length).toBe(antes);
  });
});
