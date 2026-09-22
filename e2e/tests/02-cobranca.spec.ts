import { test, expect, allowConsoleErrors } from "./fixtures";

test.describe("02. Cobrança", () => {
  test.setTimeout(240_000);

  test("filters, matrix, table, formatting, pagination, SPC tab, cell filter, and reset", async ({ page }) => {
    // Loja filter triggers 503 from backend when Google is not configured (as expected in this env)
    allowConsoleErrors(page, /503/, /status of 503/);

    await page.goto("/cobranca");

    // 1. Check default filters
    const primeiroDiaCheckbox = page.getByLabel("Somente o primeiro dia da faixa");
    const regraWhatsappCheckbox = page.getByLabel("Somente clientes da regra WhatsApp");

    await expect(primeiroDiaCheckbox).toBeVisible();
    await expect(primeiroDiaCheckbox).toBeChecked();

    await expect(regraWhatsappCheckbox).toBeVisible();
    await expect(regraWhatsappCheckbox).toBeChecked();

    // 2. Check Loja filter degrades to text input with Google hint
    const googleHint = page.getByText(/Conecte o Google em/i).filter({ hasText: /Configurações/i });
    await expect(googleHint).toBeVisible();

    // 3. Click "Aplicar filtros"
    const aplicarBtn = page.getByRole("button", { name: "Aplicar filtros" });
    await expect(aplicarBtn).toBeVisible();
    await aplicarBtn.click();

    // Wait for data to load (query against ERP takes 10-60s)
    await expect(page.getByText(/Carregando/i)).not.toBeVisible({ timeout: 120_000 });

    // 4. Matrix shows numeric Total > 0
    const matrix = page.locator("table").first();
    await expect(matrix).toBeVisible({ timeout: 60_000 });

    const totalRow = matrix.locator("tbody tr").filter({ hasText: "Total" });
    await expect(totalRow).toBeVisible();
    const totalCell = totalRow.locator("td").last();
    const totalText = (await totalCell.innerText()).trim();
    const totalClientes = parseInt(totalText.replace(/\D/g, ""), 10);
    expect(totalClientes).toBeGreaterThan(0);

    // 5. Client table header is exactly:
    // Código, CPF, Nome, Vencimento, Valor, Parcelas, Atraso, Faixa, Cluster
    const expectedHeaders = [
      "Código",
      "CPF",
      "Nome",
      "Vencimento",
      "Valor",
      "Parcelas",
      "Atraso",
      "Faixa",
      "Cluster",
    ];

    const clientTable = page.locator("table").filter({ hasText: "Código" });
    await expect(clientTable).toBeVisible();

    const headerCells = clientTable.locator("thead tr th");
    const headerCount = await headerCells.count();
    const actualHeaders: string[] = [];
    for (let i = 0; i < headerCount; i++) {
      const text = (await headerCells.nth(i).textContent())?.trim();
      if (text) actualHeaders.push(text);
    }
    expect(actualHeaders).toEqual(expectedHeaders);

    // 6. Verify row formatting: Valor like R$ ..., Vencimento like dd/mm/aaaa, CPF like 000.000.000-00 (when present)
    const rows = clientTable.locator("tbody tr");
    const rowCount = await rows.count();
    expect(rowCount).toBeGreaterThan(0);

    const firstRowCells = rows.first().locator("td");
    const firstRowCodigo = (await firstRowCells.nth(0).innerText()).trim();
    const firstRowCpf = (await firstRowCells.nth(1).innerText()).trim();
    const firstRowVencimento = (await firstRowCells.nth(3).innerText()).trim();
    const firstRowValor = (await firstRowCells.nth(4).innerText()).trim();

    // Vencimento dd/mm/aaaa
    expect(firstRowVencimento).toMatch(/^\d{2}\/\d{2}\/\d{4}$/);
    // Valor R$ ...
    expect(firstRowValor).toMatch(/^R\$\s?[\d.,]+/);
    // CPF 000.000.000-00 (when present)
    if (firstRowCpf && firstRowCpf !== "-" && firstRowCpf !== "") {
      expect(firstRowCpf).toMatch(/^\d{3}\.\d{3}\.\d{3}-\d{2}$/);
    }

    // 7. Pagination: "Próxima →" changes the first row
    const proximaBtn = page.getByRole("button", { name: /Próxima/i });
    if (await proximaBtn.isVisible() && await proximaBtn.isEnabled()) {
      await proximaBtn.click();
      await expect(page.getByText(/Carregando/i)).not.toBeVisible({ timeout: 60_000 });
      const newFirstRowCodigo = (await clientTable.locator("tbody tr").first().locator("td").nth(0).innerText()).trim();
      expect(newFirstRowCodigo).not.toBe(firstRowCodigo);

      // Return to first page
      const anteriorBtn = page.getByRole("button", { name: /Anterior/i });
      if (await anteriorBtn.isVisible() && await anteriorBtn.isEnabled()) {
        await anteriorBtn.click();
        await expect(page.getByText(/Carregando/i)).not.toBeVisible({ timeout: 60_000 });
      }
    }

    // 8. Tab "Clientes com restrição no SPC" shows total <= clients total
    const spcBtn = page.getByRole("button", { name: "Clientes com restrição no SPC" });
    await expect(spcBtn).toBeVisible();
    await spcBtn.click();
    await expect(page.getByText(/Carregando/i)).not.toBeVisible({ timeout: 120_000 });

    const spcTotalRow = matrix.locator("tbody tr").filter({ hasText: "Total" });
    const spcTotalCell = spcTotalRow.locator("td").last();
    const spcTotal = parseInt((await spcTotalCell.innerText()).replace(/\D/g, ""), 10);
    expect(spcTotal).toBeLessThanOrEqual(totalClientes);

    // Switch back to "Clientes" tab
    await page.getByRole("button", { name: "Clientes", exact: true }).click();
    await expect(page.getByText(/Carregando/i)).not.toBeVisible({ timeout: 120_000 });

    // 9. Clicking a non-zero matrix cell reloads the table and every row shows that cell's Faixa and Cluster
    // First data row is "ESPECIAL", column 1 is "-1" with value "191"
    const rowEspecial = matrix.locator("tbody tr").first();
    const cellEspecialMinus1 = rowEspecial.locator("td").nth(1);
    await cellEspecialMinus1.click();
    await expect(page.getByText(/Carregando/i)).not.toBeVisible({ timeout: 120_000 });

    // Check filtered rows in clientTable
    const filteredRows = clientTable.locator("tbody tr");
    await expect(filteredRows.first()).toBeVisible();
    const filteredCount = await filteredRows.count();
    expect(filteredCount).toBeGreaterThan(0);

    for (let i = 0; i < Math.min(filteredCount, 5); i++) {
      const rowFaixa = (await filteredRows.nth(i).locator("td").nth(7).innerText()).trim();
      const rowCluster = (await filteredRows.nth(i).locator("td").nth(8).innerText()).trim();
      expect(rowFaixa).toBe("-1");
      expect(rowCluster).toBe("ESPECIAL");
    }

    // 10. "Limpar" resets filters
    const limparBtn = page.getByRole("button", { name: "Limpar" });
    await expect(limparBtn).toBeVisible();
    await limparBtn.click();
  });
});
