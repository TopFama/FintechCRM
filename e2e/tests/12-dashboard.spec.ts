import { apiGet, apiSend, baixar, card, escolherMulti, expect, permitirErrosConsole, test } from "./fixtures";
import type { Page } from "@playwright/test";
import { prepararOperacao } from "./preparo";

const stat = (page: Page, rotulo: string) =>
  page.locator(".stat", { has: page.locator(".label", { hasText: new RegExp(`^${rotulo.replace(/[()]/g, "\\$&")}$`) }) }).locator(".value").first();

// Cenário que troca a resposta do /summary: sem o tempo real, que mandaria os
// números de verdade por cima (4000 = a tela não tenta reconectar)
const semTempoReal = (page: Page) => page.routeWebSocket(/\/dashboard\/ws/, (ws) => ws.close({ code: 4000 }));

// "12.345" → 12345 (os cards mostram separador de milhar)
const numero = (t: string) => Number(t.replace(/\./g, ""));

test.beforeAll(prepararOperacao);

test.describe("Dashboard", { tag: "@dashboard" }, () => {
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

  test("cards da fila mudam na hora, sem esperar a atualização de 30 s", { tag: ["@pausas"] }, async ({ page }) => {
    const hoje = new Date().toLocaleDateString("sv-SE", { timeZone: "America/Sao_Paulo" });
    const linha = page.locator(".stat-extra", { hasText: "pausados" });
    const pausados = async () => numero((await linha.innerText()).match(/([\d.]+) pausados/)![1]);
    await expect(linha).toBeVisible();
    const antes = await pausados();
    const faixa = (await apiGet(page, "/faixas")).find((f: any) => f.name === "11 A 20");
    const pausa = await apiSend(page, "POST", "/pausas", { escopo: "faixa", valor: faixa.id, motivo: "Tempo real" });
    expect(pausa.status).toBe(201);
    try {
      // bem antes do próximo polling (30 s): veio pelo WebSocket
      await expect.poll(pausados, { timeout: 10_000 }).toBeGreaterThan(antes);
      // e bate com o resumo do banco (que guarda o cálculo por alguns segundos)
      const card = await pausados();
      await expect.poll(async () => (await apiGet(page, `/dashboard/summary?de=${hoje}&ate=${hoje}`)).total_pausados, { timeout: 10_000 }).toBe(card);
    } finally {
      await apiSend(page, "POST", `/pausas/${pausa.corpo.id}/retomar`);
    }
    await expect.poll(pausados, { timeout: 10_000 }).toBe(antes);
  });

  test("Dashboard não tem mais a lista de erros recentes", async ({ page }) => {
    await expect(stat(page, "Erros de envio")).not.toHaveText("…");
    await expect(page.getByRole("heading", { name: "Erros recentes" })).toHaveCount(0);
  });

  test("botão de período que fica azul no hover mostra o texto branco", { tag: ["@visual"] }, async ({ page }) => {
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
    test(`card '${rotulo}' abre o relatório '${aba}' do mesmo período com o mesmo total`, { tag: ["@relatorios"] }, async ({ page }) => {
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

  test("card 'Pagaram em até 7 dias' mostra % e valor e abre Quem pagou com janela 7 e o mesmo total", { tag: ["@pagos-janela","@pagamentos"] }, async ({ page }) => {
    // No dia 1º, "Hoje" e "Este mês" são o mesmo período e o cache de 5 min do card pode ter
    // guardado o número de antes das cobranças dos cenários anteriores
    await apiSend(page, "POST", "/__e2e/cache/limpar");
    await page.goto("/");
    await page.locator(".periodo-card", { hasText: "Este mês" }).first().click();
    const valor = stat(page, "Pagaram em até 7 dias");
    await expect(valor).not.toHaveText("…", { timeout: 30_000 });
    const n = numero(await valor.innerText());
    const cardPagos = page.locator(".stat", { has: page.locator(".label", { hasText: "Pagaram em até 7 dias" }) });
    await expect(cardPagos).toContainText(/% dos cobrados · R\$/);
    await cardPagos.click();
    await expect(page).toHaveURL(/aba=pagamentos&de=\d{4}-\d{2}-01&ate=.*&dias_janela=7/);
    await expect(page.getByLabel("Janela de pagamento")).toHaveValue("7");
    if (n > 0) {
      await expect(page.locator(".stat", { hasText: "Clientes que pagaram" }).locator(".value")).toHaveText(n.toLocaleString("pt-BR"), {
        timeout: 30_000,
      });
    } else {
      await expect(page.getByText("Ninguém pagou no período")).toBeVisible({ timeout: 30_000 });
    }
  });

  test("card de pagamentos segue a janela de Indicadores e abre Quem pagou com ela", { tag: ["@pagos-janela","@pagamentos"] }, async ({ page }) => {
    await apiSend(page, "PUT", "/config/cobranca/parametros", { dias_janela_dashboard: 15 });
    try {
      await page.reload();
      const valor = stat(page, "Pagaram em até 15 dias");
      await expect(valor).not.toHaveText("…", { timeout: 30_000 });
      await page.locator(".stat", { has: page.locator(".label", { hasText: "Pagaram em até 15 dias" }) }).click();
      await expect(page).toHaveURL(/aba=pagamentos.*&dias_janela=15/);
      await expect(page.getByLabel("Janela de pagamento")).toHaveValue("15");

      await apiSend(page, "PUT", "/config/cobranca/parametros", { dias_janela_dashboard: null });
      await page.goto("/");
      const cardSemLimite = page.locator(".stat", { has: page.locator(".label", { hasText: "Pagaram após a cobrança" }) });
      await expect(cardSemLimite.locator(".value")).not.toHaveText("…", { timeout: 30_000 });
      await cardSemLimite.click();
      await expect(page).toHaveURL(/aba=pagamentos/);
      await expect(page).not.toHaveURL(/dias_janela/);
      await expect(page.getByLabel("Janela de pagamento")).toHaveValue("");
    } finally {
      await apiSend(page, "PUT", "/config/cobranca/parametros", { dias_janela_dashboard: 7 });
    }
  });

  test("card 'Pagaram em até 7 dias' com SETA fora avisa só nele", { tag: ["@pagos-janela","@pagamentos","@resiliencia"] }, async ({ page }) => {
    permitirErrosConsole(page, "503");
    await page.route("**/dashboard/janela-pagamento*", (r) =>
      r.fulfill({ status: 503, contentType: "application/json", body: JSON.stringify({ detail: "Falha ao consultar o SETA (OperationalError)", codigo: "seta_indisponivel" }) })
    );
    await page.reload();
    // sem resposta não se sabe a janela: o rótulo fica só "Pagaram"
    const cardPagos = page.locator(".stat", { has: page.locator(".label", { hasText: /^Pagaram$/ }) });
    await expect(cardPagos).toContainText("SETA indisponível");
    await expect(stat(page, "Cobranças")).not.toHaveText("…");
    await expect(page.locator(".error-box")).toHaveCount(0);
  });

  test("SETA sem conexão: faixa no topo em todas as telas até o teste de conexão passar", { tag: ["@pagos-janela","@resiliencia"] }, async ({ page }) => {
    permitirErrosConsole(page, "503");
    // o backend avisa em toda resposta enquanto o SETA está sem conexão
    let semConexao = true;
    await page.route(/localhost:8010\//, async (r) => {
      if (!semConexao) return r.fallback();
      const resposta = await r.fetch();
      const headers = { ...resposta.headers() };
      if (semConexao) headers["x-seta-fora"] = "2026-10-10T17:32:00+00:00";
      await r.fulfill({ response: resposta, headers });
    });
    await page.route("**/dashboard/janela-pagamento*", (r) =>
      r.fulfill({
        status: 503,
        contentType: "application/json",
        headers: { "x-seta-fora": "2026-10-10T17:32:00+00:00", "access-control-expose-headers": "X-Seta-Fora" },
        body: JSON.stringify({ detail: "Não foi possível conectar ao SETA (OperationalError)", codigo: "seta_indisponivel" }),
      })
    );
    await page.reload();
    const faixa = page.locator(".aviso-seta-fora");
    await expect(faixa).toContainText(/Sem conexão com o SETA desde 10\/10\/2026,? 14:32/);
    await expect(page.locator(".stat", { has: page.locator(".label", { hasText: /^Pagaram$/ }) })).toContainText("SETA indisponível");
    await page.getByRole("link", { name: "Relatórios" }).click();
    await expect(faixa).toBeVisible();
    // SETA voltou: o teste de conexão é a primeira resposta sem o aviso e a faixa some
    await page.route("**/seta/status", (r) => {
      semConexao = false;
      return r.continue();
    });
    await faixa.getByRole("button", { name: "Testar conexão" }).click();
    await expect(faixa).toHaveCount(0);
  });

  test("Redis fora tem mensagem própria, sem falar em SETA", { tag: ["@pagos-janela","@resiliencia"] }, async ({ page }) => {
    permitirErrosConsole(page, "503");
    await page.route("**/dashboard/janela-pagamento*", (r) =>
      r.fulfill({ status: 503, contentType: "application/json", body: JSON.stringify({ detail: "Cache Redis indisponível (ConnectionError)", codigo: "cache_indisponivel" }) })
    );
    await page.reload();
    const cardPagos = page.locator(".stat", { has: page.locator(".label", { hasText: /^Pagaram$/ }) });
    await expect(cardPagos).toContainText("Cache Redis indisponível");
    await expect(cardPagos).not.toContainText("SETA");
    await expect(page.locator(".aviso-seta-fora")).toHaveCount(0);
  });

  test("números dos cards saem com separador de milhar e o card fica mais largo que alto", { tag: ["@visual"] }, async ({ page }) => {
    await semTempoReal(page);
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

  test("por faixa mostra quem pagou após a cobrança e abre Quem pagou da faixa com o mesmo total", { tag: ["@pagamentos"] }, async ({ page }) => {
    const porFaixa = card(page, "Por faixa");
    await expect(porFaixa.getByRole("columnheader", { name: /Pagaram após cobrança/ })).toBeVisible();
    await expect(porFaixa.getByRole("columnheader", { name: /Valor pago/ })).toBeVisible();
    // O SETA falso tem clientes que pagam hoje: alguma faixa cobrada hoje tem pagamento
    const linha = porFaixa.locator("tbody tr").filter({ has: page.locator("td:nth-child(7) a", { hasText: /^[1-9]/ }) }).first();
    await expect(linha).toBeVisible({ timeout: 30_000 });
    const pagaram = numero(await linha.locator("td").nth(6).innerText());
    await expect(linha.locator("td").nth(9)).toContainText(/R\$\s?[1-9]/);
    await linha.locator("td").nth(6).getByRole("link").click();
    await expect(page).toHaveURL(/aba=pagamentos.*faixa_id=.*base=envios/);
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

  test("por faixa: ordem das colunas, indicadores com fórmula e linha de total", { tag: ["@visual","@pagamentos"] }, async ({ page }) => {
    const porFaixa = card(page, "Por faixa");
    await expect(porFaixa.locator("thead th")).toHaveText([
      /^Faixa/, /^Pendente/, /^Erro/, /^Enviado/, /^Clientes cobrados/, /^Frequência/,
      /^Pagaram após cobrança/, /^%\sRep\./, /^%\sConv\./, /^Valor pago/, /^ROAS/,
    ]);
    const linhas = porFaixa.locator("tbody tr");
    await expect(linhas.first()).toBeVisible();
    const n = await linhas.count();
    const col = async (i: number) => (await linhas.locator(`td:nth-child(${i + 1})`).allInnerTexts()).map((t) => t.trim());
    const pct = (t: string) => (t === "—" ? null : Number(t.replace("%", "").replace(",", ".")));
    const soma = (v: string[]) => v.reduce((s, t) => s + numero(t), 0);

    // % Rep. soma 100% quando alguém pagou (ou é 0,0% em todas as faixas)
    const pagaram = await col(6);
    const reps = (await col(7)).map(pct);
    if (soma(pagaram) > 0) expect(Math.abs(reps.reduce((s: number, v) => s + (v ?? 0), 0) - 100)).toBeLessThan(0.1 * n + 0.01);

    // Total: Pendente, Erro e Enviado somam a coluna; Clientes cobrados e
    // Pagaram contam cada cliente uma vez (no máximo a soma da coluna);
    // % Conv. do total = Pagaram ÷ Clientes cobrados do próprio total
    const total = porFaixa.locator("tfoot tr.linha-total td");
    await expect(total.first()).toHaveText("Total");
    for (const i of [1, 2, 3]) {
      await expect(total.nth(i)).toHaveText(soma(await col(i)).toLocaleString("pt-BR"));
    }
    const cobrados = numero(await total.nth(4).innerText());
    const pagaramTotal = numero(await total.nth(6).innerText());
    expect(cobrados).toBeGreaterThan(0);
    expect(cobrados).toBeLessThanOrEqual(soma(await col(4)));
    expect(pagaramTotal).toBeLessThanOrEqual(soma(pagaram));
    expect(pagaramTotal > 0).toBe(soma(pagaram) > 0);
    const convTotal = new Intl.NumberFormat("pt-BR", { style: "percent", minimumFractionDigits: 1, maximumFractionDigits: 1 }).format(
      pagaramTotal / cobrados
    );
    await expect(total.nth(8)).toHaveText(convTotal);
    await expect(total.nth(7)).toHaveText("");
    // ROAS: multiplicador ("4,25x") ou "—" sem custo da Meta
    for (const t of [...(await col(10)), await total.nth(10).innerText()]) expect(t.trim()).toMatch(/^(\d[\d.]*,\d{2}x|—)$/);

    // 🛈 abre a dica com a fórmula e não reordena a tabela
    const ordemAntes = await col(0);
    await porFaixa.getByRole("button", { name: /O que é %\sConv\./ }).hover();
    await expect(page.getByRole("tooltip")).toContainText("Pagaram após cobrança ÷ Clientes cobrados × 100");
    await porFaixa.getByRole("button", { name: /O que é %\sRep\./ }).click();
    await expect(page.getByRole("tooltip")).toContainText("Σ Pagaram após cobrança de todas as faixas");
    // Tocar no balão só fecha a dica: não reordena nem abre o relatório da linha
    await page.getByRole("tooltip").click();
    await expect(page.getByRole("tooltip")).toHaveCount(0);
    await expect(page).toHaveURL(/\/$/);
    // Clicar no 🛈 abre e fixa; clicar de novo fecha
    const conv = porFaixa.getByRole("button", { name: /O que é %\sConv\./ });
    await conv.click();
    await expect(page.getByRole("tooltip")).toContainText("Clientes cobrados × 100");
    await conv.click();
    await expect(page.getByRole("tooltip")).toHaveCount(0);
    await porFaixa.getByRole("button", { name: /O que é ROAS/ }).hover();
    await expect(page.getByRole("tooltip")).toContainText("Valor pago ÷ Custo do WhatsApp");
    expect(await col(0)).toEqual(ordemAntes);
  });

  test("por faixa: colunas se arrastam pelo título e a ordem fica salva na conta", async ({ page }) => {
    const porFaixa = card(page, "Por faixa");
    const titulos = porFaixa.locator("thead th");
    const pendente = porFaixa.getByRole("columnheader", { name: /^Pendente/ });
    await expect(porFaixa.locator("tbody tr").first()).toBeVisible();
    await expect(titulos.nth(1)).toHaveText(/^Pendente/);
    const pendentes = await porFaixa.locator("tbody tr td:nth-child(2)").allInnerTexts();
    try {
      // Arrastar "Pendente" para cima de "ROAS" (a última) leva a coluna para depois dela, com os números junto
      await pendente.dragTo(porFaixa.getByRole("columnheader", { name: /^ROAS/ }));
      await expect(titulos.last()).toHaveText(/^Pendente/);
      await expect(titulos.nth(1)).toHaveText(/^Erro/);
      await expect(titulos.nth(8)).toHaveText(/^Valor pago/);
      await expect(titulos.nth(9)).toHaveText(/^ROAS/);
      expect(await porFaixa.locator("tbody tr td:last-child").allInnerTexts()).toEqual(pendentes);
      await expect(porFaixa.locator("tfoot tr.linha-total td").last()).not.toContainText("R$");
      // Arrastar não ordena a tabela; clicar no título continua ordenando
      await expect(pendente).toHaveAttribute("aria-sort", "none");
      await pendente.click();
      await expect(pendente).toHaveAttribute("aria-sort", "ascending");
      // Faixa fica fixa na primeira coluna
      await expect(titulos.first()).not.toHaveAttribute("draggable", "true");

      // A ordem vem da conta: volta igual depois de recarregar
      await page.reload();
      await expect(titulos.last()).toHaveText(/^Pendente/);
      expect((await apiGet(page, "/dashboard/colunas-por-faixa")).colunas.at(-1)).toBe("pending");
    } finally {
      // Os outros testes usam o mesmo usuário e contam com a ordem padrão
      await apiSend(page, "PUT", "/dashboard/colunas-por-faixa", { colunas: [] });
    }
  });

  test("por faixa: números e títulos centralizados, inclusive título quebrado em duas linhas", { tag: ["@visual"] }, async ({ page }) => {
    const porFaixa = card(page, "Por faixa");
    await expect(porFaixa.locator("tbody tr").first()).toBeVisible();
    // Faixa fica à esquerda; as outras colunas, centralizadas
    const alinhamento = (sel: string) =>
      porFaixa.locator(sel).evaluateAll((els) => els.map((el) => getComputedStyle(el).textAlign));
    expect(await alinhamento("thead th")).toEqual(["left", ...Array(10).fill("center")]);
    expect(await alinhamento("tbody tr:first-child td")).toEqual(["left", ...Array(10).fill("center")]);
    expect(await alinhamento("tfoot tr td")).toEqual(["left", ...Array(10).fill("center")]);

    // O bloco do título (texto, dica e seta) fica no meio da célula, mesmo quebrado
    const desvios = await porFaixa.locator("thead th").evaluateAll((ths) =>
      ths.slice(1).map((th) => {
        const c = th.getBoundingClientRect();
        const cs = getComputedStyle(th);
        const meio = c.left + parseFloat(cs.paddingLeft) + (c.width - parseFloat(cs.paddingLeft) - parseFloat(cs.paddingRight)) / 2;
        const inner = th.querySelector(".th-sortable-inner")!;
        const range = document.createRange();
        range.selectNodeContents(inner);
        const r = range.getBoundingClientRect();
        return Math.abs(r.left + r.width / 2 - meio);
      })
    );
    for (const d of desvios) expect(d).toBeLessThan(4);
  });

  test("por faixa: altura ajustável na barra, com cabeçalho, total e faixa fixos na rolagem", { tag: ["@visual"] }, async ({ page }) => {
    const porFaixa = card(page, "Por faixa");
    const wrap = porFaixa.locator(".tabela-ajustavel");
    const alca = porFaixa.getByRole("separator", { name: "Ajustar altura da tabela Por faixa" });
    await expect(porFaixa.locator("tbody tr").first()).toBeVisible();
    const alturaInicial = (await wrap.boundingBox())!.height;
    expect(alturaInicial).toBeGreaterThan(130);

    // Arrastar a barra para cima diminui a área visível (mínimo 120 px)
    const b = (await alca.boundingBox())!;
    await page.mouse.move(b.x + b.width / 2, b.y + b.height / 2);
    await page.mouse.down();
    await page.mouse.move(b.x + b.width / 2, b.y + b.height / 2 - (alturaInicial - 125), { steps: 5 });
    await page.mouse.up();
    await expect.poll(async () => Math.round((await wrap.boundingBox())!.height)).toBeLessThanOrEqual(126);
    expect(await wrap.evaluate((w) => w.scrollHeight > w.clientHeight)).toBe(true);

    // Rolando, o cabeçalho fica no topo, o total embaixo e a faixa à esquerda
    await wrap.evaluate((w) => {
      w.scrollTop = 40;
      w.scrollLeft = 200;
    });
    const caixa = (await wrap.boundingBox())!;
    const th = (await porFaixa.locator("thead th").first().boundingBox())!;
    const total = (await porFaixa.locator("tr.linha-total td").first().boundingBox())!;
    const faixa = (await porFaixa.locator("tbody tr").nth(1).locator("td").first().boundingBox())!;
    expect(Math.abs(th.y - caixa.y)).toBeLessThan(2);
    expect(total.y + total.height).toBeLessThanOrEqual(caixa.y + caixa.height + 1);
    expect(total.y).toBeGreaterThan(caixa.y);
    expect(Math.abs(faixa.x - caixa.x)).toBeLessThan(2);

    // ↓ no teclado aumenta; a altura escolhida volta depois de recarregar
    await alca.focus();
    await page.keyboard.press("ArrowDown");
    await expect.poll(async () => Math.round((await wrap.boundingBox())!.height)).toBeGreaterThan(150);
    const escolhida = Math.round((await wrap.boundingBox())!.height);
    await page.reload();
    await expect(porFaixa.locator("tbody tr").first()).toBeVisible();
    await expect.poll(async () => Math.round((await wrap.boundingBox())!.height)).toBe(escolhida);

    // Duplo clique volta ao tamanho padrão
    await alca.dblclick();
    await expect.poll(async () => Math.round((await wrap.boundingBox())!.height)).toBe(Math.round(alturaInicial));
  });


  test("matriz cluster × faixa: aplicar, abas e clique leva para Cobrança filtrada", { tag: ["@cobranca"] }, async ({ page }) => {
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

  test("efetividade: janela 'Outro' valida 0–365 e bloqueia botões", { tag: ["@efetividade"] }, async ({ page }) => {
    const e = card(page, "Efetividade da cobrança");
    await e.getByLabel("Janela de pagamento").selectOption({ label: "Até 3 dias" });
    await expect(e.getByLabel("Janela de pagamento")).toHaveValue("3");
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

  test("efetividade: por faixa e por loja com linha de total; quem pagou hoje conta", { tag: ["@efetividade","@pagamentos"] }, async ({ page }) => {
    const e = card(page, "Efetividade da cobrança");
    await e.getByLabel("Janela de pagamento").selectOption({ label: "Qualquer data após a cobrança" });
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
    // ROAS nas três visões, com o 🛈 explicando a conta
    await expect(e.getByRole("columnheader", { name: /^ROAS/ })).toBeVisible();
    await e.getByRole("button", { name: /O que é ROAS/ }).hover();
    await expect(page.getByRole("tooltip")).toContainText("Recebimento ÷ Custo do WhatsApp");
    await expect(total.locator("td").last()).toHaveText(/^(\d[\d.]*,\d{2}x|—)$/);
  });

  test("efetividade: Aplicar fica desabilitado enquanto consulta e clique repetido não duplica o pedido ao SETA", { tag: ["@efetividade","@resiliencia"] }, async ({ page }) => {
    const e = card(page, "Efetividade da cobrança");
    const pedidos: string[] = [];
    // segura a resposta para dar tempo de clicar de novo
    await page.route("**/reports/efetividade?*", async (route) => {
      pedidos.push(route.request().url());
      await new Promise((r) => setTimeout(r, 1500));
      await route.continue();
    });
    const aplicar = e.getByRole("button", { name: "Aplicar filtros" });
    await aplicar.click();
    await expect(aplicar).toBeDisabled();
    await aplicar.click({ force: true });
    await aplicar.click({ force: true });
    await expect(e.locator("table")).toBeVisible({ timeout: 30_000 });
    await expect(aplicar).toBeEnabled();
    expect(pedidos).toHaveLength(1);
  });

  test("trocar o período no meio da consulta do SETA cancela a anterior e o card mostra a nova", { tag: ["@efetividade","@resiliencia"] }, async ({ page }) => {
    const pedidos: string[] = [];
    let primeira = true;
    await page.route("**/dashboard/janela-pagamento?*", async (route) => {
      pedidos.push(route.request().url());
      if (primeira) {
        primeira = false;
        await new Promise((r) => setTimeout(r, 3000));
      }
      await route.continue().catch(() => undefined);
    });
    await page.locator(".periodo-card", { hasText: "Últimos 7 dias" }).first().click();
    await expect.poll(() => pedidos.length).toBeGreaterThanOrEqual(1); // a consulta está no ar (segurada)
    await page.locator(".periodo-card", { hasText: "Hoje" }).first().click();
    await expect(stat(page, "Pagaram em até 7 dias")).not.toHaveText("…", { timeout: 30_000 });
    await expect(page.locator(".stat .texto-erro")).toHaveCount(0);
  });

  test("efetividade: exportar Excel e exportar por cliente", { tag: ["@efetividade"] }, async ({ page }) => {
    const e = card(page, "Efetividade da cobrança");
    const a = await baixar(page, () => e.getByRole("button", { name: "Exportar Excel" }).click());
    expect(a.nome).toMatch(/\.xlsx$/);
    expect(a.linhas.length).toBeGreaterThan(1);
    const b = await baixar(page, () => e.getByRole("button", { name: "Exportar por cliente" }).click());
    expect(b.nome).toMatch(/\.xlsx$/);
  });

  test("efetividade: filtro que não pega ninguém mostra estado vazio", { tag: ["@efetividade"] }, async ({ page }) => {
    const e = card(page, "Efetividade da cobrança");
    await e.getByLabel("Enviado de").fill("2020-01-01");
    await e.getByLabel("Enviado até").fill("2020-01-02");
    await e.getByRole("button", { name: "Aplicar filtros" }).click();
    await expect(e.getByText("Nenhum lead enviado no período e filtros escolhidos.")).toBeVisible({ timeout: 30_000 });
  });

  test("leads: contadores, filtro Hoje (liga/desliga) e exportação dos enviados", { tag: ["@leads"] }, async ({ page }) => {
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

  test("orçamento: gasto por número, linha de total, ordenação e personalizado", { tag: ["@orcamento"] }, async ({ page }) => {
    const o = card(page, "Orçamento");
    await expect(o.locator("table")).toBeVisible({ timeout: 30_000 });
    await expect(o).toContainText("Realizado (gasto acumulado)");
    await expect(o.locator("svg[role=img]")).toBeVisible();
    const linhas = o.locator("tbody tr:not(.linha-total)");
    await expect(linhas).toHaveCount(2);
    const brl = (t: string) => Number(t.replace(/[^\d,]/g, "").replace(",", "."));
    const qtd = (t: string) => Number(t.replace(/\D/g, ""));
    // Número | Qtd e R$ de Utilitário, Marketing e Serviço | Total gasto | Total enviado
    const titulos = o.locator("thead th");
    await expect(titulos).toHaveText([
      /^Número/, /^Utilitário \(qtd\)/, /^Utilitário \(R\$\)/, /^Marketing \(qtd\)/, /^Marketing \(R\$\)/,
      /^Serviço \(qtd\)/, /^Serviço \(R\$\)/, /^Total gasto/, /^Total enviado/,
    ]);
    const C = { utilQtd: 2, utilRs: 3, mktQtd: 4, mktRs: 5, servQtd: 6, servRs: 7, gasto: 8, enviado: 9 };
    const ehRs = (n: number) => [C.utilRs, C.mktRs, C.servRs, C.gasto].includes(n);
    const coluna = async (n: number) => (await linhas.locator(`td:nth-child(${n})`).allInnerTexts()).map(ehRs(n) ? brl : qtd);
    const totalDa = async (n: number) => (ehRs(n) ? brl : qtd)(await o.locator(`tr.linha-total td:nth-child(${n})`).innerText());
    for (let n = 2; n <= 9; n++) {
      expect(await totalDa(n)).toBeCloseTo((await coluna(n)).reduce((a, b) => a + b, 0), 2);
    }
    // Serviço só conta mensagem cobrada (a Meta não cobra serviço)
    expect(await totalDa(C.servQtd)).toBe(0);
    expect(await totalDa(C.utilQtd)).toBeGreaterThan(0);
    expect(await totalDa(C.mktQtd)).toBeGreaterThan(0);
    // Totais são da Meta inteira: incluem autenticação, que fica fora das categorias
    expect(await totalDa(C.gasto)).toBeGreaterThan((await totalDa(C.utilRs)) + (await totalDa(C.mktRs)) + (await totalDa(C.servRs)));
    expect(await totalDa(C.enviado)).toBeGreaterThan((await totalDa(C.utilQtd)) + (await totalDa(C.mktQtd)) + (await totalDa(C.servQtd)));
    await o.getByRole("columnheader", { name: /Total gasto/ }).click();
    const ord = await coluna(C.gasto);
    expect(ord).toEqual([...ord].sort((a, b) => a - b));
    await o.getByRole("columnheader", { name: /Marketing \(qtd\)/ }).click();
    const ordQtd = await coluna(C.mktQtd);
    expect(ordQtd).toEqual([...ordQtd].sort((a, b) => a - b));
    // Filtro de categorias: Realizado e linha do gráfico passam a somar só Marketing
    const realizado = async () => brl(await o.locator(".stat", { hasText: "Realizado" }).locator(".value").innerText());
    const pontosAntes = await o.locator("svg[role=img] polyline").getAttribute("points");
    // 1 casa: o Realizado soma por dia e a tabela por número, cada um arredondado em centavos
    expect(await realizado()).toBeCloseTo(await totalDa(C.gasto), 1);
    await escolherMulti(o, "Categorias no gráfico", ["Marketing"]);
    await expect.poll(realizado).toBeCloseTo(await totalDa(C.mktRs), 1);
    expect(await o.locator("svg[role=img] polyline").getAttribute("points")).not.toBe(pontosAntes);
    await escolherMulti(o, "Categorias no gráfico", ["Utilitário"]);
    await expect.poll(realizado).toBeCloseTo((await totalDa(C.utilRs)) + (await totalDa(C.mktRs)), 1);
    // hover no gráfico mostra o tooltip do dia
    const box = await o.locator("svg[role=img] rect").last().boundingBox();
    await page.mouse.move(box!.x + box!.width - 5, box!.y + box!.height / 2);
    await expect(o.locator("svg[role=img]")).toContainText("Acumulado:");
    await expect(o.locator("svg[role=img]")).toContainText("Qtd mensagens:");
    await expect(o.locator("svg[role=img]")).toContainText("Envios acumulados:");
    // mês corrente: a linha vai só até hoje (GMT-3) e termina numa bolinha
    const diaHoje = Number(new Intl.DateTimeFormat("en-CA", { timeZone: "America/Sao_Paulo", day: "2-digit" }).format(new Date()));
    const pontos = await o.locator("svg[role=img] polyline").getAttribute("points");
    expect(pontos!.trim().split(" ")).toHaveLength(diaHoje);
    await expect(o.locator("circle.fim-realizado")).toHaveCount(1);
    // mês que já acabou: sem bolinha
    const mesPassado = (await o.locator("select option").nth(1).getAttribute("value"))!;
    await Promise.all([
      page.waitForResponse((r) => r.url().includes("/dashboard/orcamento-progressao?") && r.ok()),
      o.locator("select").selectOption(mesPassado),
    ]);
    await expect(o.locator("svg[role=img]")).toBeVisible({ timeout: 30_000 });
    await expect(o.locator("circle.fim-realizado")).toHaveCount(0);
    // o SVG é desenhado na largura real (1 unidade = 1 px), então a letra não cresce com o card
    const svg = o.locator("svg[role=img]");
    for (const largura of [1600, 390]) {
      await page.setViewportSize({ width: largura, height: 900 });
      await expect(async () => {
        const vb = Number((await svg.getAttribute("viewBox"))!.split(" ")[2]);
        expect(Math.abs((await svg.boundingBox())!.width - vb)).toBeLessThan(1);
      }).toPass();
    }
  });

  test("orçamento: exportar por dia traz data, WABA, telefone e valor, somando o realizado", { tag: ["@orcamento"] }, async ({ page }) => {
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

  test("orçamento: escolher 'Personalizado' sem datas não deixa os números do mês anterior na tela", { tag: ["@orcamento"] }, async ({ page }) => {
    const o = card(page, "Orçamento");
    await expect(o.locator("table")).toBeVisible({ timeout: 30_000 });
    await o.locator("select").selectOption("personalizado");
    await expect(o.getByText("Escolha a data mínima e a máxima.")).toBeVisible({ timeout: 3_000 });
  });

  test("orçamento: Meta fora do ar mostra o motivo", { tag: ["@orcamento","@resiliencia"] }, async ({ page }) => {
    permitirErrosConsole(page, "502");
    await page.route("**/dashboard/orcamento-progressao*", (r) =>
      r.fulfill({ status: 502, contentType: "application/json", body: JSON.stringify({ detail: "Falha ao consultar a Meta" }) })
    );
    await page.reload();
    await expect(card(page, "Orçamento").locator(".error-box")).toContainText("Falha ao consultar a Meta");
  });
  test("resumo e leads se atualizam sozinhos, sem F5, e param com a aba oculta", { tag: ["@resiliencia"] }, async ({ page }) => {
    await semTempoReal(page); // aqui se confere o polling, que é a reserva
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

  test("'Atualizar agora' recarrega tudo, inclusive o card do SETA, sem apagar os números", { tag: ["@resiliencia"] }, async ({ page }) => {
    await expect(stat(page, "Pagaram em até 7 dias")).not.toHaveText("…", { timeout: 30_000 });
    const pedidos: URL[] = [];
    page.on("request", (r) => pedidos.push(new URL(r.url())));
    await page.getByRole("button", { name: "Atualizar agora" }).click();
    await expect.poll(() => pedidos.some((u) => u.pathname.endsWith("/dashboard/janela-pagamento"))).toBe(true);
    const resumo = pedidos.find((u) => u.pathname.endsWith("/dashboard/summary"));
    expect(resumo?.searchParams.get("auto")).toBeNull();
    await expect(page.locator(".loading-state")).toHaveCount(0);
    await expect(stat(page, "Pagaram em até 7 dias")).not.toHaveText("…");
  });
});
