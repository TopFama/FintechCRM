import { baixar, card, escolherMulti, expect, permitirErrosConsole, test } from "./fixtures";
import type { Page } from "@playwright/test";

const stat = (page: Page, rotulo: string) =>
  page.locator(".stat", { has: page.locator(".label", { hasText: new RegExp(`^${rotulo.replace(/[()]/g, "\\$&")}$`) }) }).locator(".value").first();

test.describe("Dashboard", () => {
  test.beforeEach(async ({ page }) => {
    await page.goto("/");
  });

  test("resumo de hoje reflete a fila, os envios e os telefones inválidos", async ({ page }) => {
    await expect(page.locator(".periodo-card", { hasText: "Hoje" }).first()).toHaveAttribute("aria-pressed", "true");
    await expect(stat(page, "Cobrados (enviados)")).not.toHaveText("0");
    await expect(stat(page, "Pendentes na fila")).not.toHaveText("0");
    await expect(stat(page, "Telefones inválidos")).not.toHaveText("0");
    const porFaixa = card(page, "Por faixa");
    await expect(porFaixa.locator("tbody tr", { hasText: "3 A 10" })).toBeVisible();
  });

  test("erros recentes lista os mesmos erros que o card 'Erros de envio' conta", async ({ page }) => {
    // Erro que não vem do disparo (variável em branco na planilha) também precisa aparecer
    await expect(stat(page, "Erros de envio")).not.toHaveText("0");
    const n = Number(await stat(page, "Erros de envio").innerText());
    const erros = card(page, "Erros recentes");
    await expect(erros.locator("tbody tr")).toHaveCount(Math.min(n, 20));
    await expect(erros.locator("tbody tr", { hasText: "Lúcia" })).toContainText("Faltando coluna");
    // Período sem movimento: card e lista zerados juntos
    await page.locator(".periodo-card", { hasText: "Personalizado" }).first().click();
    const periodo = page.locator(".periodo-filtro").first();
    await periodo.locator('input[type="date"]').first().fill("2020-01-01");
    await periodo.locator('input[type="date"]').nth(1).fill("2020-01-31");
    await expect(stat(page, "Erros de envio")).toHaveText("0");
    await expect(erros).toContainText("Sem erros no período");
  });

  test("cards de período: 7 dias, mês e personalizado com datas", async ({ page }) => {
    const enviadosHoje = await stat(page, "Cobrados (enviados)").innerText();
    await page.locator(".periodo-card", { hasText: "Últimos 7 dias" }).first().click();
    await expect(page.locator(".periodo-card", { hasText: "Últimos 7 dias" }).first()).toHaveAttribute("aria-pressed", "true");
    await expect(stat(page, "Cobrados (enviados)")).toHaveText(enviadosHoje);
    await page.locator(".periodo-card", { hasText: "Personalizado" }).first().click();
    const periodo = page.locator(".periodo-filtro").first();
    await periodo.locator('input[type="date"]').first().fill("2020-01-01");
    await periodo.locator('input[type="date"]').nth(1).fill("2020-01-31");
    await expect(stat(page, "Cobrados (enviados)")).toHaveText("0");
    await expect(stat(page, "Pendentes na fila")).toHaveText("0");
  });

  test("período sem movimento mostra o estado vazio, sem faixas excluídas", async ({ page }) => {
    await page.locator(".periodo-card", { hasText: "Personalizado" }).first().click();
    const periodo = page.locator(".periodo-filtro").first();
    await periodo.locator('input[type="date"]').first().fill("2020-01-01");
    await periodo.locator('input[type="date"]').nth(1).fill("2020-01-31");
    await expect(stat(page, "Cobrados (enviados)")).toHaveText("0");
    await expect(card(page, "Por faixa")).not.toContainText("RENEGOCIE");
    await expect(card(page, "Por faixa")).toContainText("Nenhuma faixa com movimento ainda");
  });

  test("'Personalizado' sem datas não troca os números por um período diferente do mostrado", async ({ page }) => {
    let pediuSemData = false;
    page.on("request", (r) => {
      const u = new URL(r.url());
      if (u.pathname.endsWith("/dashboard/summary") && !u.searchParams.get("de")) pediuSemData = true;
    });
    await page.locator(".periodo-card", { hasText: "Personalizado" }).first().click();
    await page.waitForTimeout(1_000);
    expect(pediuSemData).toBe(false);
  });

  for (const [rotulo, aba] of [
    ["Pendentes na fila", "pendentes"],
    ["Cobrados (enviados)", "envios"],
    ["Erros de envio", "erros"],
    ["Telefones inválidos", "invalidos"],
  ] as const) {
    test(`card '${rotulo}' abre o relatório '${aba}' do mesmo período com o mesmo total`, async ({ page }) => {
      const valor = stat(page, rotulo);
      await expect(valor).not.toHaveText("…");
      const n = Number(await valor.innerText());
      const link = page.getByRole("link", { name: new RegExp(`^Ver ${n} `) }).filter({ has: page.locator(".label", { hasText: rotulo }) });
      await link.hover();
      await link.click();
      const hoje = new Date().toLocaleDateString("sv-SE");
      await expect(page).toHaveURL(new RegExp(`/relatorios\\?aba=${aba}&de=${hoje}&ate=${hoje}$`));
      await expect(page.getByText("Carregando...")).toHaveCount(0, { timeout: 30_000 });
      if (n === 0) {
        await expect(page.locator(".empty-state")).toBeVisible();
      } else {
        await expect(page.locator(".paginacao-info")).toContainText(`de ${n}`);
      }
    });
  }

  test("card é navegável pelo teclado e a linha da faixa abre o relatório filtrado", async ({ page }) => {
    const pend = page.locator("a.stat-link").first();
    await pend.focus();
    await expect(pend).toBeFocused();
    await expect(pend).toContainText("Ver detalhes →");
    const linha = card(page, "Por faixa").locator("tbody tr", { hasText: "3 A 10" });
    const enviados = (await linha.locator("td").nth(2).innerText()).trim();
    await linha.locator("td").nth(2).getByRole("link").click();
    await expect(page).toHaveURL(/aba=envios.*faixa_id=/);
    await expect(page.locator("select").first()).toHaveValue(/.+/);
    await expect(page.getByText("Carregando...")).toHaveCount(0);
    if (enviados !== "0") await expect(page.locator(".paginacao-info")).toContainText(`de ${enviados}`);
  });

  test("tabela por faixa ordena pela ordem de atraso e por números", async ({ page }) => {
    const porFaixa = card(page, "Por faixa");
    await porFaixa.getByRole("columnheader", { name: /^Enviado/ }).click();
    const col = async () => (await porFaixa.locator("tbody tr td:nth-child(3)").allInnerTexts()).map(Number);
    const v = await col();
    expect(v).toEqual([...v].sort((a, b) => a - b));
  });

  test("matriz cluster × faixa: aplicar, abas e clique leva para Cobrança filtrada", async ({ page }) => {
    const m = card(page, "Base de cobrança — cluster × faixa");
    await expect(m).toContainText("Aplique os filtros para ver a matriz cluster × faixa.");
    await m.getByLabel("Somente o primeiro dia da faixa").uncheck();
    await m.getByLabel("Somente clientes da regra WhatsApp").uncheck();
    await m.getByRole("button", { name: "Aplicar filtros" }).click();
    await expect(m.getByText("Consultando o SETA — pode levar até um minuto...")).toBeVisible();
    await expect(m.locator("table")).toBeVisible({ timeout: 30_000 });
    await expect(m).toContainText("ESPECIAL");
    await m.getByRole("tab", { name: "Valor em aberto" }).click();
    await expect(m.getByRole("tab", { name: "Valor em aberto" })).toHaveAttribute("aria-selected", "true");
    await expect(m.locator("table")).toContainText("R$");
    await m.getByRole("tab", { name: "Clientes com restrição no SPC" }).click();
    await m.getByRole("tab", { name: "Clientes", exact: true }).click();
    const celula = m.locator("tbody td").filter({ hasText: /^[1-9]\d*$/ }).first();
    await celula.click();
    await expect(page).toHaveURL(/\/cobranca\?cluster=.+&faixa=.+/);
    await expect(page.getByText("Consultando o SETA")).toHaveCount(0, { timeout: 30_000 });
    await expect(card(page, /^Clientes/).locator("tbody tr").first()).toBeVisible();
  });

  test("efetividade: janela 'Outro' valida 0–365 e bloqueia botões", async ({ page }) => {
    const e = card(page, "Efetividade da cobrança");
    await e.getByLabel("Janela de pagamento").selectOption({ label: "Outro (dias)" });
    await expect(e.getByText("Informe uma janela entre 0 e 365 dias.")).toBeVisible();
    await expect(e.getByRole("button", { name: "Aplicar filtros" })).toBeDisabled();
    await expect(e.getByRole("button", { name: "Exportar Excel" })).toBeDisabled();
    await e.getByLabel("Dias (0–365)").fill("400");
    await expect(e.getByRole("button", { name: "Aplicar filtros" })).toBeDisabled();
    await e.getByLabel("Dias (0–365)").fill("10");
    await expect(e.getByRole("button", { name: "Aplicar filtros" })).toBeEnabled();
    await e.getByRole("button", { name: "Limpar" }).click();
    await expect(e.getByLabel("Janela de pagamento")).toHaveValue("7");
  });

  test("efetividade: por faixa e por loja com linha de total; quem pagou hoje conta", async ({ page }) => {
    const e = card(page, "Efetividade da cobrança");
    await e.getByLabel("Janela de pagamento").selectOption({ label: "Qualquer data após o envio" });
    await e.getByRole("button", { name: "Aplicar filtros" }).click();
    await expect(e.locator("table")).toBeVisible({ timeout: 30_000 });
    const total = e.locator("tr.linha-total");
    await expect(total).toContainText("Total");
    const cobrados = Number((await total.locator("td").nth(2).innerText()).replace(/\D/g, ""));
    expect(cobrados).toBeGreaterThan(0);
    await expect(e.locator("tbody tr", { hasText: "3 A 10" })).toBeVisible();
    await e.getByRole("tab", { name: "Por loja" }).click();
    await expect(e.getByRole("columnheader", { name: /Regional/ })).toBeVisible();
    await expect(e.locator("tbody tr").first()).toBeVisible();
    await e.getByRole("columnheader", { name: /Recebimento/ }).click();
  });

  test("efetividade: exportar Excel e exportar por cliente", async ({ page }) => {
    const e = card(page, "Efetividade da cobrança");
    const a = await baixar(page, () => e.getByRole("button", { name: "Exportar Excel" }).click());
    expect(a.nome).toMatch(/\.xlsx$/);
    expect(a.linhas.length).toBeGreaterThan(1);
    const b = await baixar(page, () => e.getByRole("button", { name: "Exportar por cliente" }).click());
    expect(b.nome).toMatch(/\.xlsx$/);
  });

  test("efetividade: filtro que não pega ninguém mostra estado vazio", async ({ page }) => {
    const e = card(page, "Efetividade da cobrança");
    await e.getByLabel("Enviado de").fill("2020-01-01");
    await e.getByLabel("Enviado até").fill("2020-01-02");
    await e.getByRole("button", { name: "Aplicar filtros" }).click();
    await expect(e.getByText("Nenhum lead enviado no período e filtros escolhidos.")).toBeVisible({ timeout: 30_000 });
  });

  test("leads: contadores, filtro Hoje (liga/desliga) e exportação dos enviados", async ({ page }) => {
    const l = card(page, "Leads");
    await expect(stat(page, "Leads novos")).not.toHaveText("…");
    await expect(stat(page, "Leads enviados")).not.toHaveText("0");
    const hoje = l.locator(".periodo-card", { hasText: "Hoje" });
    await hoje.click();
    await expect(hoje).toHaveAttribute("aria-pressed", "true");
    await hoje.click();
    await expect(hoje).toHaveAttribute("aria-pressed", "false");
    await escolherMulti(l, "Faixas a exportar", ["3 A 10"]);
    const { nome, linhas } = await baixar(page, () => l.getByRole("button", { name: "Exportar leads enviados (.xlsx)" }).click());
    expect(nome).toMatch(/\.xlsx$/);
    expect(linhas[0].map((c) => c.toLowerCase())).toEqual(expect.arrayContaining(["codigo", "nome", "cpf", "celular"]));
    expect(linhas.length).toBeGreaterThan(1);
  });

  test("orçamento: gasto por número, linha de total, ordenação e personalizado", async ({ page }) => {
    const o = card(page, "Orçamento");
    await expect(o.locator("table")).toBeVisible({ timeout: 30_000 });
    await expect(o).toContainText("Realizado (gasto acumulado)");
    await expect(o.locator("svg[role=img]")).toBeVisible();
    const linhas = o.locator("tbody tr:not(.linha-total)");
    await expect(linhas).toHaveCount(2);
    const brl = (t: string) => Number(t.replace(/[^\d,]/g, "").replace(",", "."));
    const gastos = (await linhas.locator("td:nth-child(2)").allInnerTexts()).map(brl);
    const total = brl(await o.locator("tr.linha-total td:nth-child(2)").innerText());
    expect(total).toBeCloseTo(gastos.reduce((a, b) => a + b, 0), 2);
    const qtd = (await linhas.locator("td:nth-child(3)").allInnerTexts()).map(Number);
    expect(Number(await o.locator("tr.linha-total td:nth-child(3)").innerText())).toBe(qtd.reduce((a, b) => a + b, 0));
    await o.getByRole("columnheader", { name: /Gasto no período/ }).click();
    const ord = (await linhas.locator("td:nth-child(2)").allInnerTexts()).map(brl);
    expect(ord).toEqual([...ord].sort((a, b) => a - b));
    // hover no gráfico mostra o tooltip do dia
    const box = await o.locator("svg[role=img] rect").last().boundingBox();
    await page.mouse.move(box!.x + box!.width - 5, box!.y + box!.height / 2);
    await expect(o.locator("svg[role=img]")).toContainText("Acumulado:");
  });

  test("orçamento: escolher 'Personalizado' sem datas não deixa os números do mês anterior na tela", async ({ page }) => {
    const o = card(page, "Orçamento");
    await expect(o.locator("table")).toBeVisible({ timeout: 30_000 });
    await o.locator("select").selectOption("personalizado");
    await expect(o.getByText("Escolha a data mínima e a máxima.")).toBeVisible({ timeout: 3_000 });
  });

  test("orçamento: Meta fora do ar mostra o motivo", async ({ page }) => {
    permitirErrosConsole(page, "502");
    await page.route("**/dashboard/orcamento-progressao*", (r) =>
      r.fulfill({ status: 502, contentType: "application/json", body: JSON.stringify({ detail: "Falha ao consultar a Meta" }) })
    );
    await page.reload();
    await expect(card(page, "Orçamento").locator(".error-box")).toContainText("Falha ao consultar a Meta");
  });
});
