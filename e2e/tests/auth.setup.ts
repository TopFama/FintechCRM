import { EMAIL, SENHA } from "./ambiente";
import { test as setup, expect } from "@playwright/test";
import fs from "node:fs";
import path from "node:path";
import { STORAGE_STATE } from "../playwright.config";

setup("authenticate as admin", async ({ page }) => {
  fs.mkdirSync(path.dirname(STORAGE_STATE), { recursive: true });

  await page.goto("/login");
  await page.locator('input[type="email"]').fill(EMAIL);
  await page.locator('input[type="password"]').fill(SENHA);
  await page.getByRole("button", { name: "Entrar" }).click();

  // Wait until navigated to dashboard and token is present in localStorage
  await expect(page).toHaveURL("/");
  await page.waitForFunction(() => Boolean(localStorage.getItem("token")));

  await page.context().storageState({ path: STORAGE_STATE });
});
