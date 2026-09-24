import { apiGet, campo, card, expect, permitirErrosConsole, responderDialogo, test } from "./fixtures";

const WABA = "1111111111";

test.describe("Configurações → Conexões", () => {
  test.beforeEach(async ({ page }) => {
    await page.goto("/configuracoes?aba=conexoes");
  });

  test("SETA: status conectado em somente leitura e botão de testar", async ({ page }) => {
    const seta = card(page, "SETA");
    await expect(seta.getByText("Conectado")).toBeVisible();
    await expect(seta.getByText("seta_fake")).toBeVisible();
    await expect(seta.getByText("Somente leitura ✓")).toBeVisible();
    await seta.getByRole("button", { name: "Testar conexão" }).click();
    await expect(seta.getByText(/\d+ ms/)).toBeVisible();
  });

  test("SETA fora do ar: mensagem de erro no card", async ({ page }) => {
    permitirErrosConsole(page, "503");
    await page.route("**/seta/status", (r) =>
      r.fulfill({ status: 503, contentType: "application/json", body: JSON.stringify({ detail: "Não foi possível conectar ao SETA (OperationalError)" }) })
    );
    await page.reload();
    await expect(card(page, "SETA").locator(".error-box")).toContainText("Não foi possível conectar ao SETA");
  });

  test("Google: conta conectada mostra e-mail e botão desconectar (cancelado)", async ({ page }) => {
    const g = card(page, "Google");
    await expect(g.getByText("teste@topfama.com.br")).toBeVisible();
    const dialogo = responderDialogo(page, false);
    await g.getByRole("button", { name: "Desconectar" }).click();
    expect(await dialogo).toContain("Desconectar a conta Google");
    await expect(g.getByText("teste@topfama.com.br")).toBeVisible();
  });

  test("Tokens da Meta: token inválido é recusado com mensagem", async ({ page }) => {
    permitirErrosConsole(page, /40\d/);
    const c = card(page, "Tokens da Meta");
    await c.getByLabel("Nome do token").fill("Token errado");
    await c.getByLabel("WABA ID").fill("abc" + WABA); // letras são descartadas
    await expect(c.getByLabel("WABA ID")).toHaveValue(WABA);
    await c.getByLabel("Token de acesso").fill("token-invalido");
    await c.getByRole("button", { name: "Cadastrar token" }).click();
    await expect(c.locator(".error-box").first()).toBeVisible();
    await expect(c.getByText("Nenhum token cadastrado")).toBeVisible();
  });

  test("Tokens da Meta: cadastrar, listar números, importar e testar", async ({ page }) => {
    const c = card(page, "Tokens da Meta");
    await c.getByLabel("Nome do token").fill("Token Cobrança");
    await c.getByLabel("WABA ID").fill(WABA);
    await c.getByLabel("Token de acesso").fill("EAA-token-de-teste-9876");
    await c.getByRole("button", { name: "Cadastrar token" }).click();

    const linha = c.locator("tbody tr", { hasText: "Token Cobrança" });
    await expect(linha).toBeVisible();
    await expect(linha).toContainText("…9876");
    await expect(c.getByLabel("Token de acesso")).toHaveValue(""); // formulário limpo
    // painel de números abre sozinho e pré-marca os não cadastrados
    await expect(page.getByText(`Números da WABA ${WABA} — Token Cobrança`)).toBeVisible();
    await expect(page.getByLabel("Importar +55 11 4000-0001")).toBeChecked();
    await expect(page.getByLabel("Importar +55 11 4000-0002")).toBeChecked();
    await page.getByRole("button", { name: "Importar selecionados (2)" }).click();
    await expect(page.getByText("2 número(s) importado(s).")).toBeVisible();
    await expect(page.getByText("Cadastrado com este token")).toHaveCount(2);
    await expect(page.getByRole("button", { name: /Importar selecionados \(0\)/ })).toBeDisabled();

    // card Números atualiza sem recarregar a página
    const numeros = card(page, "Números de WhatsApp");
    await expect(numeros.locator("tbody tr")).toHaveCount(2);

    await linha.getByRole("button", { name: "Testar" }).click();
    await expect(linha.locator(".success-box")).toBeVisible();
  });

  test("Tokens da Meta: editar token (vazio, inválido e válido)", async ({ page }) => {
    permitirErrosConsole(page, /40\d/);
    const c = card(page, "Tokens da Meta");
    const linha = c.locator("tbody tr", { hasText: "Token Cobrança" });
    await linha.getByRole("button", { name: "Editar token" }).click();
    await linha.getByRole("button", { name: "Salvar" }).click();
    await expect(linha.getByText("Informe o novo token")).toBeVisible();
    await linha.getByPlaceholder("Novo token (EAA...)").fill("token-invalido");
    await linha.getByRole("button", { name: "Salvar" }).click();
    await expect(linha.locator(".error-box")).toBeVisible();
    await linha.getByPlaceholder("Novo token (EAA...)").fill("EAA-token-novo-5555");
    await linha.getByRole("button", { name: "Salvar" }).click();
    await expect(linha).toContainText("…5555");
    await expect(linha.getByPlaceholder("Novo token (EAA...)")).toHaveCount(0);
  });

  test("Tokens da Meta: desativar e reativar", async ({ page }) => {
    const linha = card(page, "Tokens da Meta").locator("tbody tr", { hasText: "Token Cobrança" });
    await linha.getByRole("button", { name: "Desativar" }).click();
    await expect(linha.locator(".status-pill")).toHaveText("Não");
    await linha.getByRole("button", { name: "Ativar" }).click();
    await expect(linha.locator(".status-pill")).toHaveText("Sim");
  });

  test("Tokens da Meta: excluir pede confirmação citando os números vinculados (cancelado)", async ({ page }) => {
    const linha = card(page, "Tokens da Meta").locator("tbody tr", { hasText: "Token Cobrança" });
    const msg = responderDialogo(page, false);
    await linha.getByRole("button", { name: "Excluir" }).click();
    expect(await msg).toContain("2 número(s) vinculado(s)");
    await expect(linha).toBeVisible();
  });

  test("Números: editar apelido e inbox do Chatwoot, cancelar edição", async ({ page }) => {
    const numeros = card(page, "Números de WhatsApp");
    const l1 = numeros.locator("tbody tr", { hasText: "+55 11 4000-0001" });
    await l1.getByRole("button", { name: "Editar" }).click();
    await numeros.getByLabel("Apelido").fill("Cobrança 01");
    await numeros.getByLabel("ID da inbox do Chatwoot").fill("1");
    await numeros.getByRole("button", { name: "Salvar" }).click();
    await expect(numeros.locator("tbody tr", { hasText: "Cobrança 01" })).toContainText("1");

    const l2 = numeros.locator("tbody tr", { hasText: "+55 11 4000-0002" });
    await l2.getByRole("button", { name: "Editar" }).click();
    await numeros.getByLabel("Apelido").fill("Lembrete 02");
    await numeros.getByRole("button", { name: "Cancelar" }).click();
    await expect(numeros.getByText("Lembrete 02")).toHaveCount(0);
    await l2.getByRole("button", { name: "Editar" }).click();
    await numeros.getByLabel("Apelido").fill("Lembrete 02");
    await numeros.getByRole("button", { name: "Salvar" }).click();
    await expect(numeros.getByText("Lembrete 02")).toBeVisible();
    const lista = await apiGet(page, "/numbers");
    expect(lista.map((n: any) => n.label).sort()).toEqual(["Cobrança 01", "Lembrete 02"]);
  });

  test("Chatwoot: campos obrigatórios, salvar e testar conexão", async ({ page }) => {
    const cw = card(page, "Chatwoot");
    await cw.getByRole("button", { name: "Salvar" }).click();
    expect(await cw.getByPlaceholder("https://chat.suaempresa.com.br").evaluate((e: HTMLInputElement) => e.validity.valid)).toBe(false);
    await cw.getByPlaceholder("https://chat.suaempresa.com.br").fill("https://chatwoot.teste.local");
    await campo(cw, "ID da conta").fill("3");
    await campo(cw, "Token de acesso da API").fill("cw-token-teste");
    await cw.getByRole("button", { name: "Salvar" }).click();
    await expect(cw.getByText("Configurado")).toBeVisible();
    await expect(campo(cw, "Token de acesso da API")).toHaveValue("");
    await cw.getByRole("button", { name: "Testar conexão" }).click();
    await expect(cw.locator(".success-box")).toBeVisible();
    await expect(cw.getByRole("heading", { name: "Testar envio de template" })).toBeVisible();
  });
});
