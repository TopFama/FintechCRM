import { apiGet, baixar, card, escolherMulti, expect, permitirErrosConsole, test } from "./fixtures";
import type { Page } from "@playwright/test";

const stat = (page: Page, rotulo: string) =>
  page.locator(".stat", { has: page.locator(".label", { hasText: new RegExp(`^${rotulo.replace(/[()]/g, "\\$&")}$`) }) }).locator(".value").first();

// "12.345" → 12345 (os cards mostram separador de milhar)
const numero = (t: string) => Number(t.replace(/\./g, ""));

test.describe("Dashboard", () => {
  test.beforeEach(async ({ page }) => {
    await page.goto("/");
  });

  test("resumo de hoje reflete a fila, os envios e os telefones inválidos", async ({ page }) => {
    await expect(page.locator(".periodo-card", { hasText: "Hoje" }).first()).toHaveAttribute("aria-pressed", "true");
    await expect(stat(page, "Cobranças")).not.toHaveText("0");
    await expect(stat(page, "Pendentes na fila")).not.toHaveText("0");
    await expect(stat(page, "Telefones inválidos")).not.toHaveText("0");
    const porFaixa = card(page, "Por faixa");
    await expect(porFaixa.locator("tbody tr", { hasText: "3 A 10" })).toBeVisible();
  });

  test("Dashboard não tem mais a lista de erros recentes", async ({ page }) => {
    await expect(stat(page, "Erros de envio")).not.toHaveText("…");
    await expect(page.getByRole("heading", { name: "Erros recentes" })).toHaveCount(0);
  });

  test("botão de período que fica azul no hover mostra o texto branco", async ({ page }) => {
    const botao = page.locator(".periodo-card", { hasText: "Últimos 7 dias" }).first();
    await botao.hover();
    await expect(botao).toHaveCSS("color", "rgb(255, 255, 255)");
  });

  test("cards de período: 7 dias, mês e personalizado com datas", async ({ page }) => {
    const enviadosHoje = await stat(page, "Cobranças").innerText();
    await page.locator(".periodo-card", { hasText: "Últimos 7 dias" }).first().click();
    await expect(page.locator(".periodo-card", { hasText: "Últimos 7 dias" }).first()).toHaveAttribute("aria-pressed", "true");
    await expect(stat(page, "Cobranças")).toHaveText(enviadosHoje);
    await page.locator(".periodo-card", { hasText: "Personalizado" }).first().click();
    const periodo = page.locator(".periodo-filtro").first();
    await periodo.locator('input[type="date"]').first().fill("2020-01-01");
    await periodo.locator('input[type="date"]').nth(1).fill("2020-01-31");
    await expect(stat(page, "Cobranças")).toHaveText("0");
    await expect(stat(page, "Pendentes na fila")).toHaveText("0");
  });

  test("período sem movimento mostra o estado vazio, sem faixas excluídas", async ({ page }) => {
    await page.locator(".periodo-card", { hasText: "Personalizado" }).first().click();
    const periodo = page.locator(".periodo-filtro").first();
    await periodo.locator('input[type="date"]').first().fill("2020-01-01");
    await periodo.locator('input[type="date"]').nth(1).fill("2020-01-31");
    await expect(stat(page, "Cobranças")).toHaveText("0");
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
    ["Cobranças", "envios"],
    ["Erros de envio", "erros"],
    ["Telefones inválidos", "invalidos"],
  ] as const) {
    test(`card '${rotulo}' abre o relatório '${aba}' do mesmo período com o mesmo total`, async ({ page }) => {
      const valor = stat(page, rotulo);
      await expect(valor).not.toHaveText("…");
      const n = numero(await valor.innerText());
      const link = page.getByRole("link", { name: new RegExp(`^Ver ${n.toLocaleString("pt-BR").replace(/\./g, "\\.")} `) }).filter({ has: page.locator(".label", { hasText: rotulo }) });
      await link.hover();
      await link.click();
      // A tela roda em GMT-3 (playwright.config); o processo do teste, no fuso da máquina
      const hoje = new Date().toLocaleDateString("sv-SE", { timeZone: "America/Sao_Paulo" });
      await expect(page).toHaveURL(new RegExp(`/relatorios\\?aba=${aba}&de=${hoje}&ate=${hoje}$`));
      await expect(page.getByText("Carregando...")).toHaveCount(0, { timeout: 30_000 });
      if (n === 0) {
        await expect(page.locator(".empty-state")).toBeVisible();
      } else {
        await expect(page.locator(".paginacao-info")).toContainText(`de ${n}`);
      }
    });
  }

  test("card 'Pagaram em até 7 dias' mostra % e valor e abre Quem pagou com janela 7 e o mesmo total", async ({ page }) => {
    await page.locator(".periodo-card", { hasText: "Este mês" }).first().click();
    const valor = stat(page, "Pagaram em até 7 dias");
    await expect(valor).not.toHaveText("…", { timeout: 30_000 });
    const n = numero(await valor.innerText());
    const cardPagos = page.locator(".stat", { has: page.locator(".label", { hasText: "Pagaram em até 7 dias" }) });
    await expect(cardPagos).toContainText(/% dos cobrados · R\$/);
    await cardPagos.click();
    await expect(page).toHaveURL(/aba=pagamentos&de=\d{4}-\d{2}-01&ate=.*&dias_janela=7/);
    await expect(page.getByLabel("Pagou em até")).toHaveValue("7");
    if (n > 0) {
      await expect(page.locator(".stat", { hasText: "Clientes que pagaram" }).locator(".value")).toHaveText(n.toLocaleString("pt-BR"), {
        timeout: 30_000,
      });
    } else {
      await expect(page.getByText("Ninguém pagou no período")).toBeVisible({ timeout: 30_000 });
    }
  });

  test("card 'Pagaram em até 7 dias' com SETA fora avisa só nele", async ({ page }) => {
    permitirErrosConsole(page, "503");
    await page.route("**/dashboard/pagos-7-dias*", (r) =>
      r.fulfill({ status: 503, contentType: "application/json", body: JSON.stringify({ detail: "SETA indisponível" }) })
    );
    await page.reload();
    const cardPagos = page.locator(".stat", { has: page.locator(".label", { hasText: "Pagaram em até 7 dias" }) });
    await expect(cardPagos).toContainText("SETA indisponível");
    await expect(stat(page, "Cobranças")).not.toHaveText("…");
    await expect(page.locator(".error-box")).toHaveCount(0);
  });

  test("números dos cards saem com separador de milhar e o card fica mais largo que alto", async ({ page }) => {
    await page.route("**/dashboard/summary**", async (r) => {
      const res = await r.fetch();
      const json = { ...(await res.json()), total_pendentes: 12345, total_pausados: 1234, total_enviados: 98765 };
      await r.fulfill({ response: res, json });
    });
    await page.reload();
    await expect(stat(page, "Pendentes na fila")).toHaveText("12.345");
    await expect(stat(page, "Cobranças")).toHaveText("98.765");
    await expect(page.locator("a.stat-link").first()).toContainText("12.345 pendentes · 1.234 pausados");
    const caixa = (await page.locator("a.stat-link").first().boundingBox())!;
    expect(caixa.width).toBeGreaterThan(caixa.height);
  });

  test("card é navegável pelo teclado e a linha da faixa abre o relatório filtrado", async ({ page }) => {
    const pend = page.locator("a.stat-link").first();
    await pend.focus();
    await expect(pend).toBeFocused();
    await expect(pend).toContainText("Ver detalhes →");
    const linha = card(page, "Por faixa").locator("tbody tr", { hasText: "3 A 10" });
    const enviados = (await linha.locator("td").nth(3).innerText()).trim();
    await linha.locator("td").nth(3).getByRole("link").click();
    await expect(page).toHaveURL(/aba=envios.*faixa_id=/);
    await expect(page.locator("select").first()).toHaveValue(/.+/);
    await expect(page.getByText("Carregando...")).toHaveCount(0);
    if (enviados !== "0") await expect(page.locator(".paginacao-info")).toContainText(`de ${enviados}`);
  });

  test("por faixa mostra quem pagou após a cobrança e abre Quem pagou da faixa com o mesmo total", async ({ page }) => {
    const porFaixa = card(page, "Por faixa");
    await expect(porFaixa.getByRole("columnheader", { name: /Pagaram após cobrança/ })).toBeVisible();
    await expect(porFaixa.getByRole("columnheader", { name: /Valor pago/ })).toBeVisible();
    // O SETA falso tem clientes que pagam hoje: alguma faixa cobrada hoje tem pagamento
    const linha = porFaixa.locator("tbody tr").filter({ has: page.locator("td:nth-child(7) a", { hasText: /^[1-9]/ }) }).first();
    await expect(linha).toBeVisible({ timeout: 30_000 });
    const pagaram = numero(await linha.locator("td").nth(6).innerText());
    await expect(linha.locator("td").nth(9)).toContainText(/R\$\s?[1-9]/);
    await linha.locator("td").nth(6).getByRole("link").click();
    await expect(page).toHaveURL(/aba=pagamentos.*faixa_id=/);
    await expect(page.locator(".stat", { hasText: "Clientes que pagaram" }).locator(".value")).toHaveText(
      pagaram.toLocaleString("pt-BR"),
      { timeout: 30_000 }
    );
  });

  test("tabela por faixa ordena pela ordem de atraso e por números", async ({ page }) => {
    const porFaixa = card(page, "Por faixa");
    await porFaixa.getByRole("columnheader", { name: /^Enviado/ }).click();
    const col = async () => (await porFaixa.locator("tbody tr td:nth-child(4)").allInnerTexts()).map(Number);
    const v = await col();
    expect(v).toEqual([...v].sort((a, b) => a - b));
  });

  test("por faixa: ordem das colunas, indicadores com fórmula e linha de total", async ({ page }) => {
    const porFaixa = card(page, "Por faixa");
    await expect(porFaixa.locator("thead th")).toHaveText([
      /^Faixa/, /^Pendente/, /^Erro/, /^Enviado/, /^Clientes cobrados/, /^Frequência/,
      /^Pagaram após cobrança/, /^%\sConv\./, /^%\sRep\./, /^Valor pago/,
    ]);
    const linhas = porFaixa.locator("tbody tr");
    await expect(linhas.first()).toBeVisible();
    const n = await linhas.count();
    const col = async (i: number) => (await linhas.locator(`td:nth-child(${i + 1})`).allInnerTexts()).map((t) => t.trim());
    const pct = (t: string) => (t === "—" ? null : Number(t.replace("%", "").replace(",", ".")));
    const soma = (v: string[]) => v.reduce((s, t) => s + numero(t), 0);

    // % Rep. soma 100% quando alguém pagou (ou é 0,0% em todas as faixas)
    const pagaram = await col(6);
    const reps = (await col(8)).map(pct);
    if (soma(pagaram) > 0) expect(Math.abs(reps.reduce((s: number, v) => s + (v ?? 0), 0) - 100)).toBeLessThan(0.1 * n + 0.01);

    // Total = soma das faixas; % Conv. do total = pagaram ÷ clientes cobrados
    const total = porFaixa.locator("tfoot tr.linha-total td");
    await expect(total.first()).toHaveText("Total");
    for (const i of [1, 2, 3, 4, 6]) {
      await expect(total.nth(i)).toHaveText(soma(await col(i)).toLocaleString("pt-BR"));
    }
    const cobrados = soma(await col(4));
    const conv = cobrados
      ? new Intl.NumberFormat("pt-BR", { style: "percent", minimumFractionDigits: 1, maximumFractionDigits: 1 }).format(soma(pagaram) / cobrados)
      : "—";
    await expect(total.nth(7)).toHaveText(conv);
    await expect(total.nth(8)).toHaveText("");

    // 🛈 abre a dica com a fórmula e não reordena a tabela
    const ordemAntes = await col(0);
    await porFaixa.getByRole("button", { name: /O que é %\sConv\./ }).hover();
    await expect(page.getByRole("tooltip")).toContainText("Pagaram após cobrança ÷ Clientes cobrados × 100");
    await porFaixa.getByRole("button", { name: /O que é %\sRep\./ }).click();
    await expect(page.getByRole("tooltip")).toContainText("Σ Pagaram após cobrança de todas as faixas");
    expect(await col(0)).toEqual(ordemAntes);
  });

  test("matriz cluster × faixa: aplicar, abas e clique leva para Cobrança filtrada", async ({ page }) => {
    const m = card(page, "Base de cobrança — cluster × faixa");
    await expect(m).toContainText("Aplique os filtros para ver a matriz cluster × faixa.");
    await m.getByLabel("Somente o primeiro dia da faixa").uncheck();
    await m.getByLabel("Somente clientes da regra WhatsApp").uncheck();
    await m.getByRole("button", { name: "Aplicar filtros" }).click();
    await expect(m.locator("table")).toBeVisible({ timeout: 30_000 });
    await expect(m).toContainText("ESPECIAL");
    await m.getByRole("tab", { name: "Valor em aberto" }).click();
    await expect(m.getByRole("tab", { name: "Valor em aberto" })).toHaveAttribute("aria-selected", "true");
    await expect(m.locator("table")).toContainText("R$");
    await m.getByRole("tab", { name: "Valor em atraso" }).click();
    await expect(m.getByRole("tab", { name: "Valor em atraso" })).toHaveAttribute("aria-selected", "true");
    await expect(m.locator("table")).toContainText("R$");
    await expect(m).toContainText("Soma só as parcelas já vencidas, pelo valor original");
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

  test("orçamento: exportar por dia traz data, WABA, telefone e valor, somando o realizado", async ({ page }) => {
    const o = card(page, "Orçamento");
    await expect(o.locator("table")).toBeVisible({ timeout: 30_000 });
    const brl = (t: string) => Number(t.replace(/[^\d,]/g, "").replace(",", "."));
    const realizado = brl(await o.locator(".stat", { hasText: "Realizado" }).locator(".value").innerText());
    const { nome, linhas } = await baixar(page, () => o.getByRole("button", { name: "Exportar por dia" }).click());
    expect(nome).toMatch(/^orcamento_por_dia_.*\.xlsx$/);
    expect(linhas[0]).toEqual(["Data", "WABA", "Telefone", "Mensagens cobradas", "Valor cobrado (R$)"]);
    const dados = linhas.slice(1);
    expect(dados.length).toBeGreaterThan(1);
    expect(dados.every((l) => l[1] !== "" && /\d/.test(l[2]))).toBe(true);
    expect(dados.reduce((a, l) => a + Number(l[4]), 0)).toBeCloseTo(realizado, 1);
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
  test("resumo e leads se atualizam sozinhos, sem F5, e param com a aba oculta", async ({ page }) => {
    await page.clock.install();
    await Promise.all([page.waitForResponse((r) => r.url().includes("/dashboard/summary?")), page.reload()]);
    await expect(stat(page, "Pendentes na fila")).not.toHaveText("999");
    await expect(page.locator(".atualizacao-auto")).toContainText(/atualizado às \d{2}:\d{2}/);
    const pedidos: URL[] = [];
    page.on("request", (r) => {
      const u = new URL(r.url());
      if (/\/(dashboard\/(summary|pagos-7-dias)|leads)$/.test(u.pathname)) pedidos.push(u);
    });
    // Simula um envio acontecendo enquanto a tela está aberta
    // resumo real lido pela API (ler o corpo da resposta do reload falha quando ela
    // é de antes da navegação)
    const resumoReal = await apiGet(page, "/dashboard/summary");
    await page.route("**/dashboard/summary?*", (r) => r.fulfill({ json: { ...resumoReal, total_pendentes: 999 } }));
    const resumos = () => pedidos.filter((u) => u.pathname.endsWith("/dashboard/summary"));

    await page.clock.runFor(31_000);
    await expect(stat(page, "Pendentes na fila")).toHaveText("999");
    expect(resumos().every((u) => u.searchParams.get("auto") === "true")).toBe(true);
    // O card do SETA não se atualiza sozinho
    expect(pedidos.some((u) => u.pathname.endsWith("/pagos-7-dias"))).toBe(false);
    await page.clock.runFor(30_000);
    await expect.poll(() => pedidos.filter((u) => u.pathname.endsWith("/leads")).length).toBeGreaterThan(0);

    // Aba oculta: nenhum pedido; ao voltar, atualiza na hora
    const ocultar = (oculta: boolean) =>
      page.evaluate((o) => {
        Object.defineProperty(document, "hidden", { configurable: true, get: () => o });
        Object.defineProperty(document, "visibilityState", { configurable: true, get: () => (o ? "hidden" : "visible") });
        document.dispatchEvent(new Event("visibilitychange"));
      }, oculta);
    await ocultar(true);
    const antes = resumos().length;
    await page.clock.runFor(5 * 60_000);
    expect(resumos().length).toBe(antes);
    await ocultar(false);
    await expect.poll(() => resumos().length).toBe(antes + 1);
  });

  test("'Atualizar agora' recarrega tudo, inclusive o card do SETA, sem apagar os números", async ({ page }) => {
    await expect(stat(page, "Pagaram em até 7 dias")).not.toHaveText("…", { timeout: 30_000 });
    const pedidos: URL[] = [];
    page.on("request", (r) => pedidos.push(new URL(r.url())));
    await page.getByRole("button", { name: "Atualizar agora" }).click();
    await expect.poll(() => pedidos.some((u) => u.pathname.endsWith("/dashboard/pagos-7-dias"))).toBe(true);
    const resumo = pedidos.find((u) => u.pathname.endsWith("/dashboard/summary"));
    expect(resumo?.searchParams.get("auto")).toBeNull();
    await expect(page.locator(".loading-state")).toHaveCount(0);
    await expect(stat(page, "Pagaram em até 7 dias")).not.toHaveText("…");
  });
});
