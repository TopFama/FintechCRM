import { API_URL } from "./ambiente";
import { test, expect, allowConsoleErrors } from "./fixtures";
import fs from "node:fs";
import { STORAGE_STATE } from "../playwright.config";

function getStoredToken(): string {
  try {
    const raw = fs.readFileSync(STORAGE_STATE, "utf-8");
    const json = JSON.parse(raw);
    const tokenObj = json.origins?.[0]?.localStorage?.find((item: any) => item.name === "token");
    return tokenObj ? tokenObj.value : "";
  } catch {
    return "";
  }
}

test.describe("03. Gerar leads", () => {
  test.setTimeout(240_000);

  test("narrow to one matrix cell, generate leads, assert success box, verify idempotency", async ({ page, request }) => {
    allowConsoleErrors(page, /503/, /status of 503/);

    // Query existing leads to avoid picking an already-generated cluster/faixa combination
    const token = getStoredToken();
    const existingCombos = new Set<string>();
    const leadsRes = await request.get(`${API_URL}/leads`, {
      headers: { Authorization: `Bearer ${token}` },
    });
    if (leadsRes.ok()) {
      const data = await leadsRes.json();
      data.itens.forEach((it: any) => existingCombos.add(`${it.cluster}|${it.faixa}`));
    }

    // The cluster × faixa matrix lives on the Dashboard; a cell opens Cobrança pre-filtered
    await page.goto("/");
    const card = page.locator(".card").filter({ has: page.getByRole("heading", { name: /cluster × faixa/ }) });
    await card.getByRole("button", { name: "Aplicar filtros" }).click();
    await expect(card.locator(".loading-state")).toHaveCount(0, { timeout: 120_000 });

    const matrix = card.locator(".matriz-table");
    await expect(matrix).toBeVisible({ timeout: 60_000 });

    // Header faixas
    const headers = matrix.locator("thead tr th");
    const headerCount = await headers.count();
    const faixas: string[] = [];
    for (let c = 1; c < headerCount - 1; c++) {
      faixas.push((await headers.nth(c).innerText()).trim());
    }

    // Find an ungenerated matrix cell with a count between 3 and 15
    const bodyRows = matrix.locator("tbody tr");
    const bodyRowCount = await bodyRows.count();
    let targetCell: any = null;

    for (let r = 0; r < bodyRowCount - 1; r++) { // exclude Total row
      const row = bodyRows.nth(r);
      const cluster = (await row.locator("td").first().innerText()).trim();
      const cells = row.locator("td");
      for (let c = 1; c < headerCount - 1; c++) {
        const faixa = faixas[c - 1];
        const cell = cells.nth(c);
        const text = (await cell.innerText()).trim();
        const num = parseInt(text, 10);
        if (!isNaN(num) && num >= 3 && num <= 15 && !existingCombos.has(`${cluster}|${faixa}`)) {
          targetCell = cell;
          break;
        }
      }
      if (targetCell) break;
    }

    // Fallback to any positive count cell not in existingCombos
    if (!targetCell) {
      for (let r = 0; r < bodyRowCount - 1; r++) {
        const row = bodyRows.nth(r);
        const cluster = (await row.locator("td").first().innerText()).trim();
        const cells = row.locator("td");
        for (let c = 1; c < headerCount - 1; c++) {
          const faixa = faixas[c - 1];
          const cell = cells.nth(c);
          const text = (await cell.innerText()).trim();
          const num = parseInt(text, 10);
          if (!isNaN(num) && num > 0 && !existingCombos.has(`${cluster}|${faixa}`)) {
            targetCell = cell;
            break;
          }
        }
        if (targetCell) break;
      }
    }

    expect(targetCell).not.toBeNull();
    await targetCell.click();
    await expect(page).toHaveURL(/\/cobranca\?/);
    await expect(page.locator(".loading-state")).toHaveCount(0, { timeout: 120_000 });

    // Click "Gerar leads com estes filtros" and accept confirm dialog
    const gerarBtn = page.getByRole("button", { name: "Gerar leads com estes filtros" });
    await expect(gerarBtn).toBeVisible();

    page.once("dialog", (dialog) => dialog.accept());
    await gerarBtn.click();

    // Expect success box with "leads criados"
    const successBox = page.locator(".success-box");
    await expect(successBox).toBeVisible({ timeout: 60_000 });
    await expect(successBox).toContainText(/leads? criados?/i);
    const initialText = await successBox.innerText();
    expect(initialText).not.toContain("0 leads criados");

    // Run it again: must be idempotent and create 0 leads
    page.once("dialog", (dialog) => dialog.accept());
    await gerarBtn.click();

    await expect(successBox).toBeVisible({ timeout: 60_000 });
    await expect(successBox).toContainText(/0 leads criados/i);
  });
});
