import { test, expect, allowConsoleErrors } from "./fixtures";

function numero(texto: string): number {
  return parseInt(texto.replace(/\D/g, ""), 10);
}

test.describe("07. Dashboard", () => {
  test.setTimeout(300_000);

  test("matrix tabs, cell opens Cobrança filtered", async ({ page }) => {
    allowConsoleErrors(page, /503/, /status of 503/);
    await page.goto("/");

    const card = page.locator(".card").filter({ has: page.getByRole("heading", { name: /cluster × faixa/ }) });
    await card.getByRole("button", { name: "Aplicar filtros" }).click();
    await expect(card.locator(".loading-state")).toHaveCount(0, { timeout: 120_000 });

    const matriz = card.locator(".matriz-table");
    await expect(matriz).toBeVisible();
    const linhaTotal = matriz.locator("tbody tr").filter({ hasText: "Total" });
    const total = numero(await linhaTotal.locator("td").last().innerText());
    expect(total).toBeGreaterThan(0);

    await card.getByRole("tab", { name: "Clientes com restrição no SPC" }).click();
    expect(numero(await linhaTotal.locator("td").last().innerText())).toBeLessThanOrEqual(total);

    await card.getByRole("tab", { name: "Valor em aberto" }).click();
    await expect(linhaTotal.locator("td").last()).toContainText("R$");

    await card.getByRole("tab", { name: "Clientes", exact: true }).click();
    // first data row, first faixa column with a non-zero count
    const primeiraLinha = matriz.locator("tbody tr").first();
    const cluster = (await primeiraLinha.locator("td").first().innerText()).trim();
    const celulas = primeiraLinha.locator("td");
    const faixas = (await matriz.locator("thead th").allInnerTexts()).map((t) => t.trim());
    let coluna = -1;
    for (let c = 1; c < (await celulas.count()) - 1; c++) {
      if (numero(await celulas.nth(c).innerText()) > 0) {
        coluna = c;
        break;
      }
    }
    expect(coluna).toBeGreaterThan(0);
    const faixa = faixas[coluna];
    await celulas.nth(coluna).click();

    await expect(page).toHaveURL(/\/cobranca\?/);
    await expect(page.locator(".loading-state")).toHaveCount(0, { timeout: 120_000 });
    const rows = page.locator("table").filter({ hasText: "Código" }).locator("tbody tr");
    expect(await rows.count()).toBeGreaterThan(0);
    expect((await rows.first().locator("td").nth(7).innerText()).trim()).toBe(faixa);
    expect((await rows.first().locator("td").nth(8).innerText()).trim()).toBe(cluster);
  });

  test("effectiveness report and leads panel", async ({ page }) => {
    allowConsoleErrors(page, /503/, /status of 503/);
    await page.goto("/");

    const efet = page.locator(".card").filter({ has: page.getByRole("heading", { name: "Efetividade da cobrança" }) });
    await expect(efet.getByLabel("Janela de pagamento")).toHaveValue("7");
    await efet.getByRole("button", { name: "Aplicar filtros" }).click();
    await expect(efet.locator(".loading-state")).toHaveCount(0, { timeout: 120_000 });
    // either a table with a Total row or the empty state (no sent leads in the period)
    const temTabela = (await efet.locator("table").count()) > 0;
    if (temTabela) {
      const cab = (await efet.locator("thead th").allInnerTexts()).map((t) => t.trim().toLowerCase());
      expect(cab[0]).toBe("faixa");
      expect(cab).toContain("clientes que pagaram");
      await expect(efet.locator("tr.linha-total")).toContainText("Total");
      await efet.getByRole("tab", { name: "Por loja" }).click();
      const cabLoja = (await efet.locator("thead th").allInnerTexts()).map((t) => t.trim().toLowerCase());
      expect(cabLoja.slice(0, 3)).toEqual(["loja", "regional", "cluster inad"]);
    } else {
      await expect(efet.getByText(/Nenhum lead enviado/)).toBeVisible();
    }
    const downloadEfet = page.waitForEvent("download");
    await efet.getByRole("button", { name: "Exportar Excel" }).click();
    expect((await downloadEfet).suggestedFilename()).toMatch(/\.xlsx$/);

    const leads = page.locator(".card").filter({ has: page.getByRole("heading", { name: "Leads", exact: true }) });
    await expect(leads.getByText("Leads novos", { exact: true })).toBeVisible();
    await expect(leads.getByText("Leads enviados", { exact: true })).toBeVisible();
    const downloadLeads = page.waitForEvent("download");
    await leads.getByRole("button", { name: /Exportar leads enviados/ }).click();
    expect((await downloadLeads).suggestedFilename()).toMatch(/^leads_.*\.xlsx$/);
  });
});
