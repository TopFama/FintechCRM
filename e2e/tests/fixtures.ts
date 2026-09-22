import { test as base, expect, type Page } from "@playwright/test";

export function allowConsoleErrors(page: Page, ...patterns: (string | RegExp)[]) {
  const current = (page as any).__allowedConsoleErrors || [];
  (page as any).__allowedConsoleErrors = [...current, ...patterns];
}

export const test = base.extend({
  page: async ({ page }, use) => {
    const consoleErrors: string[] = [];

    page.on("pageerror", (err) => {
      consoleErrors.push(`[PageError] ${err.message}\n${err.stack || ""}`);
    });

    page.on("console", (msg) => {
      if (msg.type() === "error") {
        const text = msg.text();
        const allowed: (string | RegExp)[] = (page as any).__allowedConsoleErrors || [];
        const isAllowed = allowed.some((pattern) =>
          typeof pattern === "string" ? text.includes(pattern) : pattern.test(text)
        );
        if (!isAllowed) {
          consoleErrors.push(`[ConsoleError] ${text}`);
        }
      }
    });

    await use(page);

    if (consoleErrors.length > 0) {
      throw new Error(`Unexpected browser console/page errors:\n${consoleErrors.join("\n")}`);
    }
  },
});

export { expect };
