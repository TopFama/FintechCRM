import { test as base, expect, type Locator, type Page } from "@playwright/test";
import { execFileSync } from "node:child_process";
import os from "node:os";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { API_URL } from "./ambiente";

const __dirname = path.dirname(fileURLToPath(import.meta.url));

// Erros de console esperados num cenário (ex.: um 500 simulado de propósito).
export function permitirErrosConsole(page: Page, ...padroes: (string | RegExp)[]) {
  const atuais = (page as any).__permitidos || [];
  (page as any).__permitidos = [...atuais, ...padroes];
}

// Todo cenário falha se o navegador registrar erro de JS ou de console não previsto.
export const test = base.extend({
  page: async ({ page }, use) => {
    const erros: string[] = [];
    // fontes externas não são alcançáveis no ambiente de teste e não importam aqui
    await page.route(/fonts\.(googleapis|gstatic)\.com/, (r) => r.abort());
    page.on("pageerror", (err) => erros.push(`[pageerror] ${err.message}`));
    page.on("console", (msg) => {
      if (msg.type() !== "error") return;
      const texto = msg.text();
      const permitidos: (string | RegExp)[] = [
        /ERR_FAILED|ERR_CERT|net::ERR_ABORTED/,
        ...((page as any).__permitidos || []),
      ];
      if (!permitidos.some((p) => (typeof p === "string" ? texto.includes(p) : p.test(texto)))) {
        erros.push(`[console] ${texto}`);
      }
    });
    await use(page);
    expect(erros, "erros inesperados no console do navegador").toEqual([]);
  },
});

export { expect };

/** Aceita (ou recusa) o próximo window.confirm/prompt e devolve o texto dele. */
export function responderDialogo(page: Page, aceitar = true, valor?: string): Promise<string> {
  return new Promise((resolve) => {
    page.once("dialog", async (d) => {
      const msg = d.message();
      if (aceitar) await d.accept(valor);
      else await d.dismiss();
      resolve(msg);
    });
  });
}

/** Marca opções num MultiSelect (botão com o rótulo + lista de checkboxes). */
export async function escolherMulti(escopo: Page | Locator, rotulo: string, opcoes: string[]) {
  const campo = escopo.locator(".field").filter({ has: raiz(escopo).locator("label", { hasText: new RegExp(`^${rotulo}$`) }) }).first();
  const btn = campo.locator(".ms-btn");
  await btn.click();
  for (const o of opcoes) {
    await campo.getByRole("option", { name: o, exact: true }).locator("input").check();
  }
  await btn.click();
}

/** Chamada direta ao backend de teste com a sessão do navegador (para preparar/conferir dados). */
export async function apiGet(page: Page, caminho: string) {
  const r = await page.request.get(`${API_URL}${caminho}`);
  expect(r.ok(), `GET ${caminho} → ${r.status()}`).toBeTruthy();
  return r.json();
}

export async function apiSend(page: Page, metodo: "POST" | "PUT" | "PATCH" | "DELETE", caminho: string, corpo?: unknown) {
  const r = await page.request.fetch(`${API_URL}${caminho}`, { method: metodo, data: corpo });
  return { status: r.status(), corpo: await r.json().catch(() => null) };
}

// Locators passados em `has` precisam nascer da página, não de outro locator.
function raiz(escopo: Page | Locator): Page {
  return "page" in escopo && typeof (escopo as Locator).page === "function" ? (escopo as Locator).page() : (escopo as Page);
}

/** Card pelo título (h3). */
export function card(page: Page, titulo: string | RegExp): Locator {
  return page.locator(".card").filter({ has: page.locator("h3", { hasText: titulo }) }).first();
}

/** Sobrescreve uma rota do backend só neste cenário (erros e estados de carregamento). */
export async function simularApi(
  page: Page,
  padrao: string | RegExp,
  resposta: { status?: number; corpo?: unknown; atrasoMs?: number }
) {
  await page.route(typeof padrao === "string" ? `${API_URL}${padrao}` : padrao, async (route) => {
    if (route.request().method() === "OPTIONS") return route.continue();
    if (resposta.atrasoMs) await new Promise((r) => setTimeout(r, resposta.atrasoMs));
    await route.fulfill({
      status: resposta.status ?? 200,
      contentType: "application/json",
      body: JSON.stringify(resposta.corpo ?? {}),
    });
  });
}

/** Campo de formulário pelo texto do <label> do mesmo .field (vários labels do app não têm htmlFor). */
export function campo(escopo: Page | Locator, rotulo: string | RegExp): Locator {
  const texto = typeof rotulo === "string" ? new RegExp(`^\\s*${rotulo.replace(/[.*+?^${}()|[\]\\]/g, "\\$&")}\\s*$`) : rotulo;
  return escopo
    .locator(".field")
    .filter({ has: raiz(escopo).locator("label", { hasText: texto }) })
    .locator("input, select, textarea")
    .first();
}

/** Lê um .xlsx baixado (primeira aba) com o openpyxl do venv do backend: [cabeçalho, ...linhas]. */
export function lerXlsx(caminho: string): string[][] {
  const py = process.env.E2E_PYTHON ?? path.resolve(__dirname, "../../apps/backend/.venv/bin/python");
  const script =
    "import json,sys,openpyxl;ws=openpyxl.load_workbook(sys.argv[1],read_only=True).worksheets[0];" +
    "print(json.dumps([[('' if c is None else str(c)) for c in r] for r in ws.iter_rows(values_only=True)]))";
  return JSON.parse(execFileSync(py, ["-c", script, caminho]).toString());
}

/** Clica num botão de exportação e devolve o arquivo baixado (nome + linhas). */
export async function baixar(page: Page, clicar: () => Promise<unknown>) {
  const [download] = await Promise.all([page.waitForEvent("download"), clicar()]);
  // o openpyxl exige a extensão .xlsx no nome do arquivo
  const caminho = path.join(os.tmpdir(), `e2e-${Date.now()}-${download.suggestedFilename()}`);
  await download.saveAs(caminho);
  return { nome: download.suggestedFilename(), linhas: lerXlsx(caminho) };
}
