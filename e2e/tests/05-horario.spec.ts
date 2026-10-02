import { card, expect, permitirErrosConsole, test } from "./fixtures";
import { prepararFaixas } from "./preparo";

test.beforeAll(prepararFaixas);

test.describe("Configurações → Horário", { tag: "@horario" }, () => {
  test.beforeEach(async ({ page }) => {
    await page.goto("/configuracoes?aba=horario");
  });

  test("mostra a configuração padrão e os envios por faixa", async ({ page }) => {
    const h = card(page, "Horário de disparo");
    await expect(h).toContainText("Dias: Seg, Ter, Qua, Qui, Sex");
    await expect(h).toContainText("Janela: 08:00–18:30");
    await expect(h).toContainText("Extração automática de leads: Não");
    const envios = card(page, "Disparo por envio");
    await expect(envios.getByRole("heading", { level: 4, name: "3 A 10" })).toBeVisible();
    await expect(envios.getByRole("heading", { level: 4, name: "11 A 20" })).toBeVisible();
  });

  test("horário inválido e fim antes do início são recusados com mensagem", async ({ page }) => {
    permitirErrosConsole(page, "400");
    const h = card(page, "Horário de disparo");
    await h.getByRole("button", { name: "Editar" }).click();
    await h.getByLabel("Início").fill("25:99");
    await h.getByRole("button", { name: "Salvar" }).click();
    await expect(h.locator(".error-box")).toBeVisible();
    await h.getByLabel("Início").fill("19:00");
    await h.getByLabel("Fim").fill("08:00");
    await h.getByRole("button", { name: "Salvar" }).click();
    await expect(h.locator(".error-box")).toContainText(/depois/);
    await h.getByRole("button", { name: "Cancelar" }).click();
    await expect(h).toContainText("Janela: 08:00–18:30");
  });

  test("mensagens de validação usam linguagem do usuário, não nomes de campo da API", async ({ page }) => {
    permitirErrosConsole(page, "400");
    const h = card(page, "Horário de disparo");
    await h.getByRole("button", { name: "Editar" }).click();
    await h.getByLabel("Início").fill("19:00");
    await h.getByLabel("Fim").fill("08:00");
    await h.getByRole("button", { name: "Salvar" }).click();
    await expect(h.locator(".error-box")).not.toContainText("schedule_");
  });

  test("nenhum dia marcado é recusado", async ({ page }) => {
    permitirErrosConsole(page, "400");
    const h = card(page, "Horário de disparo");
    await h.getByRole("button", { name: "Editar" }).click();
    for (const d of ["Seg", "Ter", "Qua", "Qui", "Sex"]) await h.getByRole("button", { name: d, exact: true }).click();
    await h.getByRole("button", { name: "Salvar" }).click();
    await expect(h.locator(".error-box")).toBeVisible();
    await h.getByRole("button", { name: "Cancelar" }).click();
  });

  test("salvar janela de todos os dias, ritmo e extração automática", async ({ page }) => {
    const h = card(page, "Horário de disparo");
    await h.getByRole("button", { name: "Editar" }).click();
    for (const d of ["Sáb", "Dom"]) await h.getByRole("button", { name: d, exact: true }).click();
    await h.getByLabel("Início").fill("00:00");
    await h.getByLabel("Fim").fill("23:59");
    await h.getByLabel("Intervalo entre rodadas (segundos)").fill("2");
    await h.getByLabel("Mensagens por vez").fill("50");
    await h.getByLabel(/Extrair leads automaticamente/).check();
    await expect(h.getByText(/entram sozinhos na\s+fila/)).toBeVisible();
    await h.getByLabel("Minutos antes do início").fill("10");
    await h.getByLabel(/Extrair leads automaticamente/).uncheck(); // desliga de novo: extração real mexeria na fila dos testes
    await h.getByRole("button", { name: "Salvar" }).click();
    await expect(h).toContainText("Dias: Seg, Ter, Qua, Qui, Sex, Sáb, Dom");
    await expect(h).toContainText("Janela: 00:00–23:59");
    await expect(h).toContainText("Ritmo: 50 mensagem(ns) a cada 2s por envio");
    await page.reload();
    await expect(card(page, "Horário de disparo")).toContainText("Janela: 00:00–23:59");
  });

  test("ativar o disparo de um envio e 'Cobrar esta base agora' sem fila", async ({ page }) => {
    const envios = card(page, "Disparo por envio");
    // bloco da faixa: <div> que contém o <h4> e a tabela de envios dela
    const bloco = envios.getByRole("heading", { level: 4, name: "3 A 10", exact: true }).locator("xpath=../..");
    await bloco.getByRole("button", { name: "Editar" }).click();
    await bloco.getByLabel("Ativo").selectOption("sim");
    await bloco.getByRole("button", { name: "Salvar" }).click();
    await expect(bloco.locator(".status-pill")).toHaveText("Sim");
    await bloco.getByRole("button", { name: "Cobrar esta base agora" }).click();
    await expect(bloco.locator(".success-box")).toContainText("Disparo agendado");
  });

  test("status 'Agendado' aparece na lista de faixas", async ({ page }) => {
    await page.goto("/configuracoes?aba=faixas");
    await expect(page.locator(".faixa-row", { hasText: "3 A 10" }).locator(".status-pill")).toHaveText("Agendado");
  });
});
