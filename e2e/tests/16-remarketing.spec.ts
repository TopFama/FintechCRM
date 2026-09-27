import { apiGet, apiSend, card, expect, permitirErrosConsole, test } from "./fixtures";

// Renegocie simulado em servidor_teste.py: 00000003 só se identificou, 00000004 viu a
// proposta há 40 dias, 00000005 e 00000027 têm acordo ativo (no SETA falso a entrada do
// 00000005 está paga e a do 00000027 vencida em aberto) e 00000009 vem num segmento
// antigo (CANCELOU_PROPOSTA), que o CRM ignora.
// Espera a chave ser gravada antes de testar; sem isso o teste pode usar a chave anterior.
const salvar = (page: import("@playwright/test").Page, renegocie: import("@playwright/test").Locator) =>
  Promise.all([
    page.waitForResponse((r) => r.url().includes("/remarketing/conexao") && r.request().method() === "PUT"),
    renegocie.getByRole("button", { name: "Salvar" }).click(),
  ]);

test.describe.serial("Remarketing do Renegocie", () => {
  const acordo = (page: import("@playwright/test").Page) => card(page, "Acordo ativo com entrada não paga");

  test("conexão com o Renegocie: chave errada é recusada, a certa conecta", async ({ page }) => {
    await page.goto("/configuracoes");
    const renegocie = card(page, /^Renegocie/);
    await expect(renegocie.getByLabel("Endereço do Renegocie")).toHaveValue("http://renegocie-api:8000");
    await renegocie.getByLabel("Chave de integração").fill("chave-errada");
    await salvar(page, renegocie);
    await renegocie.getByRole("button", { name: "Testar conexão" }).click();
    await expect(renegocie.locator(".error-box")).toContainText("recusou a chave");

    await renegocie.getByLabel("Chave de integração").fill("chave-teste");
    await salvar(page, renegocie);
    await renegocie.getByRole("button", { name: "Testar conexão" }).click();
    await expect(renegocie.locator(".success-box")).toContainText("Conectado. 5 desistência(s)");
  });

  test("segmentos nascem desligados, com faixa própria e descrição", async ({ page }) => {
    await page.goto("/remarketing");
    for (const nome of ["Clientes identificados no portal", "Propostas simuladas", "Acordo ativo com entrada não paga"]) {
      await expect(card(page, nome).locator(".status-pill")).toHaveText("Desligado");
    }
    await expect(page.locator(".card", { has: page.locator("h3", { hasText: /^Cancelou/ }) })).toHaveCount(0);
    await expect(acordo(page)).toContainText("entrada (primeira parcela do RE) vencida e em aberto");
    await expect(acordo(page).locator(".error-box")).toContainText("Ainda sem número e template");
  });

  test("prévia: acordo com a entrada paga (status B) fica de fora", async ({ page }) => {
    await page.goto("/remarketing");
    await acordo(page).getByLabel("Enviar remarketing para este segmento").check();
    await acordo(page).getByRole("button", { name: "Salvar" }).click();
    await expect(acordo(page).locator(".status-pill")).toHaveText("Ligado");
    await acordo(page).getByRole("button", { name: "Ver quem entraria hoje" }).click();
    await expect(acordo(page)).toContainText("1 de 2 cliente(s) do Renegocie passam nos filtros");
    await expect(acordo(page).locator("tbody tr")).toHaveCount(1);
    await expect(acordo(page).locator("tbody")).toContainText("00000027");
    await expect(acordo(page).locator("tbody")).toContainText("RE000901");
  });

  test("janela da desistência e filtro de valor valem na prévia", async ({ page }) => {
    await page.goto("/remarketing");
    const viu = card(page, "Propostas simuladas");
    await viu.getByRole("button", { name: "Ver quem entraria hoje" }).click();
    await expect(viu).toContainText("0 de 1 cliente(s) do Renegocie"); // desistiu há 40 dias, janela de 30
    await viu.getByLabel("Desistiu há no máximo (dias)").fill("60");
    await viu.getByRole("button", { name: "Salvar" }).click();
    await viu.getByRole("button", { name: "Ver quem entraria hoje" }).click();
    await expect(viu).toContainText("1 de 1 cliente(s) do Renegocie");
    await viu.getByLabel("Valor a cobrar mínimo (R$)").fill("999999");
    await viu.getByRole("button", { name: "Salvar" }).click();
    await viu.getByRole("button", { name: "Ver quem entraria hoje" }).click();
    await expect(viu).toContainText("0 de 1 cliente(s) do Renegocie");
  });

  test("faixa de remarketing: descrição, sem planilha, sem excluir, template atribuível", async ({ page }) => {
    permitirErrosConsole(page, /400/);
    const faixa = (await apiGet(page, "/faixas")).find((f: any) => f.remarketing_segmento === "ACORDO_ATIVO");
    expect(faixa.descricao).toContain("entrada (primeira parcela do RE) vencida");

    // Configurações → Faixas lista só a régua de atraso
    await page.goto("/configuracoes?aba=faixas");
    await expect(page.locator(".faixa-row").first()).toBeVisible();
    await expect(page.locator(".faixa-row", { hasText: faixa.name })).toHaveCount(0);
    expect((await apiSend(page, "DELETE", `/faixas/${faixa.id}`)).status).toBe(400);

    await page.goto("/cobranca");
    await expect(page.locator("#cobranca-faixa option", { hasText: "Remarketing" })).toHaveCount(0);

    await page.goto(`/faixas/${faixa.id}`);
    await expect(page.locator(".faixa-descricao")).toContainText("entrada (primeira parcela do RE) vencida");
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
    // Com o segmento ligado, a rotina do dia do worker pode ter buscado antes do clique:
    // o cliente entra na fila uma vez só, por um caminho ou pelo outro.
    await expect(card(page, "Remarketing do Renegocie").locator(".success-box")).toContainText(
      /^[01] cliente\(s\) colocado\(s\) na fila/
    );

    const faixa = (await apiGet(page, "/faixas")).find((f: any) => f.remarketing_segmento === "ACORDO_ATIVO");
    const fila = await apiGet(page, `/faixas/${faixa.id}/queue?limit=100&offset=0`);
    expect(fila.itens.map((i: any) => i.codigo_cliente)).toEqual(["00000027"]);
    expect(fila.itens[0].status).not.toBe("error");

    await page.getByRole("button", { name: "Buscar agora" }).click();
    await expect(card(page, "Remarketing do Renegocie").locator(".success-box")).toContainText(
      "0 cliente(s) colocado(s) na fila"
    );
  });
});
