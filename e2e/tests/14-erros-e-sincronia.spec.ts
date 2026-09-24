import { card, expect, permitirErrosConsole, responderDialogo, test } from "./fixtures";

// Cenários de resiliência da tela: erro de rede some quando a próxima chamada dá certo,
// e cards que dependem uns dos outros ficam em sincronia. Roda por último porque exclui o token.

test.describe("Erros e sincronia entre cards", () => {
  test("Dashboard: erro do resumo some quando o próximo período carrega", async ({ page }) => {
    permitirErrosConsole(page, "500");
    let falhar = true;
    await page.route("**/dashboard/summary?*", (r) =>
      falhar ? r.fulfill({ status: 500, contentType: "application/json", body: JSON.stringify({ detail: "Falha temporária" }) }) : r.continue()
    );
    await page.goto("/");
    await expect(page.locator(".error-box", { hasText: "Falha temporária" })).toBeVisible();
    falhar = false;
    await page.locator(".periodo-card", { hasText: "Últimos 7 dias" }).first().click();
    await expect(page.locator(".stat .label", { hasText: "Pendentes na fila" })).toBeVisible();
    await expect(page.locator(".error-box", { hasText: "Falha temporária" })).toHaveCount(0);
  });

  test("Dashboard: resumo com erro não fica preso em 'Carregando'", async ({ page }) => {
    permitirErrosConsole(page, "500");
    await page.route("**/dashboard/summary?*", (r) =>
      r.fulfill({ status: 500, contentType: "application/json", body: JSON.stringify({ detail: "Falha temporária" }) })
    );
    await page.goto("/");
    await expect(page.locator(".error-box", { hasText: "Falha temporária" })).toBeVisible();
    await expect(page.getByText("Carregando resumo da fila...")).toHaveCount(0);
  });

  test("Conexões: inbox informada em Números libera o 'Testar envio' sem recarregar", async ({ page }) => {
    await page.goto("/configuracoes?aba=conexoes");
    const numeros = card(page, "Números de WhatsApp");
    const l2 = numeros.locator("tbody tr", { hasText: "+55 11 4000-0002" });
    await l2.getByRole("button", { name: "Editar" }).click();
    await numeros.getByLabel("ID da inbox do Chatwoot").fill("2");
    await numeros.getByRole("button", { name: "Salvar" }).click();
    await expect(l2).toContainText("2");
    const origem = card(page, "Chatwoot").locator(".field", { hasText: "Número de origem" }).locator("select");
    await expect(origem.locator("option", { hasText: "Lembrete 02" })).toHaveCount(1);
  });

  test("Conexões: excluir o token também tira os números dele da lista na hora", async ({ page }) => {
    await page.goto("/configuracoes?aba=conexoes");
    const numeros = card(page, "Números de WhatsApp");
    await expect(numeros.locator("tbody tr")).toHaveCount(2);
    const linha = card(page, "Tokens da Meta").locator("tbody tr", { hasText: "Token Cobrança" });
    const msg = responderDialogo(page, true);
    await linha.getByRole("button", { name: "Excluir" }).click();
    await msg;
    await expect(card(page, "Tokens da Meta").getByText("Nenhum token cadastrado")).toBeVisible();
    await expect(numeros.getByText("Nenhum número importado")).toBeVisible({ timeout: 5_000 });
  });

  test("depois de recarregar, os números do token excluído somem", async ({ page }) => {
    await page.goto("/configuracoes?aba=conexoes");
    await expect(card(page, "Números de WhatsApp").getByText("Nenhum número importado")).toBeVisible();
  });
});
