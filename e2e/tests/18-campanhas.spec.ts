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
    // a coluna da loja é escolhida na tela, com exemplos de cada coluna
    await page.getByLabel("Coluna com o código da loja").selectOption({ label: "FILIAL (ex.: 1, 6, 99)" });
    await page.getByRole("button", { name: "Marcar lojas" }).click();
    await expect(page.getByRole("status")).toContainText("2 loja(s) marcada(s). Não encontrei na base de lojas: 99");

    await page.getByLabel("Valor em atraso de (R$)").fill("200");
    await page.getByLabel("Valor em atraso até (R$)").fill("900");
    await page.getByLabel("Valor considerado").selectOption({ label: "Corrigido com multa e juros" });
    await page.getByRole("button", { name: "Criar campanha" }).click();
    await expect(page.getByRole("heading", { name: "Feirão lojas 01 e 06" })).toBeVisible();
    await expect(page.locator(".status-pill").first()).toHaveText("Manual");

    const campanha = (await apiGet(page, "/campanhas")).find((c: any) => c.nome === "Feirão lojas 01 e 06");
    expect(campanha.filtros.loja).toEqual(["01", "06"]);
    expect(campanha.filtros.valor_atraso_com_juros).toBe(true);
  });

  test("template atribuído na campanha, fora da lista de faixas de atraso", async ({ page }) => {
    const campanha = (await apiGet(page, "/campanhas")).find((c: any) => c.nome === "Feirão lojas 01 e 06");
    await page.goto(`/campanhas/${campanha.id}`);
    await atribuirTemplate(page, "lembrete_vencimento", "Primeiro nome");
    await expect(card(page, "Template e número da campanha").locator("tbody")).toContainText("lembrete_vencimento");

    // o tipo separa campanha de régua de atraso
    expect((await apiGet(page, `/faixas/${campanha.faixa_id}`)).tipo).toBe("campanha");
    const faixas = await apiGet(page, "/faixas");
    expect(faixas.filter((f: any) => f.name.startsWith("Remarketing: ")).every((f: any) => f.tipo === "remarketing")).toBe(true);
    expect(faixas.filter((f: any) => !f.campanha_id && !f.remarketing_segmento).every((f: any) => f.tipo === "regua")).toBe(true);

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
    // tudo = régua + cada campanha (inclusive o remarketing, que é campanha fixa)
    let somaCampanhas = 0;
    for (const c of await apiGet(page, "/campanhas/opcoes")) {
      somaCampanhas += (await apiGet(page, `/reports/efetividade?campanha=${c.id}`)).total.qtd_envios;
    }
    expect(todas.total.qtd_envios).toBe(soRegua.total.qtd_envios + somaCampanhas);

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
    // planilha escolhida antes de salvar: sobe junto com a criação
    await page.locator('input[aria-label="Planilha de clientes"]').setInputFiles(path.join(DADOS, "clientes_campanha.xlsx"));
    await expect(page.getByText("clientes_campanha.xlsx · será lida ao criar a campanha")).toBeVisible();
    await page.getByLabel("Valor, celular e variáveis vêm").selectOption("planilha");
    // envio automático num período futuro: salva a configuração sem rodar sozinho durante o teste
    await page.getByLabel("Envio automático").check();
    await page.getByLabel("Período: de").fill("2099-01-01");
    await page.getByLabel("Até (vazio = sem data final)").fill("2099-01-02");
    await page.getByRole("button", { name: "Criar campanha" }).click();
    await expect(page.getByRole("heading", { name: "Planilha promo" })).toBeVisible();
    await expect(page.getByText("clientes_campanha.xlsx · 3 cliente(s)")).toBeVisible();
    await expect(page.getByLabel("Valor, celular e variáveis vêm")).toHaveValue("planilha");
    await expect(page.locator(".status-pill").first()).toHaveText("Automática");
    await expect(page.locator(".page-header .subtitle")).toContainText("Envio automático de 01/01/2099 a 02/01/2099");

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

    // Pendentes: faixa de atraso (régua) e campanha em colunas separadas
    const pendente = fila.itens.find((i: any) => i.status === "pending");
    if (pendente) {
      const api = await apiGet(page, `/reports/pendentes?faixa_id=${campanha.faixa_id}&limit=50&offset=0`);
      const linhaApi = api.itens.find((i: any) => i.codigo_cliente === pendente.codigo_cliente);
      expect(linhaApi.campanha).toBe("Planilha promo");
      expect((await apiGet(page, "/cobranca/regras")).faixas).toContain(linhaApi.faixa);
      await page.goto(`/relatorios?aba=pendentes&faixa_id=${campanha.faixa_id}`);
      await expect(page.getByRole("columnheader", { name: /Faixa de atraso \(régua\)/ })).toBeVisible();
      const linha = page.locator("tbody tr", { hasText: pendente.codigo_cliente });
      await expect(linha).toContainText("Planilha promo");
      await expect(linha).toContainText(linhaApi.faixa);
      await expect(linha).not.toContainText("Campanha:");
    }
  });

  test("Por faixa do Dashboard mostra a faixa de atraso de quem recebeu, não a campanha", async ({ page }) => {
    const resumo = await apiGet(page, "/dashboard/summary");
    const nomes = resumo.por_faixa.map((f: any) => f.faixa);
    expect(nomes.some((n: string) => n.startsWith("Campanha:"))).toBe(false);
    const faixasAtraso = (await apiGet(page, "/cobranca/regras")).faixas as string[];
    const campanha = (await apiGet(page, "/campanhas")).find((c: any) => c.nome === "Feirão lojas 01 e 06");
    const lead = (await apiGet(page, `/leads?campanha=${campanha.id}&limit=1&offset=0`)).itens[0];
    expect(faixasAtraso).toContain(lead.faixa);
    const linha = resumo.por_faixa.find((f: any) => f.faixa === lead.faixa);
    expect((linha.sent ?? 0) + (linha.cancelled ?? 0) + (linha.pending ?? 0)).toBeGreaterThan(0);
  });

  test("Efetividade por campanha e lista de campanhas pelo período enviado", async ({ page }) => {
    await page.goto("/");
    const e = card(page, "Efetividade da cobrança");
    await e.getByRole("button", { name: "Aplicar filtros" }).click();
    await e.getByRole("tab", { name: "Por campanha" }).click();
    await expect(e.locator("thead th").first()).toHaveText(/Campanha/);
    // a régua aparece numa linha própria quando também cobrou no período
    const regua = await apiGet(page, "/reports/efetividade?campanha=regua");
    await expect(e.locator("tbody tr", { hasText: "Régua de atraso" })).toHaveCount(
      regua.total.qtd_envios > 0 ? 1 : 0
    );
    await expect(e.locator("tbody tr", { hasText: "Feirão lojas 01 e 06" })).toBeVisible();
    await foto(page, "efetividade-por-campanha");

    const opcoes = e.getByLabel("Campanha").locator("option");
    await expect(opcoes.filter({ hasText: "Feirão lojas 01 e 06" })).toHaveCount(1);
    // sem aplicar: só as datas já filtram a lista
    await e.getByLabel("Enviado de").fill("2020-01-01");
    await e.getByLabel("Enviado até").fill("2020-01-02");
    await expect(opcoes.filter({ hasText: "Feirão lojas 01 e 06" })).toHaveCount(0);
    await e.getByLabel("Enviado de").fill("");
    await e.getByLabel("Enviado até").fill("");
    await expect(opcoes.filter({ hasText: "Feirão lojas 01 e 06" })).toHaveCount(1);
  });

  test("Campanhas mostra Criado em e filtra por período de criação ou de envio", async ({ page }) => {
    await page.goto("/campanhas");
    const feirao = page.locator(".faixa-row", { hasText: "Feirão lojas 01 e 06" });
    await expect(feirao).toContainText(/Criado em: \d{2}\/\d{2}\/\d{4}/);
    const hoje = new Intl.DateTimeFormat("en-CA", { timeZone: "America/Sao_Paulo" }).format(new Date());

    await page.getByLabel("De", { exact: true }).fill("2020-01-01");
    await page.getByLabel("Até", { exact: true }).fill("2020-01-02");
    await expect(page.getByText("Nenhuma campanha criada no período escolhido.")).toBeVisible();
    await page.getByLabel("De", { exact: true }).fill(hoje);
    await page.getByLabel("Até", { exact: true }).fill(hoje);
    await expect(feirao).toBeVisible();

    // envio: pelo dia em que a campanha cobrou (o teste da régua jogou os envios da Feirão para ontem)
    const ontem = new Intl.DateTimeFormat("en-CA", { timeZone: "America/Sao_Paulo" }).format(
      new Date(Date.now() - 86_400_000)
    );
    await page.getByLabel("Filtrar por").selectOption({ label: "Período de envio" });
    await page.getByLabel("De", { exact: true }).fill("2020-01-01");
    await page.getByLabel("Até", { exact: true }).fill("2020-01-02");
    await expect(page.getByText("Nenhuma campanha com envio no período escolhido.")).toBeVisible();
    await page.getByLabel("De", { exact: true }).fill(ontem);
    await page.getByLabel("Até", { exact: true }).fill(hoje);
    await expect(feirao).toBeVisible();
    const envio = await apiGet(page, `/campanhas?periodo=envio&de=${ontem}&ate=${hoje}`);
    expect(envio.map((c: any) => c.nome)).toContain("Feirão lojas 01 e 06");
    // o remarketing (campanha fixa) também aparece se enviou no período
    const fixas = await apiGet(page, `/campanhas/fixas?periodo=envio&de=${ontem}&ate=${hoje}`);
    await expect(page.locator(".faixa-row")).toHaveCount(envio.length + fixas.length);
    await foto(page, "campanhas-filtro-periodo");
  });

  test("Relatórios filtram por campanha", async ({ page }) => {
    const campanha = (await apiGet(page, "/campanhas")).find((c: any) => c.nome === "Feirão lojas 01 e 06");
    const todos = (await apiGet(page, "/reports/envios?limit=1&offset=0")).total;
    const daCampanha = (await apiGet(page, `/reports/envios?campanha=${campanha.id}&limit=1&offset=0`)).total;
    const regua = (await apiGet(page, "/reports/envios?campanha=regua&limit=1&offset=0")).total;
    expect(daCampanha).toBeGreaterThan(0);
    expect(regua + daCampanha).toBeLessThanOrEqual(todos);

    await page.goto("/relatorios?aba=envios");
    await page.getByLabel("Campanha").selectOption({ label: "Feirão lojas 01 e 06" });
    await expect(page).toHaveURL(new RegExp(`campanha=${campanha.id}`));
    await expect(page.locator(".card table tbody tr")).toHaveCount(Math.min(daCampanha, 50));
    await page.reload();
    await expect(page.getByLabel("Campanha")).toHaveValue(campanha.id);
  });

  test("remarketing do Renegocie entra como campanha fixa", async ({ page }) => {
    await garantirNumero(page);
    const conexao = { base_url: "http://renegocie-api:8000", chave: "chave-teste" };
    expect((await apiSend(page, "PUT", "/remarketing/conexao", conexao)).status).toBe(200);
    const segmento = { ativo: true, janela_dias: 30, recontato_dias: 7 };
    expect((await apiSend(page, "PUT", "/remarketing/segmentos/SO_IDENTIFICOU", segmento)).status).toBe(200);
    const id = "remarketing:SO_IDENTIFICOU";
    const nome = "Remarketing: Clientes identificados no portal";

    // aparece no topo da lista de Campanhas como campanha fixa
    await page.goto("/campanhas");
    const fixa = page.locator(".faixa-row", { hasText: nome });
    await expect(fixa).toContainText("Campanha fixa");
    await expect(fixa.locator(".status-pill")).toHaveText("Ligada");
    await foto(page, "campanhas-com-fixas");

    await page.goto("/campanhas?aba=remarketing");
    const bloco = card(page, "Clientes identificados no portal");
    await bloco.getByRole("button", { name: "Adicionar número e template" }).click();
    await bloco.getByLabel("Número de envio").selectOption({ index: 1 });
    await bloco.locator("#faixa-template").selectOption({ label: "lembrete_vencimento" });
    await bloco.locator("select[id^='faixa-var-']").first().selectOption({ label: "Primeiro nome" });
    await bloco.getByRole("button", { name: "Salvar envio" }).click();
    await expect(bloco.locator(".success-box")).toContainText("Envio adicionado");

    const resumo = await apiSend(page, "POST", "/remarketing/executar");
    expect(resumo.status).toBe(200);
    const naFila = resumo.corpo.SO_IDENTIFICOU.na_fila;
    expect(naFila).toBe(1);
    expect((await apiSend(page, "POST", "/__e2e/campanhas/enviar")).status).toBe(200);

    // como numa campanha: lead da faixa de atraso marcado com a campanha fixa, cobrado no envio
    const faixasAtraso = (await apiGet(page, "/cobranca/regras")).faixas as string[];
    await expect
      .poll(async () => (await apiGet(page, `/leads?campanha=${id}&status=cobrado&limit=10&offset=0`)).total)
      .toBe(naFila);
    const lead = (await apiGet(page, `/leads?campanha=${id}&limit=10&offset=0`)).itens[0];
    expect(lead.codigo_cliente).toBe("00000003");
    expect(faixasAtraso).toContain(lead.faixa);

    const opcoes = await apiGet(page, "/campanhas/opcoes");
    expect(opcoes.find((o: any) => o.id === id)).toMatchObject({ nome, fixa: true });
    const efet = await apiGet(page, "/reports/efetividade");
    expect(efet.por_campanha.map((l: any) => l.campanha)).toContain(nome);
    expect((await apiGet(page, `/reports/efetividade?campanha=${id}`)).total.clientes_cobrados).toBe(naFila);
    expect((await apiGet(page, `/reports/envios?campanha=${id}&limit=10&offset=0`)).total).toBe(naFila);

    await page.goto("/");
    const e = card(page, "Efetividade da cobrança");
    const grupo = e.getByLabel("Campanha").locator('optgroup[label="Remarketing do Renegocie (campanhas fixas)"] option');
    await expect(grupo.filter({ hasText: nome })).toHaveCount(1);
  });

  test("pausar, retomar e parar a campanha pela lista e dentro dela", async ({ page }) => {
    await page.goto("/campanhas");
    const linha = page.locator(".faixa-row", { hasText: "Planilha promo" });
    let dialogo = responderDialogo(page, true, "conferir valores");
    await linha.getByRole("button", { name: "Pausar" }).click();
    await dialogo;
    await expect(linha.locator(".status-pill")).toHaveText("Pausada");
    await expect(page).toHaveURL(/\/campanhas$/); // o botão não abre a campanha

    await linha.getByRole("button", { name: "Retomar" }).click();
    await expect(linha.locator(".status-pill")).toHaveText("Automática");

    await linha.locator(".faixa-row-title").click();
    await expect(page.getByRole("heading", { name: "Planilha promo" })).toBeVisible();
    dialogo = responderDialogo(page);
    await page.locator(".page-header").getByRole("button", { name: "Parar" }).click();
    await dialogo;
    await expect(page.locator(".success-box")).toContainText(/Campanha parada: \d+ pendente\(s\) cancelado\(s\)/);
    await expect(page.locator(".page-header .status-pill")).toHaveText("Parada");
    await expect(page.getByLabel("Envio automático")).not.toBeChecked();
    const campanha = (await apiGet(page, "/campanhas")).find((c: any) => c.nome === "Planilha promo");
    expect(campanha.pendentes).toBe(0);
  });

  test("busca pelo nome e campanha com prazo vencido aparece como Finalizada", async ({ page }) => {
    await page.goto("/campanhas");
    await page.getByLabel("Buscar").fill("planilha PROMO");
    await expect(page.locator(".faixa-row", { hasText: "Planilha promo" })).toBeVisible();
    await expect(page.locator(".faixa-row", { hasText: "Feirão lojas 01 e 06" })).toHaveCount(0);
    await page.getByLabel("Buscar").fill("não existe essa");
    await expect(page.getByText('Nenhuma campanha com "não existe essa" no nome.')).toBeVisible();
    await page.getByRole("button", { name: "Limpar" }).click();
    await expect(page.locator(".faixa-row", { hasText: "Feirão lojas 01 e 06" })).toBeVisible();

    // prazo terminou ontem: deixa de ser "Parada" e vira "Finalizada"
    const campanha = (await apiGet(page, "/campanhas")).find((c: any) => c.nome === "Planilha promo");
    const r = await apiSend(page, "PUT", `/campanhas/${campanha.id}`, {
      nome: campanha.nome,
      ativa: false,
      data_inicio: "2020-01-01",
      data_fim: "2020-01-02",
      fonte_valores: campanha.fonte_valores,
      recontato_dias: campanha.recontato_dias,
      filtros: campanha.filtros,
    });
    expect(r.status).toBe(200);
    expect(r.corpo.finalizada).toBe(true);
    await page.reload();
    const linha = page.locator(".faixa-row", { hasText: "Planilha promo" });
    await expect(linha.locator(".status-pill")).toHaveText("Finalizada");
    await expect(linha.getByRole("button", { name: "Parar" })).toHaveCount(0);
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
