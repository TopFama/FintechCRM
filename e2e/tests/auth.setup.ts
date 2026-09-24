import { test as setup, expect } from "@playwright/test";
import fs from "node:fs";
import path from "node:path";
import { STORAGE_STATE } from "../playwright.config";
import { EMAIL, SENHA } from "./ambiente";

setup("entrar como admin", async ({ page }) => {
  fs.mkdirSync(path.dirname(STORAGE_STATE), { recursive: true });
  await page.goto("/login");
  await page.getByPlaceholder("voce@empresa.com").fill(EMAIL);
  await page.getByPlaceholder("••••••••").fill(SENHA);
  await page.getByRole("button", { name: "Entrar" }).click();
  await expect(page).toHaveURL("/");
  await expect(page.getByRole("heading", { name: "Dashboard" })).toBeVisible();
  await page.context().storageState({ path: STORAGE_STATE });
});
