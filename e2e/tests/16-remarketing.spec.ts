import { apiGet, apiSend, card, expect, permitirErrosConsole, test } from "./fixtures";

// Renegocie simulado em servidor_teste.py: 00000003 só se identificou, 00000004 viu a
// proposta há 40 dias, 00000005 e 00000027 tiveram acordo cancelado (o acordo do
// 00000005 tem parcela paga no SETA falso) e 00000009 cancelou a proposta.
test.describe.serial("Remarketing do Renegocie", () => {
  const acordo = (page: import("@playwright/test").Page) => card(page, "Acordo cancelado sem pagar a entrada");

  test("conexão com o Renegocie: chave errada é recusada, a certa conecta", async ({ page }) => {
    await page.goto("/remarketing");
    const renegocie = card(page, /^Renegocie/);
    await expect(renegocie.getByLabel("Endereço do Renegocie")).toHaveValue("http://renegocie-api:8000");
    await renegocie.getByLabel("Chave de integração").fill("chave-errada");
    await renegocie.getByRole("button", { name: "Salvar" }).click();
    await renegocie.getByRole("button", { name: "Testar conexão" }).click();
    await expect(renegocie.locator(".error-box")).toContainText("recusou a chave");

    await renegocie.getByLabel("Chave de integração").fill("chave-teste");
    await renegocie.getByRole("button", { name: "Salvar" }).click();
    await renegocie.getByRole("button", { name: "Testar conexão" }).click();
    await expect(renegocie.locator(".success-box")).toContainText("Conectado. 5 desistência(s)");
  });

  test("segmentos nascem desligados, com faixa própria e descrição", async ({ page }) => {
    await page.goto("/remarketing");
    for (const nome of ["Só se identificou", "Viu a proposta e não fechou", "Cancelou a proposta"]) {
      await expect(card(page, nome).locator(".status-pill")).toHaveText("Desligado");
    }
    await expect(acordo(page)).toContainText("entrada não foi paga");
    await expect(acordo(page).locator(".error-box")).toContainText("ainda não tem número e template");
  });

  test("prévia: acordo com parcela paga (status B) fica de fora", async ({ page }) => {
    await page.goto("/remarketing");
    await acordo(page).getByLabel("Enviar remarketing para este segmento").check();
    await acordo(page).getByRole("button", { name: "Salvar" }).click();
    await expect(acordo(page).locator(".status-pill")).toHaveText("Ligado");
    await acordo(page).getByRole("button", { name: "Ver quem entraria hoje" }).click();
    await expect(acordo(page)).toContainText("1 de 2 desistência(s)");
    await expect(acordo(page).locator("tbody tr")).toHaveCount(1);
    await expect(acordo(page).locator("tbody")).toContainText("00000027");
    await expect(acordo(page).locator("tbody")).toContainText("RE000901");
  });

  test("janela da desistência e filtro de valor valem na prévia", async ({ page }) => {
    await page.goto("/remarketing");
    const viu = card(page, "Viu a proposta e não fechou");
    await viu.getByRole("button", { name: "Ver quem entraria hoje" }).click();
    await expect(viu).toContainText("0 de 1 desistência(s)"); // desistiu há 40 dias, janela de 30
    await viu.getByLabel("Desistiu há no máximo (dias)").fill("60");
    await viu.getByRole("button", { name: "Salvar" }).click();
    await viu.getByRole("button", { name: "Ver quem entraria hoje" }).click();
    await expect(viu).toContainText("1 de 1 desistência(s)");
    await viu.getByLabel("Valor a cobrar mínimo (R$)").fill("999999");
    await viu.getByRole("button", { name: "Salvar" }).click();
    await viu.getByRole("button", { name: "Ver quem entraria hoje" }).click();
    await expect(viu).toContainText("0 de 1 desistência(s)");
  });

  test("faixa de remarketing: descrição, sem planilha, sem excluir, template atribuível", async ({ page }) => {
    permitirErrosConsole(page, /400/);
    const faixa = (await apiGet(page, "/faixas")).find((f: any) => f.remarketing_segmento === "ACORDO_SEM_ENTRADA");
    expect(faixa.descricao).toContain("entrada não foi paga");

    await page.goto("/configuracoes?aba=faixas");
    const linha = page.locator(".faixa-row", { hasText: faixa.name });
    await expect(linha).toContainText("entrada não foi paga");
    await expect(linha.getByTitle("Excluir faixa")).toHaveCount(0);
    expect((await apiSend(page, "DELETE", `/faixas/${faixa.id}`)).status).toBe(400);

    await page.goto("/cobranca");
    await expect(page.locator("#cobranca-faixa option", { hasText: "Remarketing" })).toHaveCount(0);

    await page.goto(`/faixas/${faixa.id}`);
    await expect(page.locator(".faixa-descricao")).toContainText("entrada não foi paga");
    await expect(card(page, "De onde vêm os clientes")).toContainText("não recebe planilha");
    await expect(card(page, "Leads gerados nesta faixa de atraso")).toHaveCount(0);

    // o cenário de Conexões exclui o token (e os números): cadastra um de novo
    if ((await apiGet(page, "/numbers")).length === 0) {
      const token = await apiSend(page, "POST", "/meta-tokens", {
        nome: "Token Remarketing",
        token: "EAA-token-remarketing-1234",
        waba_id: "1111111111",
      });
      expect(token.status).toBe(201);
      expect((await apiSend(page, "POST", `/meta-tokens/${token.corpo.id}/importar-numeros`, { phone_number_ids: ["900002"] })).status).toBe(200);
    }
    await page.reload();
    await page.getByRole("button", { name: "Adicionar número e template" }).click();
    await page.getByLabel("Número de envio").selectOption({ index: 1 });
    await page.locator("#faixa-template").selectOption({ label: "lembrete_vencimento" });
    await page.locator("select[id^='faixa-var-']").first().selectOption({ label: "Primeiro nome" });
    await page.getByRole("button", { name: "Salvar envio" }).click();
    await expect(page.locator(".success-box")).toContainText("Envio adicionado");
  });

  test("buscar agora coloca na fila só quem passou, e não repete dentro do recontato", async ({ page }) => {
    await page.goto("/remarketing");
    await page.getByRole("button", { name: "Buscar agora" }).click();
    await expect(card(page, "Remarketing do Renegocie").locator(".success-box")).toContainText(
      "1 cliente(s) colocado(s) na fila"
    );
    await expect(acordo(page)).toContainText("1 encontrado(s), 1 na fila");

    const faixa = (await apiGet(page, "/faixas")).find((f: any) => f.remarketing_segmento === "ACORDO_SEM_ENTRADA");
    const fila = await apiGet(page, `/faixas/${faixa.id}/queue?limit=100&offset=0`);
    expect(fila.itens.map((i: any) => i.codigo_cliente)).toEqual(["00000027"]);
    expect(fila.itens[0].status).not.toBe("error");

    await page.getByRole("button", { name: "Buscar agora" }).click();
    await expect(card(page, "Remarketing do Renegocie").locator(".success-box")).toContainText(
      "0 cliente(s) colocado(s) na fila"
    );
  });
});
