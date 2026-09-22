import { test, expect, allowConsoleErrors } from "./fixtures";

test.describe("02. Cobrança", () => {
  test.setTimeout(240_000);

  test("filters, table, formatting, pagination and reset (no matrix on this page)", async ({ page }) => {
    // Loja filter triggers 503 from backend when Google is not configured (as expected in this env)
    allowConsoleErrors(page, /503/, /status of 503/);

    await page.goto("/cobranca");

    // 1. Default filters
    const primeiroDiaCheckbox = page.getByLabel("Somente o primeiro dia da faixa");
    const regraWhatsappCheckbox = page.getByLabel("Somente clientes da regra WhatsApp");
    await expect(primeiroDiaCheckbox).toBeChecked();
    await expect(regraWhatsappCheckbox).toBeChecked();

    // 2. Loja filter degrades to text input with Google hint
    await expect(page.getByText(/Conecte o Google em/i).filter({ hasText: /Configurações/i })).toBeVisible();
    await expect(page.getByLabel(/Loja \(códigos/)).toBeVisible();

    // 3. Reports moved to the Dashboard: no matrix here
    await expect(page.locator(".matriz-table")).toHaveCount(0);

    // 4. Apply and wait for the ERP query
    await page.getByRole("button", { name: "Aplicar filtros" }).click();
    await expect(page.locator(".loading-state")).toHaveCount(0, { timeout: 120_000 });

    // 5. Client table header is exactly the agreed columns
    const clientTable = page.locator("table").filter({ hasText: "Código" });
    await expect(clientTable).toBeVisible();
    const actualHeaders = (await clientTable.locator("thead th").allInnerTexts()).map((t) => t.trim());
    expect(actualHeaders.map((h) => h.toLowerCase())).toEqual(
      ["Código", "CPF", "Nome", "Vencimento", "Valor", "Parcelas", "Atraso", "Faixa", "Cluster"].map((h) =>
        h.toLowerCase(),
      ),
    );

    // 6. Row formatting
    const rows = clientTable.locator("tbody tr");
    expect(await rows.count()).toBeGreaterThan(0);
    const cells = rows.first().locator("td");
    const firstRowCodigo = (await cells.nth(0).innerText()).trim();
    const firstRowCpf = (await cells.nth(1).innerText()).trim();
    expect((await cells.nth(3).innerText()).trim()).toMatch(/^\d{2}\/\d{2}\/\d{4}$/);
    expect((await cells.nth(4).innerText()).trim()).toMatch(/^R\$\s?[\d.,]+/);
    if (firstRowCpf && firstRowCpf !== "—") {
      expect(firstRowCpf).toMatch(/^(\d{3}\.\d{3}\.\d{3}-\d{2}|\d{2}\.\d{3}\.\d{3}\/\d{4}-\d{2})$/);
    }

    // 7. Pagination changes the first row
    const proximaBtn = page.getByRole("button", { name: /Próxima/i });
    if ((await proximaBtn.isVisible()) && (await proximaBtn.isEnabled())) {
      await proximaBtn.click();
      await expect(page.locator(".loading-state")).toHaveCount(0, { timeout: 60_000 });
      const novoPrimeiro = (await clientTable.locator("tbody tr").first().locator("td").nth(0).innerText()).trim();
      expect(novoPrimeiro).not.toBe(firstRowCodigo);
    }

    // 8. "Limpar" resets the filters being edited
    await primeiroDiaCheckbox.uncheck();
    await page.getByRole("button", { name: "Limpar" }).click();
    await expect(primeiroDiaCheckbox).toBeChecked();
  });

  test("opens pre-filtered from the Dashboard query string", async ({ page }) => {
    allowConsoleErrors(page, /503/, /status of 503/);

    await page.goto("/cobranca?cluster=ESPECIAL&faixa=-1");
    await expect(page.locator(".loading-state")).toHaveCount(0, { timeout: 120_000 });

    const rows = page.locator("table").filter({ hasText: "Código" }).locator("tbody tr");
    const count = await rows.count();
    expect(count).toBeGreaterThan(0);
    for (let i = 0; i < Math.min(count, 10); i++) {
      expect((await rows.nth(i).locator("td").nth(7).innerText()).trim()).toBe("-1");
      expect((await rows.nth(i).locator("td").nth(8).innerText()).trim()).toBe("ESPECIAL");
    }
  });
});
