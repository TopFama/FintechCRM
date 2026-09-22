import { test, expect, allowConsoleErrors } from "./fixtures";

test.describe("04. Leads", () => {
  test.setTimeout(240_000);

  test("table headers, novo status, mark as sent, status filter, and code search", async ({ page }) => {
    allowConsoleErrors(page, /503/, /status of 503/);

    await page.goto("/leads");
    await expect(page.getByText(/Carregando/i)).not.toBeVisible({ timeout: 120_000 });

    const leadsTable = page.locator("table").filter({ hasText: "Código" });
    await expect(leadsTable).toBeVisible({ timeout: 60_000 });

    // 1. Verify table header is exactly:
    // Código, CPF, Nome, Vencimento, Valor, Parcelas, Atraso, Faixa, Cluster, Status, Enviado em
    // (plus the leading checkbox column)
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
      "Status",
      "Enviado em",
    ];

    const headerCells = leadsTable.locator("thead tr th");
    const headerCount = await headerCells.count();
    const actualHeaders: string[] = [];
    for (let i = 0; i < headerCount; i++) {
      const text = (await headerCells.nth(i).textContent())?.trim();
      if (text) actualHeaders.push(text);
    }
    expect(actualHeaders).toEqual(expectedHeaders);

    // 2. Verify rows from scenario 3 appear with status "Novo"
    const novoRows = leadsTable.locator("tbody tr").filter({ hasText: "Novo" });
    await expect(novoRows.first()).toBeVisible({ timeout: 30_000 });
    const novoCount = await novoRows.count();
    expect(novoCount).toBeGreaterThanOrEqual(2);

    const targetRow1 = novoRows.nth(0);
    const targetRow2 = novoRows.nth(1);
    const targetCode1 = (await targetRow1.locator("td").nth(1).innerText()).trim();
    const targetCode2 = (await targetRow2.locator("td").nth(1).innerText()).trim();

    // 3. Select two rows: check their checkboxes
    const checkbox1 = targetRow1.locator('input[type="checkbox"]');
    const checkbox2 = targetRow2.locator('input[type="checkbox"]');
    await checkbox1.check();
    await checkbox2.check();

    // 4. Click "Marcar como enviados (2)"
    const marcarBtn = page.getByRole("button", { name: /Marcar como enviados \(2\)/i });
    await expect(marcarBtn).toBeVisible();

    page.once("dialog", (dialog) => dialog.accept());
    await marcarBtn.click();

    // Expect success box
    const successBox = page.locator(".success-box");
    await expect(successBox).toBeVisible({ timeout: 60_000 });

    // Wait for table update / loading
    await expect(page.getByText(/Carregando/i)).not.toBeVisible({ timeout: 60_000 });

    // 5. Verify those rows now show "Enviado" and a date in "Enviado em"
    const updatedRow1 = leadsTable.locator("tbody tr").filter({ hasText: targetCode1 });
    await expect(updatedRow1).toBeVisible();
    const updatedStatus1 = (await updatedRow1.locator("td").nth(10).innerText()).trim();
    const updatedEnviadoEm1 = (await updatedRow1.locator("td").nth(11).innerText()).trim();
    expect(updatedStatus1).toMatch(/Enviado|Cobrado/i);
    expect(updatedEnviadoEm1).toMatch(/\d{2}\/\d{2}\/\d{4}/);

    const updatedRow2 = leadsTable.locator("tbody tr").filter({ hasText: targetCode2 });
    await expect(updatedRow2).toBeVisible();
    const updatedStatus2 = (await updatedRow2.locator("td").nth(10).innerText()).trim();
    const updatedEnviadoEm2 = (await updatedRow2.locator("td").nth(11).innerText()).trim();
    expect(updatedStatus2).toMatch(/Enviado|Cobrado/i);
    expect(updatedEnviadoEm2).toMatch(/\d{2}\/\d{2}\/\d{4}/);

    // 6. The Status filter "Enviado" lists them
    const statusSelect = page.locator("select").filter({ has: page.locator('option[value="cobrado"]') })
      .or(page.getByLabel(/Status/i))
      .or(page.getByRole("combobox", { name: /Status/i }));

    if (await statusSelect.isVisible()) {
      await statusSelect.selectOption({ label: "Enviado" }).catch(() => statusSelect.selectOption("cobrado"));
    } else {
      const statusBtn = page.getByRole("button", { name: /Status/i });
      if (await statusBtn.isVisible()) {
        await statusBtn.click();
        const enviadoOption = page.getByText("Enviado", { exact: true }).or(page.getByText("Cobrado", { exact: true }));
        await enviadoOption.first().click();
      }
    }

    const aplicarFiltrosBtn = page.getByRole("button", { name: /Aplicar/i });
    if (await aplicarFiltrosBtn.isVisible()) {
      await aplicarFiltrosBtn.click();
    }
    await expect(page.getByText(/Carregando/i)).not.toBeVisible({ timeout: 60_000 });

    // Verify targetCode1 is listed
    await expect(leadsTable.locator("tbody tr").filter({ hasText: targetCode1 })).toBeVisible();

    // 7. Search by one row's Código finds it
    const searchInput = page.getByPlaceholder(/Buscar|Nome, código ou CPF|Pesquisar/i)
      .or(page.locator('input[type="search"]'))
      .or(page.locator('input[placeholder*="código" i]'));
    await expect(searchInput).toBeVisible();
    await searchInput.fill(targetCode1);

    await searchInput.press("Enter");
    const buscarBtn = page.getByRole("button", { name: /Buscar/i });
    if (await buscarBtn.isVisible()) {
      await buscarBtn.click();
    }
    await expect(page.getByText(/Carregando/i)).not.toBeVisible({ timeout: 60_000 });

    const searchResults = leadsTable.locator("tbody tr");
    await expect(searchResults.first()).toBeVisible();
    const searchCode = (await searchResults.first().locator("td").nth(1).innerText()).trim();
    expect(searchCode).toBe(targetCode1);
  });
});
