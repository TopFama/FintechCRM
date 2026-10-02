// Preparo de estado pela API, no lugar de rodar os cenários anteriores só para
// montar dados. Cada etapa só cria o que ainda não existe (pode rodar de novo, na
// suíte inteira ou depois de um cenário que excluiu o token), e chama as etapas
// de que depende. Os cenários que testam a própria tela (02 a 08) criam o estado
// pela interface; os demais declaram o que precisam num test.beforeAll:
//
//   test.beforeAll(prepararOperacao);
//
// O resultado é o mesmo estado que a cadeia de specs deixava: o que cada etapa
// reproduz está no comentário dela.

import { expect, request, type APIRequestContext } from "@playwright/test";
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { STORAGE_STATE } from "../playwright.config";
import { API_URL } from "./ambiente";
import { apiGet, apiSend } from "./fixtures";

const DADOS = path.join(path.dirname(fileURLToPath(import.meta.url)), "dados");
const WABA = "1111111111";
const NUMEROS = [
  { phoneNumberId: "900001", rotulo: "Cobrança 01", inbox: 1 },
  { phoneNumberId: "900002", rotulo: "Lembrete 02", inbox: null },
];
// campo do cliente sugerido para cada variável do template cobranca_atraso (como o spec 03 mapeia)
const CAMPOS_COBRANCA = ["nome", "valor_em_aberto", "vencimento", "codigo"];

async function comSessao<T>(fn: (api: APIRequestContext) => Promise<T>): Promise<T> {
  const api = await request.newContext({ storageState: STORAGE_STATE });
  try {
    return await fn(api);
  } finally {
    await api.dispose();
  }
}

async function enviar(api: APIRequestContext, metodo: "POST" | "PUT" | "PATCH", caminho: string, corpo?: unknown) {
  const r = await apiSend(api, metodo, caminho, corpo);
  expect(r.status, `${metodo} ${caminho} → ${r.status} ${JSON.stringify(r.corpo)}`).toBeLessThan(300);
  return r.corpo;
}

/** Token da Meta com os dois números importados, apelidos, inbox do Chatwoot e Chatwoot configurado (spec 02). */
export async function prepararConexoes() {
  await comSessao(async (api) => {
    const tokens = await apiGet(api, "/meta-tokens");
    const token =
      tokens[0] ?? (await enviar(api, "POST", "/meta-tokens", { nome: "Token Cobrança", token: "EAA-token-de-teste-9876", waba_id: WABA }));
    if ((await apiGet(api, "/numbers")).length === 0) {
      await enviar(api, "POST", `/meta-tokens/${token.id}/importar-numeros`, { phone_number_ids: NUMEROS.map((n) => n.phoneNumberId) });
    }
    for (const n of await apiGet(api, "/numbers")) {
      const esperado = NUMEROS.find((x) => x.phoneNumberId === n.phone_number_id);
      if (!esperado || n.label === esperado.rotulo) continue;
      await enviar(api, "PATCH", `/numbers/${n.id}`, { label: esperado.rotulo, chatwoot_inbox_id: n.chatwoot_inbox_id ?? esperado.inbox });
    }
    if (!(await apiGet(api, "/chatwoot/status")).configurado) {
      await enviar(api, "PUT", "/chatwoot/config", {
        base_url: "https://chatwoot.teste.local",
        account_id: "3",
        api_access_token: "cw-token-teste",
      });
    }
  });
}

/** Templates da Meta sincronizados e o cobranca_atraso com os campos sugeridos (specs 03). */
export async function prepararTemplates() {
  await prepararConexoes();
  await comSessao(async (api) => {
    if (!(await apiGet(api, "/templates")).some((t: any) => t.name === "cobranca_atraso")) {
      await enviar(api, "POST", "/templates/meta/sync");
    }
    const cobranca = (await apiGet(api, "/templates")).find((t: any) => t.name === "cobranca_atraso");
    for (const v of cobranca.variables) {
      if (v.campo_sugerido) continue;
      await enviar(api, "PATCH", `/templates/${cobranca.id}/variaveis/${v.id}`, { campo_sugerido: CAMPOS_COBRANCA[v.position - 1] });
    }
  });
}

/** Faixas de atraso sincronizadas; 3 A 10 com o envio "Cobrança 01" e 11 A 20 com o "Lembrete 02", ambos com cobranca_atraso (spec 04). */
export async function prepararFaixas() {
  await prepararTemplates();
  await comSessao(async (api) => {
    await enviar(api, "POST", "/faixas/sincronizar-faixas-atraso");
    const numeros = await apiGet(api, "/numbers");
    const template = (await apiGet(api, "/templates")).find((t: any) => t.name === "cobranca_atraso");
    for (const [nomeFaixa, { rotulo }] of [["3 A 10", NUMEROS[0]], ["11 A 20", NUMEROS[1]]] as const) {
      const faixa = (await apiGet(api, "/faixas")).find((f: any) => f.name === nomeFaixa);
      const numero = numeros.find((n: any) => n.label === rotulo);
      if (faixa.envios.some((e: any) => e.whatsapp_number_id === numero.id && e.template_id === template.id)) continue;
      await enviar(api, "POST", `/faixas/${faixa.id}/envios`, {
        whatsapp_number_id: numero.id,
        template_id: template.id,
        variable_mappings: template.variables.map((v: any) => ({
          template_variable_id: v.id,
          fonte_tipo: "campo_cliente",
          column_name: CAMPOS_COBRANCA[v.position - 1],
        })),
      });
    }
  });
}

/** Clientes 35 e 36 na blacklist: a base de cobrança do SETA falso fica com 34 (spec 07). */
export async function prepararBlacklist() {
  await comSessao(async (api) => {
    await enviar(api, "POST", "/blacklist/lote", { documentos: ["35", "36"], motivo: "Pediu para não ser cobrado" });
  });
}

/** Disparo liberado o dia todo, em todos os dias, e o envio da faixa 3 A 10 ativo (spec 05). */
export async function prepararDisparo() {
  await prepararFaixas();
  await comSessao(async (api) => {
    await enviar(api, "PUT", "/config/cobranca/disparo", {
      schedule_days: "1,2,3,4,5,6,7",
      schedule_start: "00:00",
      schedule_end: "23:59",
      leads_auto_extract: false,
      leads_auto_extract_minutos_antes: 10,
      interval_seconds: 2,
      batch_size: 50,
    });
    const faixa = (await apiGet(api, "/faixas")).find((f: any) => f.name === "3 A 10");
    for (const e of faixa.envios) {
      await enviar(api, "PUT", `/faixas/${faixa.id}/envios/${e.id}/dispatch-config`, { ...e.dispatch_config, active: true });
    }
  });
}

/** Todos os clientes de 3 A 10 e 11 A 20 na fila, como o "Enviar para fila de cobrança" do spec 09 (sem as regras padrão). */
export async function prepararFila() {
  await prepararDisparo();
  await prepararBlacklist();
  await comSessao(async (api) => {
    const consulta = "faixa=3 A 10&faixa=11 A 20&apenas_primeiro_dia=false&somente_regra_whatsapp=false";
    // a base de cobrança é calculada em segundo plano: repete até vir pronta
    await expect
      .poll(async () => (await apiSend(api, "POST", `/leads/gerar?${consulta}`)).corpo?.status, { timeout: 60_000 })
      .toBe("ready");
  });
}

/** Planilha da faixa 11 A 20 importada (telefones inválidos e erros de importação, spec 10) e a fila de 3 A 10 já enviada (spec 11). */
export async function prepararOperacao() {
  await prepararFila();
  await comSessao(async (api) => {
    const faixa = (await apiGet(api, "/faixas")).find((f: any) => f.name === "11 A 20");
    // a planilha tem linhas com erro: se o relatório de erros já tem linhas, ela já foi importada
    if ((await apiGet(api, "/relatorios/erros?limit=1&offset=0")).total > 0) return;
    const planilha = path.join(DADOS, "planilha_faixa.xlsx");
    const variaveis = faixa.envios.flatMap((e: any) => e.template.variables).map((v: any) => v.id);
    const colunas = ["Nome Completo", "Valor Devido", "Vencimento", "Codigo Cliente"];
    const r = await api.post(`${API_URL}/faixas/${faixa.id}/uploads`, {
      multipart: {
        file: { name: "planilha_faixa.xlsx", mimeType: "application/octet-stream", buffer: fs.readFileSync(planilha) },
        mapping: JSON.stringify({
          celular: "Telefone",
          codigo_cliente: "Codigo Cliente",
          nome: "Nome Completo",
          cpf: "Documento",
          valor: "Valor Devido",
          variables: Object.fromEntries(variaveis.map((id: string, i: number) => [id, colunas[i % colunas.length]])),
        }),
      },
    });
    expect(r.ok(), `importação da planilha → ${r.status()} ${await r.text()}`).toBeTruthy();

    const enviada = (await apiGet(api, "/faixas")).find((f: any) => f.name === "3 A 10");
    await expect
      .poll(async () => {
        const { itens } = await apiGet(api, `/faixas/${enviada.id}/queue?limit=500&offset=0`);
        return itens.filter((i: any) => i.status === "pending").length;
      }, { timeout: 45_000 })
      .toBe(0);
    // o resumo e a efetividade ficam em cache: sem isto a tela mostraria o que o login de setup viu, antes do preparo
    await enviar(api, "POST", "/__e2e/cache/limpar");
  });
}
