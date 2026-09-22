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

async function cleanupBlacklist(request: any) {
  const token = getStoredToken();
  if (!token) return;

  const res = await request.get(`${API_URL}/blacklist`, {
    headers: { Authorization: `Bearer ${token}` },
  });

  if (res.ok()) {
    const items = await res.json();
    const targets = ["00000001", "00000002", "52998224725", "529.982.247-25"];
    for (const item of items) {
      if (targets.includes(item.valor)) {
        await request.delete(`${API_URL}/blacklist/${item.id}`, {
          headers: { Authorization: `Bearer ${token}` },
        });
      }
    }
  }
}

test.describe("05. Blacklist", () => {
  test.beforeEach(async ({ request }) => {
    await cleanupBlacklist(request);
  });

  test.afterAll(async ({ request }) => {
    await cleanupBlacklist(request);
  });

  test("add single, duplicate error, invalid CPF, batch add with invalid, search", async ({ page }) => {
    // 400 (invalid document) and 409 (duplicate document) are intentional network responses provoked by this scenario
    allowConsoleErrors(page, /400/, /409/, /status of 400/, /status of 409/);

    await page.goto("/blacklist");
    await expect(page.getByRole("heading", { level: 2, name: "Blacklist" })).toBeVisible();

    const singleForm = page.locator("form").filter({ has: page.locator("#bl-doc") });
    const singleDocInput = page.locator("#bl-doc");
    const singleMotivoInput = page.locator("#bl-motivo");
    const singleSubmitBtn = singleForm.getByRole("button", { name: "Adicionar" });

    // 1. Add code 00000001 with motivo "e2e"
    await singleDocInput.fill("00000001");
    await singleMotivoInput.fill("e2e");
    await singleSubmitBtn.click();

    // Verify appears in table as Código SETA
    const table = page.locator("table");
    await expect(table).toBeVisible();
    const row1 = table.locator("tbody tr").filter({ hasText: "00000001" });
    await expect(row1).toBeVisible();
    await expect(row1).toContainText("Código SETA");
    await expect(row1).toContainText("e2e");

    // 2. Adding it again shows backend duplicate error (409)
    await singleDocInput.fill("00000001");
    await singleMotivoInput.fill("e2e repetido");
    await singleSubmitBtn.click();

    const singleErrorBox = singleForm.locator("..").locator(".error-box");
    await expect(singleErrorBox).toBeVisible();
    await expect(singleErrorBox).toContainText(/já está na blacklist/i);

    // 3. Invalid CPF 111.111.111-11 shows error box (400)
    await singleDocInput.fill("111.111.111-11");
    await singleMotivoInput.fill("cpf invalido");
    await singleSubmitBtn.click();

    await expect(singleErrorBox).toBeVisible();
    await expect(singleErrorBox).toContainText(/código do cliente|CPF válido/i);

    // 4. "Colar lista" with 00000002, abc, 529.982.247-25
    const batchCard = page.locator(".card").filter({ hasText: "Colar lista" });
    const batchTextarea = batchCard.locator("#bl-lote");
    const batchMotivoInput = batchCard.locator("#bl-motivo-lote");
    const batchSubmitBtn = batchCard.getByRole("button", { name: "Adicionar lista" });

    await batchTextarea.fill("00000002\nabc\n529.982.247-25");
    await batchMotivoInput.fill("lote e2e");
    await batchSubmitBtn.click();

    // Result says 2 added and lists abc as invalid
    const batchSuccessBox = batchCard.locator(".success-box");
    await expect(batchSuccessBox).toBeVisible();
    await expect(batchSuccessBox).toContainText(/2/);
    await expect(batchSuccessBox).toContainText(/abc/);

    // Verify 00000002 and formatted CPF 529.982.247-25 appear in table
    const row2 = table.locator("tbody tr").filter({ hasText: "00000002" });
    await expect(row2).toBeVisible();

    const rowCpf = table.locator("tbody tr").filter({ hasText: "529.982.247-25" });
    await expect(rowCpf).toBeVisible();
    await expect(rowCpf).toContainText("CPF");

    // 5. Search filters the table
    const searchInput = page.locator("#bl-busca");
    await searchInput.fill("00000002");
    await expect(table.locator("tbody tr")).toHaveCount(1);
    await expect(table.locator("tbody tr")).toContainText("00000002");

    // Clear search
    await searchInput.fill("");
    await expect(table.locator("tbody tr")).toHaveCount(3);
  });

  test("remove entries (confirm dialogs) and verify they are gone", async ({ page }) => {
    // Add code 00000001 first so we can test removing it
    await page.goto("/blacklist");
    await expect(page.getByRole("heading", { level: 2, name: "Blacklist" })).toBeVisible();

    const singleForm = page.locator("form").filter({ has: page.locator("#bl-doc") });
    await page.locator("#bl-doc").fill("00000001");
    await page.locator("#bl-motivo").fill("remover e2e");
    await singleForm.getByRole("button", { name: "Adicionar" }).click();

    const table = page.locator("table");
    const targetRow = table.locator("tbody tr").filter({ hasText: "00000001" });
    await expect(targetRow).toBeVisible();

    const removeBtn = targetRow.getByRole("button", { name: "Remover" });
    await expect(removeBtn).toBeVisible();

    page.once("dialog", (dialog) => dialog.accept());
    await removeBtn.click();

    // Verify row is removed from table
    await expect(table.locator("tbody tr").filter({ hasText: "00000001" })).not.toBeVisible({ timeout: 5000 });
  });
});
