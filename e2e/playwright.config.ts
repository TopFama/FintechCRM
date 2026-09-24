import { defineConfig, devices } from "@playwright/test";
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

const __dirname = path.dirname(fileURLToPath(import.meta.url));

// Usa o Chromium já instalado no ambiente quando existe (sem `playwright install`).
function chromiumLocal(): string | undefined {
  if (process.env.CHROMIUM_PATH) return process.env.CHROMIUM_PATH;
  const base = process.env.PLAYWRIGHT_BROWSERS_PATH ?? "/opt/pw-browsers";
  if (!fs.existsSync(base)) return undefined;
  const dir = fs.readdirSync(base).find((d) => /^chromium-\d+$/.test(d));
  const exe = dir && path.join(base, dir, "chrome-linux", "chrome");
  return exe && fs.existsSync(exe) ? exe : undefined;
}
const CHROMIUM = chromiumLocal();

export const STORAGE_STATE = path.join(__dirname, ".auth/user.json");

// Os cenários dependem uns dos outros (cadastram token, números, faixas e fila
// em sequência), por isso rodam em série, na ordem dos arquivos.
export default defineConfig({
  testDir: "./tests",
  workers: 1,
  fullyParallel: false,
  retries: 0,
  timeout: 90_000,
  expect: { timeout: 15_000 },
  reporter: [
    ["list"],
    ["html", { open: "never", outputFolder: "playwright-report" }],
    ["json", { outputFile: "test-results/resultado.json" }],
  ],
  use: {
    baseURL: process.env.E2E_BASE_URL ?? "http://localhost:4174",
    locale: "pt-BR",
    timezoneId: "America/Sao_Paulo",
    viewport: { width: 1440, height: 1000 },
    acceptDownloads: true,
    actionTimeout: 15_000,
    screenshot: "only-on-failure",
    trace: "retain-on-failure",
    launchOptions: CHROMIUM ? { executablePath: CHROMIUM } : {},
  },
  projects: [
    { name: "setup", testMatch: /.*\.setup\.ts/ },
    {
      name: "chromium",
      use: { ...devices["Desktop Chrome"], viewport: { width: 1440, height: 1000 }, storageState: STORAGE_STATE },
      dependencies: ["setup"],
      testIgnore: /.*\.setup\.ts/,
    },
  ],
});
