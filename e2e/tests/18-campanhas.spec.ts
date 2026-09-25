import path from "node:path";
import { fileURLToPath } from "node:url";
import type { Page } from "@playwright/test";
import { API_URL } from "./ambiente";
import { apiGet, apiSend, baixar, card, expect, responderDialogo, test } from "./fixtures";

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
    // a ordenação volta do servidor depois do clique: espera a tabela recarregar
    await expect
      .poll(async () => {
        const valores = (await previa.locator("tbody tr td:nth-child(4)").allInnerTexts()).map((t) =>
          Number(t.replace(/[^\d,]/g, "").replace(",", ".")),
        );
        return valores.every((v, i) => i === 0 || valores[i - 1] <= v);
      })
      .toBe(true);
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

  test("quem recebeu a campanha vira lead da faixa de atraso e aparece filtrando pela campanha", async ({ page }) => {
    const campanha = (await apiGet(page, "/campanhas")).find((c: any) => c.nome === "Feirão lojas 01 e 06");
    const faixasAtraso = (await apiGet(page, "/cobranca/regras")).faixas as string[];
    const leads = await apiGet(page, `/leads?campanha=${campanha.id}&limit=100&offset=0`);
    expect(leads.total).toBeGreaterThan(0);
    for (const l of leads.itens) expect(faixasAtraso).toContain(l.faixa);

    // envia já a fila da campanha (o worker só envia dentro do horário de disparo)
    expect((await apiSend(page, "POST", "/__e2e/campanhas/enviar")).status).toBe(200);
    await expect
      .poll(async () => (await apiGet(page, `/leads?campanha=${campanha.id}&status=cobrado&limit=100&offset=0`)).total, {
        timeout: 15_000,
      })
      .toBe(leads.total);
    const codigos = leads.itens.map((l: any) => l.codigo_cliente).sort();

    const efet = await apiGet(page, `/reports/efetividade?campanha=${campanha.id}`);
    expect(efet.total.clientes_cobrados).toBe(leads.total);
    const soRegua = await apiGet(page, "/reports/efetividade?campanha=regua");
    const todas = await apiGet(page, "/reports/efetividade");
    expect(todas.total.qtd_envios).toBe(soRegua.total.qtd_envios + efet.total.qtd_envios);

    await page.goto("/");
    const e = card(page, "Efetividade da cobrança");
    await e.getByLabel("Campanha").selectOption({ label: "Feirão lojas 01 e 06" });
    await e.getByRole("button", { name: "Aplicar filtros" }).click();
    await expect(e.locator("tr.linha-total td").nth(2)).toHaveText(String(leads.total));
    await foto(page, "campanha-efetividade");

    const l = card(page, "Leads");
    await l.getByLabel("Campanha").selectOption({ label: "Feirão lojas 01 e 06" });
    const { linhas } = await baixar(page, () => l.getByRole("button", { name: "Exportar leads enviados (.xlsx)" }).click());
    expect(linhas.slice(1).map((r) => r[0].replace(/\D/g, "").padStart(8, "0")).sort()).toEqual(codigos);
  });

  test("no dia seguinte ao envio da campanha o cliente entra na régua da faixa de atraso", async ({ page }) => {
    const campanha = (await apiGet(page, "/campanhas")).find((c: any) => c.nome === "Feirão lojas 01 e 06");
    const leads = (await apiGet(page, `/leads?campanha=${campanha.id}&limit=100&offset=0`)).itens;
    const codigos = leads.map((l: any) => l.codigo_cliente);
    // a régua precisa da faixa com número + template (rodando só este arquivo, ninguém configurou)
    const faixaDoCliente = (await apiGet(page, "/faixas")).find((f: any) => f.name === leads[0].faixa);
    if (!faixaDoCliente?.envios.some((e: any) => e.active)) {
      const numero = (await apiGet(page, "/numbers"))[0];
      const template = (await apiGet(page, "/templates")).find((t: any) => t.name === "lembrete_vencimento");
      const envio = {
        template_id: template.id,
        variable_mappings: template.variables.map((v: any) => ({
          template_variable_id: v.id,
          fonte_tipo: "campo_cliente",
          column_name: "primeiro_nome",
        })),
      };
      const criado = faixaDoCliente
        ? await apiSend(page, "POST", `/faixas/${faixaDoCliente.id}/envios`, { ...envio, whatsapp_number_id: numero.id })
        : await apiSend(page, "POST", "/faixas", { ...envio, name: leads[0].faixa, whatsapp_number_ids: [numero.id] });
      expect(criado.status).toBe(201);
    }
    const r = await apiSend(page, "POST", "/__e2e/campanhas/regua-no-dia-seguinte");
    expect(r.corpo.status).toBe("ready");

    // entraram na fila de alguma faixa de atraso (régua), não na da campanha. Dentro do horário
    // de disparo o próprio agendador pode ter feito isso antes do gancho, então confere a fila.
    const regua = (await apiGet(page, "/faixas")).filter((f: any) => !f.campanha_id && !f.remarketing_segmento);
    const naRegua = new Set<string>();
    for (const f of regua) {
      const fila = await apiGet(page, `/faixas/${f.id}/queue?limit=500&offset=0`);
      for (const i of fila.itens) if (codigos.includes(i.codigo_cliente)) naRegua.add(i.codigo_cliente);
    }
    expect(naRegua.size).toBeGreaterThan(0);

    // segunda passada no mesmo dia não repete ninguém
    const deNovo = await apiSend(page, "POST", "/__e2e/campanhas/regua-no-dia-seguinte");
    expect(deNovo.corpo.na_fila).toBe(0);
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
    // 99999 não existe no SETA; 00000036 pode ter saído da base em cenários anteriores (blacklist)
    await expect(previa).toContainText(/[12] cliente\(s\) entrariam/);
    await expect(previa.locator("tbody")).toContainText("R$ 99,90");
    const entrariam = await previa.locator("tbody tr").count();

    const confirmou = responderDialogo(page);
    await previa.getByRole("button", { name: "Colocar na fila agora" }).click();
    await confirmou;
    await expect(page.locator(".success-box", { hasText: "encontrado" })).toContainText(`(de ${entrariam} encontrado(s))`);

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
