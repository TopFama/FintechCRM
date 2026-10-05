import { apiGet, campo, card, expect, permitirErrosConsole, test } from "./fixtures";
import { prepararConexoes } from "./preparo";

test.beforeAll(prepararConexoes);

test.describe("Configurações → Templates", { tag: "@templates" }, () => {
  test.beforeEach(async ({ page }) => {
    await page.goto("/configuracoes?aba=templates");
  });

  test("sincronizar com a Meta traz os templates e mostra o status", async ({ page }) => {
    await expect(page.getByText("Nenhum template cadastrado")).toBeVisible();
    await page.getByRole("button", { name: "Sincronizar", exact: true }).click();
    const tabela = card(page, "Templates cadastrados");
    await expect(tabela.locator("tbody tr")).toHaveCount(3);
    const cobranca = (await apiGet(page, "/templates")).find((t: any) => t.meta_template_name === "cobranca_atraso");
    expect(cobranca.variables.map((v: any) => v.internal_name)).toEqual(["variavel_1", "variavel_2", "variavel_3", "variavel_4"]);
    await expect(tabela.locator("thead th")).toHaveText([/Template/, /Tipo/, /WABA/, /Telefones/, /Status/, /Imagem/, ""]);
    await expect(tabela.locator("tbody tr", { hasText: "promo_reprovada" }).locator(".badge")).toHaveText(/rejected|reprovado/i);
    await expect(tabela.locator("tbody tr", { hasText: "promo_reprovada" })).toContainText("Marketing");
    await expect(tabela.locator("tbody tr", { hasText: "cobranca_atraso" })).toContainText("Utilidade");
  });

  test("ordenar a tabela por nome e por status", async ({ page }) => {
    const tabela = card(page, "Templates cadastrados");
    const nomes = () => tabela.locator("tbody tr td:first-child").allInnerTexts();
    await tabela.getByRole("columnheader", { name: /Nome/ }).click();
    const asc = await nomes();
    expect(asc).toEqual([...asc].sort((a, b) => a.localeCompare(b)));
    await tabela.getByRole("columnheader", { name: /Nome/ }).click();
    expect(await nomes()).toEqual([...asc].reverse());
  });

  test("pré-visualizar e mapear variável para campo do cliente", async ({ page }) => {
    const tabela = card(page, "Templates cadastrados");
    const linha = tabela.locator("tbody tr", { hasText: "cobranca_atraso" });
    await linha.getByRole("button", { name: "Pré-visualizar" }).click();
    const bolha = tabela.locator(".template-preview-bubble");
    await expect(bolha).toContainText("(não mapeado)");
    const sel = campo(tabela, "{{1}} (variavel_1)");
    const opcoes = await sel.locator("option").allInnerTexts();
    expect(opcoes.length).toBeGreaterThan(2);
    await sel.selectOption({ label: opcoes.find((o) => /nome/i.test(o))! });
    await expect(bolha).not.toContainText("{{1}} (não mapeado)");
    // persistiu no backend
    const t = (await apiGet(page, "/templates")).find((x: any) => x.name === "cobranca_atraso" || x.meta_template_name === "cobranca_atraso");
    expect(t.variables.find((v: any) => v.position === 1).campo_sugerido).toBeTruthy();
    await linha.getByRole("button", { name: "Fechar" }).click();
    await expect(bolha).toHaveCount(0);
  });

  test("mapeia todas as variáveis do template de cobrança (usado nas próximas etapas)", async ({ page }) => {
    const tabela = card(page, "Templates cadastrados");
    await tabela.locator("tbody tr", { hasText: "cobranca_atraso" }).getByRole("button", { name: "Pré-visualizar" }).click();
    const alvo: [number, RegExp][] = [[2, /valor/i], [3, /vencimento/i], [4, /c[óo]digo/i]];
    for (const [pos, re] of alvo) {
      const sel = campo(tabela, `{{${pos}}} (variavel_${pos})`);
      const rotulo = (await sel.locator("option").allInnerTexts()).find((o) => re.test(o));
      expect(rotulo, `campo para {{${pos}}}`).toBeTruthy();
      await sel.selectOption({ label: rotulo! });
    }
    await expect(tabela.locator(".template-preview-bubble")).not.toContainText("não mapeado");
  });

  test("criar template: nome em snake_case, idioma fixo, categorias, variáveis e cancela", async ({ page }) => {
    const novo = card(page, "Novo template");
    await novo.getByRole("button", { name: "Criar template" }).click();
    await campo(novo, "Nome interno").fill("Cobrança Atraso 15 dias");
    await expect(campo(novo, "Nome na Meta")).toHaveValue("cobranca_atraso_15_dias");
    await campo(novo, "Nome na Meta").fill("Outro-Nome Ç");
    await expect(campo(novo, "Nome na Meta")).toHaveValue("outro_nome_c");
    await expect(campo(novo, "Idioma")).toHaveValue("Português (Brasil)");
    await expect(campo(novo, "Idioma")).toBeDisabled();
    expect(await campo(novo, "Categoria").locator("option").allInnerTexts()).toEqual(["Utilidade", "Marketing"]);

    await campo(novo, /Corpo do template/).fill("{{1}}, pague {{3}}");
    await expect(novo.locator(".field-error")).toHaveText([
      "As variáveis precisam ser {{1}}, {{2}}… em sequência.",
      "O corpo não pode começar nem terminar com variável.",
    ]);
    await expect(novo.getByRole("button", { name: "Salvar template" })).toBeDisabled();

    await campo(novo, /Corpo do template/).fill("Olá {{1}}, pague {{2}} até {{1}}.");
    await expect(novo.getByText(/Variáveis detectadas: variavel_1, variavel_2/)).toBeVisible();
    await expect(novo.locator(".field-error")).toHaveCount(0);
    await campo(novo, "Nome interno").fill("");
    await novo.getByRole("button", { name: "Salvar template" }).click();
    expect(await campo(novo, "Nome interno").evaluate((e: HTMLInputElement) => e.validity.valid)).toBe(false);
    await novo.getByRole("button", { name: "Cancelar" }).click();
    await expect(novo.getByRole("button", { name: "Salvar template" })).toHaveCount(0);
  });

  test("prévia com a formatação do WhatsApp e exemplos das variáveis", async ({ page }) => {
    const novo = card(page, "Novo template");
    await novo.getByRole("button", { name: "Criar template" }).click();
    await campo(novo, /Corpo do template/).fill("Olá *{{1}}*, pague ~R$ 10~ _hoje_ com `pix`.\n- boleto\n- cartão\n> TopFama\n```linha mono```");
    const bolha = novo.locator(".template-preview-bubble");
    await expect(bolha.locator("strong")).toHaveText("{{1}}");
    await campo(novo, "Campo do cliente de {{1}}").selectOption({ label: (await campo(novo, "Campo do cliente de {{1}}").locator("option").allInnerTexts()).find((o) => /nome/i.test(o))! });
    await expect(campo(novo, "Exemplo de {{1}}")).not.toHaveValue("");
    await campo(novo, "Exemplo de {{1}}").fill("Maria");
    await expect(bolha.locator("strong")).toHaveText("Maria");
    await expect(bolha.locator("s")).toHaveText("R$ 10");
    await expect(bolha.locator("em")).toHaveText("hoje");
    await expect(bolha.locator("code")).toHaveText("pix");
    await expect(bolha.locator("li")).toHaveText(["boleto", "cartão"]);
    await expect(bolha.locator("blockquote")).toHaveText("TopFama");
    await expect(bolha.locator("pre")).toHaveText("linha mono");
    await campo(novo, "Cabeçalho com imagem?").selectOption("image");
    await expect(bolha.getByText("Imagem do cabeçalho")).toBeVisible();
    await novo.getByRole("button", { name: "Cancelar" }).click();
  });

  test("criar rascunho e enviar para aprovação na Meta", async ({ page }) => {
    const novo = card(page, "Novo template");
    const tabela = card(page, "Templates cadastrados");
    await novo.getByRole("button", { name: "Criar template" }).click();
    await campo(novo, "Nome interno").fill("Enviado Meta");
    await campo(novo, /Corpo do template/).fill("Oi {{1}}, sua fatura {{2}} chegou.");
    await campo(novo, "Exemplo de {{1}}").fill("Maria");
    await campo(novo, "Exemplo de {{2}}").fill("189,90");
    await novo.getByRole("button", { name: "Salvar template" }).click();
    const linha = tabela.locator("tbody tr", { hasText: "Enviado Meta" });
    await expect(linha).toContainText("enviado_meta");
    await expect(linha.locator(".badge")).toHaveText(/draft|rascunho/i);
    const salvo = (await apiGet(page, "/templates")).find((t: any) => t.name === "Enviado Meta");
    expect(salvo.language).toBe("pt_BR");
    expect(salvo.variables.map((v: any) => v.exemplo)).toEqual(["Maria", "189,90"]);

    await linha.getByRole("button", { name: "Enviar para aprovação" }).click();
    await expect(linha.locator(".badge")).toHaveText(/pending|pendente/i);
    await expect(page.locator(".success-box").first()).toContainText("enviado para aprovação");
    await linha.getByRole("button", { name: "Atualizar status" }).click();
    await expect(linha.locator(".badge")).toHaveText(/pending|pendente/i);
  });

  test("imagem do cabeçalho: subir e trocar", async ({ page }) => {
    // PNG 1x1
    const png = Buffer.from("iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNk+M9QDwADhgGAWjR9awAAAABJRU5ErkJggg==", "base64");
    const novo = card(page, "Novo template");
    await novo.getByRole("button", { name: "Criar template" }).click();
    await campo(novo, "Nome interno").fill("Com imagem");
    await campo(novo, "Cabeçalho com imagem?").selectOption("image");
    await campo(novo, /Corpo do template/).fill("Oi {{1}}, sua fatura chegou.");
    await campo(novo, "Exemplo de {{1}}").fill("Maria");
    await novo.getByRole("button", { name: "Salvar template" }).click();
    const linha = card(page, "Templates cadastrados").locator("tbody tr", { hasText: "Com imagem" });

    // sem imagem a Meta recusaria: o backend barra antes
    permitirErrosConsole(page, "400");
    await linha.getByRole("button", { name: "Enviar para aprovação" }).click();
    await expect(page.locator(".error-box").first()).toContainText("Suba a imagem do cabeçalho");
    const imagem = async () =>
      (await apiGet(page, "/templates")).find((t: any) => t.name === "Com imagem").image_url as string | null;

    await linha.locator("label", { hasText: "subir" }).locator("input[type=file]").setInputFiles({ name: "a.png", mimeType: "image/png", buffer: png });
    await expect(linha.locator(".badge", { hasText: "enviada" })).toBeVisible();
    const primeira = await imagem();
    expect(primeira).toMatch(/\/media\/.+\.png\?v=/);

    // mesmo arquivo de novo: o link muda para ninguém mostrar a imagem antiga guardada
    await linha.locator("label", { hasText: "trocar" }).locator("input[type=file]").setInputFiles({ name: "b.png", mimeType: "image/png", buffer: png });
    await expect.poll(imagem).not.toBe(primeira);
    await expect(linha.locator(".badge", { hasText: "enviada" })).toBeVisible();
  });

  test("imagem que precisa de otimização: mostra para validar, recusar mantém a anterior, aprovar troca", async ({ page }) => {
    // .webp 64x40: o WhatsApp não aceita, então o backend converte e pede validação
    const webp = Buffer.from(
      "UklGRlAAAABXRUJQVlA4IEQAAACwAwCdASpAACgAPjEYi0QiIaERVAAgAwSzgDsAfgAAFRpjHD4MwAD+9Sdf//wJ34E78Cd/4E7//9Tj8nH5OP6ygAAAAA==",
      "base64"
    );
    const linha = card(page, "Templates cadastrados").locator("tbody tr", { hasText: "Com imagem" });
    const imagem = async () =>
      (await apiGet(page, "/templates")).find((t: any) => t.name === "Com imagem").image_url as string | null;
    const antes = await imagem();
    const validacao = card(page, /Validar imagem otimizada/);

    await linha.locator("label", { hasText: "trocar" }).locator("input[type=file]").setInputFiles({ name: "arte.webp", mimeType: "image/webp", buffer: webp });
    await expect(validacao).toBeVisible();
    await expect(validacao).toContainText("precisou ser otimizada");
    await expect(validacao.getByRole("img", { name: "Imagem original enviada" })).toBeVisible();
    await expect(validacao.getByRole("img", { name: "Imagem otimizada" })).toBeVisible();
    await expect(validacao).toContainText("Otimizada · JPEG");
    expect(await imagem()).toBe(antes);

    await validacao.getByRole("button", { name: "Não usar" }).click();
    await expect(validacao).toHaveCount(0);
    await expect(page.locator(".error-box").first()).toContainText("é necessário subir uma imagem de até 5 MB");
    expect(await imagem()).toBe(antes);

    await linha.locator("label", { hasText: "trocar" }).locator("input[type=file]").setInputFiles({ name: "arte.webp", mimeType: "image/webp", buffer: webp });
    await validacao.getByRole("button", { name: "Usar imagem otimizada" }).click();
    await expect(page.locator(".success-box").first()).toContainText("Imagem otimizada salva");
    await expect.poll(imagem).toMatch(/\/media\/.+\.jpg\?v=/);
  });

  test("template com imagem vai para aprovação com a imagem do cabeçalho", async ({ page }) => {
    const linha = card(page, "Templates cadastrados").locator("tbody tr", { hasText: "Com imagem" });
    await linha.getByRole("button", { name: "Enviar para aprovação" }).click();
    await expect(linha.locator(".badge").first()).toHaveText(/pending|pendente/i);
    await expect(linha.getByRole("button", { name: "Enviar para aprovação" })).toHaveCount(0);
  });

  test("falha na sincronização aparece como erro e o botão volta ao normal", async ({ page }) => {
    permitirErrosConsole(page, "400");
    await page.route("**/templates/meta/sync", (r) =>
      r.fulfill({ status: 400, contentType: "application/json", body: JSON.stringify({ detail: "Nenhuma WABA sincronizou — WABA 1: token expirado" }) })
    );
    await page.getByRole("button", { name: "Sincronizar", exact: true }).click();
    await expect(page.locator(".error-box").first()).toContainText("token expirado");
    await expect(page.getByRole("button", { name: "Sincronizar", exact: true })).toBeEnabled();
  });
});

test.describe("Conexões → Chatwoot: testar envio de template", { tag: "@templates" }, () => {
  test("envia teste e mostra o resultado; botão só libera com tudo preenchido", async ({ page }) => {
    await page.goto("/configuracoes?aba=conexoes");
    const cw = card(page, "Chatwoot");
    const enviar = cw.getByRole("button", { name: "Enviar teste" });
    await expect(enviar).toBeDisabled();
    await campo(cw, "Template").selectOption({ label: "cobranca_atraso" });
    await expect(cw.locator(".template-preview-bubble")).toBeVisible();
    await campo(cw, "Número de origem").selectOption({ index: 1 });
    await expect(enviar).toBeDisabled();
    await campo(cw, "Celular de destino").fill("5511999990000");
    await expect(enviar).toBeEnabled();
    await enviar.click();
    await expect(cw.locator(".field-success, .field-error")).toBeVisible();
    await expect(cw.locator(".field-success")).toBeVisible();
    const envios = await apiGet(page, "/__e2e/envios");
    expect(envios.some((e: any) => e.canal === "chatwoot")).toBeTruthy();
  });
});
