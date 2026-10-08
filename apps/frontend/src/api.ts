const API_URL = import.meta.env.VITE_API_URL || "http://localhost:8000";

/** Imagem de cabeçalho de template: /media é servido pelo backend, não pelo frontend. */
export function urlImagemTemplate(imageUrl: string): string {
  return /^https?:\/\//.test(imageUrl) ? imageUrl : `${API_URL}${imageUrl}`;
}

// Sinalizadores locais só para a UI decidir o que mostrar sem esperar uma
// chamada à API — não é o que autentica/autoriza (isso é o cookie httpOnly +
// checagem no backend), então não tem problema em ficarem acessíveis via JS.
const AUTH_FLAG_KEY = "autenticado";
const ADMIN_FLAG_KEY = "eh_admin";

export function marcarAutenticado(isAdmin: boolean) {
  localStorage.setItem(AUTH_FLAG_KEY, "1");
  localStorage.setItem(ADMIN_FLAG_KEY, isAdmin ? "1" : "0");
}

export function limparAutenticado() {
  localStorage.removeItem(AUTH_FLAG_KEY);
  localStorage.removeItem(ADMIN_FLAG_KEY);
}

export function pareceAutenticado(): boolean {
  return localStorage.getItem(AUTH_FLAG_KEY) === "1";
}

export function pareceAdmin(): boolean {
  return localStorage.getItem(ADMIN_FLAG_KEY) === "1";
}

export class ApiError extends Error {
  status: number;

  constructor(status: number, message: string) {
    super(message);
    this.name = "ApiError";
    this.status = status;
  }
}

// Erro de validação do FastAPI (422) vem como lista de objetos com nomes de
// campo internos — não faz sentido para o usuário.
function textoDoErro(detail: unknown): string {
  if (typeof detail === "string") return detail;
  if (Array.isArray(detail)) return "Dados inválidos: confira os campos preenchidos.";
  return "";
}

async function request<T>(path: string, options: RequestInit = {}): Promise<T> {
  const headers: Record<string, string> = {
    ...(options.body && !(options.body instanceof FormData)
      ? { "Content-Type": "application/json" }
      : {}),
    ...((options.headers as Record<string, string>) || {}),
  };

  // O token de sessão vive só num cookie httpOnly (setado por POST /auth/login) —
  // nunca em localStorage/JS, para não ficar exposto a um eventual XSS no frontend.
  const response = await fetch(`${API_URL}${path}`, { ...options, headers, credentials: "include" });
  if (response.status === 401) {
    if (path.startsWith("/auth/login")) {
      const body = await response.json().catch(() => ({}));
      throw new ApiError(401, body.detail || "Email ou senha incorretos");
    }
    limparAutenticado();
    window.location.href = "/login";
    throw new ApiError(401, "Sessão expirada");
  }
  if (!response.ok) {
    const body = await response.json().catch(() => ({}));
    throw new ApiError(response.status, textoDoErro(body.detail) || `Erro ${response.status}`);
  }
  if (
    response.status === 204 ||
    response.status === 205 ||
    response.headers.get("content-length") === "0"
  ) {
    return undefined as unknown as T;
  }
  if (response.headers.get("content-type")?.includes("application/json")) {
    const text = await response.text();
    if (!text || !text.trim()) {
      return undefined as unknown as T;
    }
    return JSON.parse(text) as T;
  }
  return response as unknown as T;
}

// 503 nas rotas de cobrança = ERP fora do ar ou não configurado
export function mensagemErroSeta(e: unknown): string {
  if (e instanceof ApiError && e.status === 503) {
    return e.message.startsWith("SETA") ? e.message : `SETA indisponível: ${e.message}`;
  }
  return e instanceof Error ? e.message : "Erro desconhecido";
}

// Relatórios pesados do SETA (base de cobrança) calculam em segundo plano no
// backend (cache Redis) — a primeira consulta com um filtro novo devolve
// "processing" na hora, sem segurar a conexão; aqui a gente só tenta de novo até
// vir "ready", então quem chama continua recebendo uma Promise normal com o
// resultado, como se fosse uma chamada síncrona.
//
// O intervalo cresce (2 s, 2 s, 3 s, 3 s, 4 s, 5 s…) e leva um jitter de ±20%:
// abas abertas ao mesmo tempo não consultam o backend em sincronia. O `signal`
// cancela de verdade: a espera termina e o polling para na hora (filtro trocado,
// tela fechada), em vez de seguir pedindo ao SETA por minutos.
const ESPERAS_POLLING_MS = [2000, 2000, 3000, 3000, 4000, 5000];
const LIMITE_POLLING_MS = 180_000;

function esperar(ms: number, signal?: AbortSignal): Promise<void> {
  return new Promise((resolve, reject) => {
    if (signal?.aborted) return reject(new DOMException("Cancelado", "AbortError"));
    const timer = setTimeout(() => {
      signal?.removeEventListener("abort", cancelar);
      resolve();
    }, ms);
    const cancelar = () => {
      clearTimeout(timer);
      reject(new DOMException("Cancelado", "AbortError"));
    };
    signal?.addEventListener("abort", cancelar, { once: true });
  });
}

/** Consulta cancelada de propósito (filtro trocado, tela fechada): não é erro para mostrar. */
export function foiCancelada(e: unknown): boolean {
  return e instanceof DOMException && e.name === "AbortError";
}

async function pollAsync<T>(
  chamar: (signal?: AbortSignal) => Promise<{ status: "ready" | "processing"; data: T | null }>,
  signal?: AbortSignal
): Promise<T> {
  const inicio = Date.now();
  for (let tentativa = 0; Date.now() - inicio < LIMITE_POLLING_MS; tentativa++) {
    const resultado = await chamar(signal);
    if (resultado.status === "ready" && resultado.data !== null) {
      return resultado.data;
    }
    const base = ESPERAS_POLLING_MS[Math.min(tentativa, ESPERAS_POLLING_MS.length - 1)];
    await esperar(base * (0.8 + Math.random() * 0.4), signal);
  }
  throw new ApiError(504, "O relatório está demorando mais que o esperado para calcular — tente novamente");
}

// Gera query string com arrays como parâmetros repetidos (?a=1&a=2) e ignora vazios.
export interface OrdenacaoParams {
  sort_by?: string;
  sort_dir?: "asc" | "desc";
}

export function montarQuery(params: object): string {
  const qs = new URLSearchParams();
  for (const [k, v] of Object.entries(params)) {
    if (v === undefined || v === null || v === "") continue;
    if (Array.isArray(v)) {
      v.forEach((item) => {
        if (item !== undefined && item !== null && item !== "") {
          qs.append(k, String(item));
        }
      });
    } else {
      qs.append(k, String(v));
    }
  }
  return qs.toString();
}

export const api = {
  login: (email: string, password: string) =>
    request<{ access_token: string; is_admin: boolean }>("/auth/login", {
      method: "POST",
      body: JSON.stringify({ email, password }),
    }),
  logout: () => request<{ ok: boolean }>("/auth/logout", { method: "POST" }),

  listUsuarios: () => request<Usuario[]>("/users"),
  criarUsuario: (email: string, password: string) =>
    request<Usuario>("/users", { method: "POST", body: JSON.stringify({ email, password }) }),
  excluirUsuario: (id: string) => request<void>(`/users/${id}`, { method: "DELETE" }),

  listNumbers: () => request<WhatsappNumber[]>("/numbers"),
  createNumber: (payload: Partial<WhatsappNumber>) =>
    request<WhatsappNumber>("/numbers", { method: "POST", body: JSON.stringify(payload) }),
  atualizarNumero: (
    id: string,
    payload: {
      label?: string;
      active?: boolean;
      meta_token_id?: string | null;
      chatwoot_inbox_id?: number | null;
    }
  ) =>
    request<WhatsappNumber>(`/numbers/${id}`, { method: "PATCH", body: JSON.stringify(payload) }),
  excluirNumero: (id: string) => request<void>(`/numbers/${id}`, { method: "DELETE" }),

  listarTokensMeta: () => request<MetaToken[]>("/meta-tokens"),
  criarTokenMeta: (payload: { nome: string; token: string; waba_id: string }) =>
    request<MetaToken>("/meta-tokens", { method: "POST", body: JSON.stringify(payload) }),
  atualizarTokenMeta: (id: string, payload: { nome?: string; ativo?: boolean; waba_id?: string; token?: string }) =>
    request<MetaToken>(`/meta-tokens/${id}`, { method: "PATCH", body: JSON.stringify(payload) }),
  excluirTokenMeta: (id: string) =>
    request<void>(`/meta-tokens/${id}`, { method: "DELETE" }),
  testarTokenMeta: (id: string) =>
    request<MetaTokenTestResult>(`/meta-tokens/${id}/testar`, { method: "POST" }),
  listarNumerosMeta: (id: string) => request<NumeroMeta[]>(`/meta-tokens/${id}/numeros-meta`),
  importarNumerosMeta: (id: string, phoneNumberIds: string[]) =>
    request<{ importados: number; vinculados: number; ignorados: number }>(`/meta-tokens/${id}/importar-numeros`, {
      method: "POST",
      body: JSON.stringify({ phone_number_ids: phoneNumberIds }),
    }),

  listTemplates: () => request<Template[]>("/templates"),
  createTemplate: (payload: TemplateCreate) =>
    request<Template>("/templates", { method: "POST", body: JSON.stringify(payload) }),
  enviarTemplateParaAprovacao: (id: string) =>
    request<Template>(`/templates/${id}/enviar-para-aprovacao`, { method: "POST" }),
  syncTemplatesFromMeta: () => request<Template[]>("/templates/meta/sync", { method: "POST" }),
  refreshTemplateStatus: (id: string) =>
    request<Template>(`/templates/${id}/refresh-status`, { method: "POST" }),
  listCamposCliente: () => request<CampoCliente[]>("/templates/variaveis/campos"),
  atualizarVariavelTemplate: (templateId: string, variavelId: string, campoSugerido: string | null) =>
    request<TemplateVariable>(`/templates/${templateId}/variaveis/${variavelId}`, {
      method: "PATCH",
      body: JSON.stringify({ campo_sugerido: campoSugerido }),
    }),
  testarEnvioChatwoot: (
    templateId: string,
    payload: { whatsapp_number_id: string; celular: string; variables: Record<string, string> }
  ) =>
    request<ChatwootTestResult>(`/templates/${templateId}/testar-envio-chatwoot`, {
      method: "POST",
      body: JSON.stringify(payload),
    }),
  testarEnvioTemplate: (
    templateId: string,
    payload: { whatsapp_number_id: string; celular: string; variables: Record<string, string> }
  ) =>
    request<ChatwootTestResult>(`/templates/${templateId}/testar-envio`, {
      method: "POST",
      body: JSON.stringify(payload),
    }),
  uploadTemplateImage: (id: string, file: File) => {
    const form = new FormData();
    form.append("file", file);
    return request<TemplateImagemResultado>(`/templates/${id}/image`, { method: "POST", body: form });
  },
  confirmarImagemOtimizada: (id: string, token: string) =>
    request<Template>(`/templates/${id}/image/confirmar`, { method: "POST", body: JSON.stringify({ token }) }),
  descartarImagemOtimizada: (id: string, token: string) =>
    request<void>(`/templates/${id}/image/pendente?token=${encodeURIComponent(token)}`, { method: "DELETE" }),
  removerImagemTemplate: (id: string) =>
    request<Template>(`/templates/${id}/image`, { method: "DELETE" }),

  listFaixas: () => request<Faixa[]>("/faixas"),
  getFaixa: (id: string) => request<Faixa>(`/faixas/${id}`),
  createFaixa: (payload: unknown) =>
    request<Faixa>("/faixas", { method: "POST", body: JSON.stringify(payload) }),
  sincronizarFaixasAtraso: () =>
    request<{ criadas: string[]; ja_existentes: string[] }>("/faixas/sincronizar-faixas-atraso", {
      method: "POST",
    }),
  adicionarEnvio: (
    faixaId: string,
    payload: { whatsapp_number_id: string; template_id: string; variable_mappings: FaixaVariableMappingIn[] }
  ) => request<FaixaEnvio>(`/faixas/${faixaId}/envios`, { method: "POST", body: JSON.stringify(payload) }),
  atualizarEnvio: (
    faixaId: string,
    envioId: string,
    payload: {
      whatsapp_number_id: string;
      template_id: string;
      active: boolean;
      variable_mappings: FaixaVariableMappingIn[];
    }
  ) =>
    request<FaixaEnvio>(`/faixas/${faixaId}/envios/${envioId}`, {
      method: "PUT",
      body: JSON.stringify(payload),
    }),
  excluirEnvio: (faixaId: string, envioId: string) =>
    request<void>(`/faixas/${faixaId}/envios/${envioId}`, { method: "DELETE" }),
  updateDispatchConfig: (faixaId: string, envioId: string, payload: unknown) =>
    request(`/faixas/${faixaId}/envios/${envioId}/dispatch-config`, {
      method: "PUT",
      body: JSON.stringify(payload),
    }),
  getGlobalDispatchConfig: () => request<GlobalDispatchConfig>("/config/cobranca/disparo"),
  updateGlobalDispatchConfig: (payload: Omit<GlobalDispatchConfig, "leads_auto_extract_last_run">) =>
    request<GlobalDispatchConfig>("/config/cobranca/disparo", {
      method: "PUT",
      body: JSON.stringify(payload),
    }),
  dispatchNow: (id: string) => request(`/faixas/${id}/dispatch-now`, { method: "POST" }),
  excluirFaixa: (id: string) => request<void>(`/faixas/${id}`, { method: "DELETE" }),
  // Exige o mesmo Bearer token das outras rotas, então baixa como blob
  // autenticado em vez de um <a href> simples (que não manda o header).
  downloadSpreadsheetModel: (id: string, faixaName: string) =>
    downloadFile(`/faixas/${id}/spreadsheet-model`, `modelo_${faixaName || "planilha"}.xlsx`),

  uploadColumns: (faixaId: string, file: File) => {
    const form = new FormData();
    form.append("file", file);
    return request<UploadColumnsResult>(`/faixas/${faixaId}/uploads/columns`, {
      method: "POST",
      body: form,
    });
  },
  uploadPlanilha: (faixaId: string, file: File, mapping: UploadFieldMapping) => {
    const form = new FormData();
    form.append("file", file);
    form.append("mapping", JSON.stringify(mapping));
    return request<UploadResult>(`/faixas/${faixaId}/uploads`, { method: "POST", body: form });
  },
  importarValoresZerados: (
    faixaId: string,
    payload: {
      filename: string;
      mapping: UploadFieldMapping;
      linhas: { linha: number; dados: Record<string, string>; valor: string }[];
    }
  ) =>
    request<UploadResult>(`/faixas/${faixaId}/uploads/valores-zerados`, {
      method: "POST",
      body: JSON.stringify(payload),
    }),
  listQueue: (faixaId: string, params: { limit: number; offset: number } & OrdenacaoParams) =>
    request<{ total: number; itens: QueueItem[] }>(`/faixas/${faixaId}/queue?${montarQuery(params)}`),

  /** Ordem das colunas da tabela "Por faixa", salva na conta do usuário (vazia = padrão). */
  colunasPorFaixa: () => request<{ colunas: string[] }>("/dashboard/colunas-por-faixa"),
  salvarColunasPorFaixa: (colunas: string[]) =>
    request<{ colunas: string[] }>("/dashboard/colunas-por-faixa", { method: "PUT", body: JSON.stringify({ colunas }) }),
  janelaPagamento: (periodo: { de?: string; ate?: string }, signal?: AbortSignal) =>
    request<PagosJanela>(`/dashboard/janela-pagamento?${montarQuery(periodo)}`, { signal }),
  // auto=true: atualização automática da tela, o backend pode responder do cache compartilhado
  dashboardSummary: (periodo: { de?: string; ate?: string } = {}, auto = false, signal?: AbortSignal) =>
    request<DashboardSummary>(`/dashboard/summary?${montarQuery({ ...periodo, auto: auto || undefined })}`, { signal }),
  /** Cards da fila em tempo real: o backend manda os números a cada mudança. */
  painelTempoReal: (periodo: { de: string; ate: string }, aoReceber: (numeros: PainelTempoReal) => void) => {
    const url = new URL(`${API_URL}/dashboard/ws?${montarQuery(periodo)}`, window.location.href);
    url.protocol = url.protocol === "https:" ? "wss:" : "ws:";
    const ws = new WebSocket(url);
    // {} só mantém a conexão viva
    ws.onmessage = (e) => {
      const numeros = JSON.parse(e.data);
      if ("total_pendentes" in numeros) aoReceber(numeros);
    };
    return ws;
  },

  listInvalidPhones: (
    params: { faixa_id?: string; campanha?: string; de?: string; ate?: string; limit: number; offset: number } & OrdenacaoParams
  ) => request<{ total: number; itens: InvalidPhoneRecord[] }>(`/relatorios/telefones-invalidos?${montarQuery(params)}`),
  listDispatchReport: (
    params: { faixa_id?: string; campanha?: string; de?: string; ate?: string; limit: number; offset: number } & OrdenacaoParams
  ) =>
    request<{ total: number; itens: DispatchReportItem[] }>(`/relatorios/envios?${montarQuery(params)}`),

  // Exportações em Excel exigem o mesmo Bearer token das outras rotas, então
  // baixamos como blob autenticado em vez de um <a href> simples.
  downloadInvalidPhonesXlsx: (params: { faixa_id?: string; campanha?: string; de?: string; ate?: string }) =>
    downloadFile(`/relatorios/telefones-invalidos/export?${montarQuery(params)}`, "telefones_invalidos.xlsx"),
  downloadDispatchReportXlsx: (params: { faixa_id?: string; campanha?: string; de?: string; ate?: string }) =>
    downloadFile(`/relatorios/envios/export?${montarQuery(params)}`, "relatorio_envios.xlsx"),
  listPendentes: (
    params: { faixa_id?: string; campanha?: string; loja?: string; de?: string; ate?: string; limit: number; offset: number } & OrdenacaoParams
  ) => request<FilaReportPage>(`/relatorios/pendentes?${montarQuery(params)}`),
  downloadPendentesXlsx: (params: { faixa_id?: string; campanha?: string; loja?: string; de?: string; ate?: string }) =>
    downloadFile(`/relatorios/pendentes/export?${montarQuery(params)}`, "relatorio_pendentes.xlsx"),
  // --- Pausas de envio (aba Pendentes) ---
  listarPausas: () => request<PausaEnvio[]>("/pausas"),
  pausarEnvio: (dados: { escopo: EscopoPausa; valor: string; motivo: string; ate?: string }) =>
    request<PausaEnvio>("/pausas", { method: "POST", body: JSON.stringify(dados) }),
  opcoesPausaFila: () => request<OpcoesFila>("/pausas/opcoes-fila"),
  pausarLote: (dados: { escopo: "faixa" | "loja"; valores: string[]; motivo: string; ate?: string }) =>
    request<PausaEnvio[]>("/pausas/lote", { method: "POST", body: JSON.stringify(dados) }),
  reaplicarVariaveisFaixa: (faixaId: string) =>
    request<{ atualizados: number; sem_cadastro: number }>(
      `/pausas/faixa/${encodeURIComponent(faixaId)}/reaplicar-variaveis`,
      { method: "POST" }
    ),
  retomarEnvio: (id: string) => request<PausaEnvio>(`/pausas/${encodeURIComponent(id)}/retomar`, { method: "POST" }),
  previaPararEnvio: (escopo: EscopoPausa, valor: string) =>
    request<{ qtd: number }>(`/pausas/parar/previa?${montarQuery({ escopo, valor })}`),
  pararEnvio: (escopo: EscopoPausa, valor: string) =>
    request<{ qtd: number }>("/pausas/parar", { method: "POST", body: JSON.stringify({ escopo, valor }) }),
  previaDescartarPendentes: (filtros: FiltrosDescarte) =>
    request<{ qtd: number }>(`/relatorios/pendentes/descartar/previa?${montarQuery(filtros)}`),
  descartarPendentes: (filtros: FiltrosDescarte) =>
    request<{ qtd: number }>(`/relatorios/pendentes/descartar?${montarQuery(filtros)}`, { method: "POST" }),
  listErros: (
    params: { faixa_id?: string; campanha?: string; de?: string; ate?: string; limit: number; offset: number } & OrdenacaoParams
  ) => request<FilaReportPage>(`/relatorios/erros?${montarQuery(params)}`),
  downloadErrosXlsx: (params: { faixa_id?: string; campanha?: string; de?: string; ate?: string }) =>
    downloadFile(`/relatorios/erros/export?${montarQuery(params)}`, "relatorio_erros.xlsx"),
  listPagamentos: (params: FiltrosPagamentos & { limit: number; offset: number } & OrdenacaoParams, signal?: AbortSignal) =>
    request<PagamentosPage>(`/relatorios/pagamentos?${montarQuery(params)}`, { signal }),
  downloadPagamentosXlsx: (params: FiltrosPagamentos) =>
    downloadFile(`/relatorios/pagamentos/export?${montarQuery(params)}`, "relatorio_pagamentos.xlsx"),

  // --- Cobrança ---
  // /clientes, /relatorio e /leads/gerar consultam uma tabela do SETA com
  // dezenas de milhões de linhas, cacheada no Redis pelo backend — a primeira
  // vez com um filtro novo pode "processar" por alguns segundos/minutos;
  // pollAsync tenta de novo sozinho até vir pronto.
  exportarClientesCobranca: (params: FiltrosCobranca & OrdenacaoParams) =>
    downloadFile(`/cobranca/clientes/exportar.xlsx?${montarQuery(params)}`, "clientes_cobranca.xlsx"),
  regrasCobranca: () => request<RegrasCobranca>("/cobranca/regras"),
  atualizarComprasSeta: () =>
    request<{ clientes_atualizados: number }>("/cobranca/compras/atualizar", { method: "POST" }),
  listarClientesCobranca: (params: FiltrosCobranca & { limit: number; offset: number } & OrdenacaoParams, signal?: AbortSignal) =>
    pollAsync<{ total: number; itens: ClienteCobranca[] }>(
      (s) => request(`/cobranca/clientes?${montarQuery(params)}`, { signal: s }),
      signal
    ),
  relatorioCobranca: (params: FiltrosCobranca, signal?: AbortSignal) =>
    pollAsync<RelatorioCobranca>((s) => request(`/cobranca/relatorio?${montarQuery(params)}`, { signal: s }), signal),

  // --- Leads ---
  gerarLeads: (params: FiltrosCobranca, signal?: AbortSignal) =>
    pollAsync<{ criados: number; ja_existiam: number; sem_celular: number; na_fila: number }>(
      (s) => request(`/leads/gerar?${montarQuery(params)}`, { method: "POST", signal: s }),
      signal
    ),
  listarLeads: (params: FiltrosLeads & { limit: number; offset: number } & OrdenacaoParams) =>
    request<{ total: number; itens: Lead[] }>(`/leads?${montarQuery(params)}`),
  contarLeads: async (status: "novo" | "cobrado" | undefined, periodo: Partial<Pick<FiltrosLeads, "criado_de" | "criado_ate" | "enviado_de" | "enviado_ate">> = {}) =>
    (await request<{ total: number }>(`/leads?${montarQuery({ status, limit: 1, ...periodo })}`)).total,
  exportarLeads: (params: FiltrosLeads) =>
    downloadFile(`/leads/exportar.xlsx?${montarQuery(params)}`, "leads.xlsx"),
  enfileirarLeadsPendentes: () =>
    request<{ pendentes: number; na_fila: number }>("/leads/enfileirar-pendentes", { method: "POST" }),
  marcarLeadsCobrados: (ids: string[]) =>
    request<{ atualizados: number }>("/leads/marcar-cobrados", {
      method: "POST",
      body: JSON.stringify({ ids }),
    }),
  excluirLeads: (filtros: FiltrosLeads, ids: string[]) =>
    request<{ excluidos: number; ignorados_ja_enviados: number }>(`/leads/excluir?${montarQuery(filtros)}`, {
      method: "POST",
      body: JSON.stringify({ ids }),
    }),

  // --- Efetividade da cobrança ---
  relatorioEfetividade: (params: FiltrosEfetividade, signal?: AbortSignal) =>
    request<RelatorioEfetividade>(`/reports/efetividade?${montarQuery(params)}`, { signal }),
  exportarEfetividade: (params: FiltrosEfetividade) =>
    downloadFile(`/reports/efetividade.xlsx?${montarQuery(params)}`, "efetividade.xlsx"),
  exportarEfetividadeClientes: (params: FiltrosEfetividade) =>
    downloadFile(`/reports/efetividade/clientes.xlsx?${montarQuery(params)}`, "efetividade_clientes.xlsx"),

  // --- Blacklist ---
  listarBlacklist: (busca?: string) =>
    request<Bloqueado[]>(`/blacklist${busca ? `?busca=${encodeURIComponent(busca)}` : ""}`),
  adicionarBlacklist: (documento: string, motivo?: string) =>
    request<Bloqueado>("/blacklist", {
      method: "POST",
      body: JSON.stringify({ documento, motivo }),
    }),
  adicionarBlacklistLote: (documentos: string[], motivo?: string) =>
    request<{ adicionados: number; ja_existiam: number; invalidos: string[] }>("/blacklist/lote", {
      method: "POST",
      body: JSON.stringify({ documentos, motivo }),
    }),
  removerBlacklist: (id: string) =>
    request<void>(`/blacklist/${id}`, { method: "DELETE" }),

  // --- Lojas ---
  listarLojas: () => request<Loja[]>("/lojas"),
  filtrosLojas: () => request<FiltrosLoja>("/lojas/filtros"),
  criarLoja: (dados: LojaEditavel & { filial: string }) =>
    request<Loja>("/lojas", { method: "POST", body: JSON.stringify(dados) }),
  editarLoja: (filial: string, dados: LojaEditavel) =>
    request<Loja>(`/lojas/${encodeURIComponent(filial)}`, { method: "PUT", body: JSON.stringify(dados) }),
  excluirLoja: (filial: string) => request<void>(`/lojas/${encodeURIComponent(filial)}`, { method: "DELETE" }),
  sincronizarLojas: () =>
    request<{ novas: number; atualizadas: number; sem_mudanca: number }>("/lojas/sincronizar", { method: "POST" }),

  // --- Configurações ---
  statusSeta: () => request<StatusSeta>("/seta/status"),
  statusGoogle: () => request<StatusGoogle>("/google/status"),
  iniciarOAuthGoogle: () => request<{ url: string }>("/google/oauth/iniciar", { method: "POST" }),
  desconectarGoogle: () => request<void>("/google/oauth", { method: "DELETE" }),
  statusChatwoot: () => request<StatusChatwoot>("/chatwoot/status"),
  salvarConfigChatwoot: (payload: { base_url: string; account_id: string; api_access_token: string | null }) =>
    request<StatusChatwoot>("/chatwoot/config", { method: "PUT", body: JSON.stringify(payload) }),
  testarChatwoot: () => request<{ ok: boolean; detalhe: string }>("/chatwoot/testar", { method: "POST" }),

  // --- Remarketing de clientes do Renegocie ---
  conexaoRenegocie: () => request<ConexaoRenegocie>("/remarketing/conexao"),
  salvarConexaoRenegocie: (payload: { base_url: string; chave: string | null }) =>
    request<ConexaoRenegocie>("/remarketing/conexao", { method: "PUT", body: JSON.stringify(payload) }),
  testarConexaoRenegocie: () => request<{ ok: boolean; detalhe: string }>("/remarketing/conexao/testar", { method: "POST" }),
  segmentosRemarketing: () => request<SegmentoRemarketing[]>("/remarketing/segmentos"),
  salvarSegmentoRemarketing: (segmento: string, payload: SegmentoRemarketingIn) =>
    request<SegmentoRemarketing>(`/remarketing/segmentos/${segmento}`, { method: "PUT", body: JSON.stringify(payload) }),
  previaRemarketing: (segmento: string, periodo: { de?: string; ate?: string } = {}) => {
    const params = new URLSearchParams();
    if (periodo.de) params.set("de", periodo.de);
    if (periodo.ate) params.set("ate", periodo.ate);
    const qs = params.toString();
    return request<PreviaRemarketing>(`/remarketing/segmentos/${segmento}/previa${qs ? `?${qs}` : ""}`, {
      method: "POST",
    });
  },
  // --- Campanhas ---
  listarCampanhas: (filtro: { periodo?: "criacao" | "envio"; de?: string; ate?: string; busca?: string } = {}) =>
    request<Campanha[]>(`/campanhas?${montarQuery(filtro)}`),
  listarCampanhasFixas: (filtro: { periodo?: "criacao" | "envio"; de?: string; ate?: string; busca?: string } = {}) =>
    request<CampanhaFixa[]>(`/campanhas/fixas?${montarQuery(filtro)}`),
  opcoesCampanhas: (enviado: { enviado_de?: string; enviado_ate?: string } = {}) =>
    request<OpcaoCampanha[]>(`/campanhas/opcoes?${montarQuery(enviado)}`),
  getCampanha: (id: string) => request<Campanha>(`/campanhas/${id}`),
  criarCampanha: (payload: CampanhaIn) =>
    request<Campanha>("/campanhas", { method: "POST", body: JSON.stringify(payload) }),
  salvarCampanha: (id: string, payload: CampanhaIn) =>
    request<Campanha>(`/campanhas/${id}`, { method: "PUT", body: JSON.stringify(payload) }),
  excluirCampanha: (id: string) => request<void>(`/campanhas/${id}`, { method: "DELETE" }),
  pausarCampanha: (id: string, dados: { motivo?: string; ate?: string | null } = {}) =>
    request<Campanha>(`/campanhas/${id}/pausar`, { method: "POST", body: JSON.stringify(dados) }),
  retomarCampanha: (id: string) => request<Campanha>(`/campanhas/${id}/retomar`, { method: "POST" }),
  pararCampanha: (id: string) =>
    request<Campanha & { cancelados: number }>(`/campanhas/${id}/parar`, { method: "POST" }),
  subirClientesCampanha: (id: string, file: File) => {
    const form = new FormData();
    form.append("file", file);
    return request<{ clientes: number; ignoradas: number; coluna: string; colunas: string[] }>(
      `/campanhas/${id}/clientes`,
      { method: "POST", body: form },
    );
  },
  removerClientesCampanha: (id: string) => request<void>(`/campanhas/${id}/clientes`, { method: "DELETE" }),
  previaCampanha: (id: string, params: { limit: number; offset: number } & OrdenacaoParams, signal?: AbortSignal) =>
    pollAsync<PreviaCampanha>((s) => request(`/campanhas/${id}/previa?${montarQuery(params)}`, { signal: s }), signal),
  executarCampanha: (id: string, signal?: AbortSignal) =>
    pollAsync<{ encontrados: number; na_fila: number }>(
      (s) => request(`/campanhas/${id}/executar`, { method: "POST", signal: s }),
      signal
    ),
  colunasPlanilhaLojas: (file: File) => {
    const form = new FormData();
    form.append("file", file);
    return request<ColunaPlanilha[]>("/lojas/colunas-planilha", { method: "POST", body: form });
  },
  lerPlanilhaLojas: (file: File, coluna: number) => {
    const form = new FormData();
    form.append("file", file);
    return request<{ lojas: string[]; nao_encontradas: string[] }>(`/lojas/ler-planilha?coluna=${coluna}`, {
      method: "POST",
      body: form,
    });
  },

  executarRemarketing: () =>
    request<Record<string, { encontrados: number; na_fila: number }>>("/remarketing/executar", { method: "POST" }),

  // --- Regras de cobrança (clusters, faixas de atraso, matriz do WhatsApp) ---
  getConfigCobranca: () => request<ConfigCobrancaOut>("/config/cobranca"),
  salvarClustersCobranca: (clusters: ClusterConfigIn[]) =>
    request<ConfigCobrancaOut>("/config/cobranca/clusters", { method: "PUT", body: JSON.stringify(clusters) }),
  salvarFaixasCobranca: (faixas: FaixaAtrasoConfigIn[]) =>
    request<ConfigCobrancaOut>("/config/cobranca/faixas", { method: "PUT", body: JSON.stringify(faixas) }),
  salvarMatrizCobranca: (celulas: CelulaMatriz[]) =>
    request<ConfigCobrancaOut>("/config/cobranca/matriz", { method: "PUT", body: JSON.stringify(celulas) }),
  // manda só os campos do card; o backend mantém os outros
  salvarParametrosCobranca: (p: Partial<ParametrosCobranca>) =>
    request<ConfigCobrancaOut>("/config/cobranca/parametros", { method: "PUT", body: JSON.stringify(p) }),

  // --- Orçamento (Tarefa 4) ---
  getOrcamento: (ano: number) => request<OrcamentoMes[]>(`/config/cobranca/orcamento?ano=${ano}`),
  salvarOrcamento: (ano: number, meses: { mes: number; valor_orcado: string }[]) =>
    request<OrcamentoMes[]>(`/config/cobranca/orcamento?ano=${ano}`, { method: "PUT", body: JSON.stringify(meses) }),
  getOrcamentoProgressao: (filtro: { ano?: number; mes?: number; de?: string; ate?: string }, auto = false) =>
    request<OrcamentoProgressao>(`/dashboard/orcamento-progressao?${montarQuery({ ...filtro, auto: auto || undefined })}`),
  exportarOrcamentoPorDia: (filtro: { ano?: number; mes?: number; de?: string; ate?: string }) =>
    downloadFile(`/dashboard/orcamento-progressao/exportar.xlsx?${montarQuery(filtro)}`, "orcamento_por_dia.xlsx"),
};

async function downloadFile(path: string, nomePadrao: string): Promise<void> {
  // Autentica pelo cookie httpOnly de sessão (ver comentário em `request`).
  const response = await fetch(`${API_URL}${path}`, { credentials: "include" });
  if (!response.ok) {
    const body = await response.json().catch(() => ({}));
    throw new ApiError(response.status, textoDoErro(body.detail) || `Erro ${response.status} ao baixar o arquivo`);
  }
  // O backend manda o nome do arquivo (ex. com as faixas e a data) no Content-Disposition
  const disposicao = response.headers.get("content-disposition") ?? "";
  const nome = /filename="?([^";]+)"?/i.exec(disposicao)?.[1] ?? nomePadrao;
  const blob = await response.blob();
  const url = URL.createObjectURL(blob);
  const link = document.createElement("a");
  link.href = url;
  link.download = nome;
  document.body.appendChild(link);
  link.click();
  link.remove();
  URL.revokeObjectURL(url);
}

export interface Usuario {
  id: string;
  email: string;
  is_admin: boolean;
  created_at: string;
}

export interface WhatsappNumber {
  id: string;
  waba_id: string;
  phone_number_id: string;
  display_phone_number: string;
  label: string;
  active: boolean;
  meta_token_id?: string | null;
  meta_token_nome?: string | null;
  chatwoot_inbox_id?: number | null;
}

export interface MetaToken {
  id: string;
  nome: string;
  ultimos4: string;
  waba_id: string | null;
  ativo: boolean;
  created_at: string;
  numeros_vinculados: number;
}

// Número que a Meta devolve para a WABA de um token
export interface NumeroMeta {
  phone_number_id: string;
  display_phone_number: string;
  verified_name: string | null;
  quality_rating: string | null;
  status: string | null;
  cadastrado: boolean;
  vinculado_a_este_token: boolean;
}

export interface MetaTokenTestResult {
  ok: boolean;
  detalhe: string;
}

export interface TemplateVariable {
  id: string;
  position: number;
  internal_name: string;
  campo_sugerido: string | null;
  exemplo: string | null;
}

export interface TemplateCreate {
  name: string;
  meta_template_name: string;
  category: "UTILITY" | "MARKETING";
  header_type: "none" | "image";
  body_text: string;
  waba_id?: string;
  variables: { position: number; internal_name: string; exemplo: string; campo_sugerido: string | null }[];
}

// Campo do cliente disponível pra mapear numa variável de template — "exemplo"
// é o valor de demonstração usado na pré-visualização.
export interface CampoCliente {
  campo: string;
  rotulo: string;
  exemplo: string;
}

/** Versão comprimida da imagem, esperando o usuário aprovar ou descartar. */
export interface ImagemPendente {
  token: string;
  url_previa: string;
  tamanho_original: number;
  tamanho_final: number;
  largura_original: number;
  altura_original: number;
  largura: number;
  altura: number;
  formato_original: string;
  formato_final: string;
  qualidade: number | null;
}

export interface TemplateImagemResultado {
  template: Template;
  /** null: a imagem coube no limite como veio e já está no template */
  pendente: ImagemPendente | null;
}

export interface Template {
  id: string;
  name: string;
  meta_template_name: string;
  language: string;
  category: string;
  header_type: "none" | "image";
  image_url: string | null;
  body_text: string;
  status: "draft" | "pending" | "approved" | "rejected";
  meta_status_raw: string | null;
  meta_template_id: string | null;
  waba_id: string | null;
  variables: TemplateVariable[];
}

export function formatarNomeTemplate(
  t: { name: string; waba_id?: string | null },
  numbers: WhatsappNumber[]
): string {
  if (!t.waba_id) return t.name;
  const tels = Array.from(
    new Set(
      numbers
        .filter((n) => n.waba_id === t.waba_id)
        .map((n) => (n.display_phone_number || n.phone_number_id || "").trim())
        .filter(Boolean)
    )
  );
  return `${t.name} ● ${t.waba_id} (${tels.join("; ")})`;
}

export interface FaixaVariableMapping {
  id: string;
  template_id: string;
  template_variable_id: string;
  fonte_tipo: "coluna" | "campo_cliente" | "expressao";
  column_name: string | null;
  expressao: string | null;
}

export interface FaixaVariableMappingIn {
  template_variable_id: string;
  fonte_tipo: "coluna" | "campo_cliente" | "expressao";
  column_name?: string | null;
  expressao?: string | null;
}

export interface DispatchConfig {
  interval_seconds: number;
  batch_size: number;
  active: boolean;
  last_run_at: string | null;
}

// Horário de disparo (dias/janela) é global — vale pra todo envio de toda
// faixa. A extração automática de leads (opcional) roda pouco antes do
// início da janela, pra evitar cobrar quem já pagou mais cedo no mesmo dia.
export interface GlobalDispatchConfig {
  schedule_days: string;
  schedule_start: string;
  schedule_end: string;
  leads_auto_extract: boolean;
  leads_auto_extract_minutos_antes: number;
  leads_auto_extract_last_run: string | null;
  interval_seconds: number;
  batch_size: number;
}

// Um par (número, template) atribuído a uma faixa, com disparo próprio —
// uma faixa pode ter vários, cada um cobrando em paralelo (números de WABAs
// diferentes), distribuindo os envios e sem cobrar o mesmo cliente duas vezes
// (a fila é compartilhada por faixa; cada item só é reservado por um envio).
export interface FaixaEnvio {
  id: string;
  whatsapp_number_id: string;
  whatsapp_number: WhatsappNumber;
  template_id: string;
  template: Template;
  active: boolean;
  created_at: string;
  dispatch_config: DispatchConfig | null;
}

export interface Faixa {
  id: string;
  name: string;
  active: boolean;
  created_at: string;
  envios: FaixaEnvio[];
  variable_mappings: FaixaVariableMapping[];
  upload_field_mapping: Partial<UploadFieldMapping>;
  /** "regua" = faixa de atraso; "campanha" e "remarketing" ficam na tela Campanhas. */
  tipo: TipoFaixa;
  // Faixas de remarketing do Renegocie: recebem clientes pelo agendador, nunca por planilha.
  remarketing_segmento: string | null;
  // Faixa de uma campanha (tela Campanhas): não é faixa de atraso.
  campanha_id: string | null;
  descricao: string | null;
}

/** Filtros da aba Pendentes que definem o que "Descartar fila" tira da fila. */
export interface FiltrosDescarte {
  faixa_id?: string;
  campanha?: string;
  loja?: string;
  de?: string;
  ate?: string;
}

/** Coluna de uma planilha subida, com exemplos, para o usuário escolher qual usar. */
export interface ColunaPlanilha {
  indice: number;
  nome: string;
  exemplos: string[];
}

export type TipoFaixa = "regua" | "campanha" | "remarketing";

export const ROTULO_TIPO_FAIXA: Record<TipoFaixa, string> = {
  regua: "Régua de atraso",
  campanha: "Campanhas",
  remarketing: "Remarketing do Renegocie",
};

export interface QueueItem {
  id: string;
  faixa_id: string;
  codigo_cliente: string;
  nome: string;
  cpf: string;
  valor: string | null;
  celular: string;
  status: "pending" | "reserved" | "sent" | "error" | "invalid_phone" | "cancelled";
  error_message: string | null;
  created_at: string;
  sent_at: string | null;
}

export interface UploadColumnsResult {
  columns: string[];
  sample_row: Record<string, string> | null;
}

export interface UploadFieldMapping {
  celular: string;
  codigo_cliente: string;
  nome: string;
  cpf: string;
  valor?: string | null;
  variables: Record<string, string>; // template_variable_id -> nome da coluna
}

export interface UploadResult {
  filename: string;
  row_count: number;
  accepted_count: number;
  rejected_count: number;
  invalid_phone_count: number;
  rejected_reasons: string[];
  valores_zerados: UploadValorZerado[];
}

export interface OpcaoValor {
  campo: string;
  rotulo: string;
  valor: string;
}

/** Linha com valor zerado: o usuário escolhe um valor do sistema ou descarta. */
export interface UploadValorZerado {
  linha: number;
  codigo_cliente: string;
  nome: string;
  dados: Record<string, string>;
  opcoes: OpcaoValor[];
}

export interface InvalidPhoneRecord {
  id: string;
  faixa_id: string;
  codigo_cliente: string;
  cpf: string;
  celular_original: string;
  celular_normalizado: string | null;
  motivo: string;
  created_at: string;
}

export interface DispatchReportItem {
  codigo_cliente: string;
  faixa: string;
  nome: string;
  lojas: string[];
  valor: string | null;
  telefone: string;
  enviado_em: string;
}

export interface FilaReportItem {
  id: string;
  codigo_cliente: string;
  nome: string;
  faixa_id: string;
  /** Faixa de atraso (régua); num item de campanha, a do cliente. */
  faixa: string | null;
  /** Campanha ou segmento de remarketing; null na régua. */
  campanha: string | null;
  valor: string | null;
  telefone: string;
  entrou_em: string;
  mensagem: string | null;
  quando: string | null;
  lojas: string[];
  pausado: boolean;
}

export interface FilaReportPage {
  total: number;
  itens: FilaReportItem[];
  total_pausados: number;
  total_sem_loja: number;
}

export interface OpcaoFila {
  valor: string;
  rotulo: string;
  qtd_pendentes: number;
  pausado: boolean;
}

export interface OpcoesFila {
  faixas: OpcaoFila[];
  lojas: OpcaoFila[];
}

export type EscopoPausa = "cliente" | "faixa" | "loja";

export interface PausaEnvio {
  id: string;
  escopo: EscopoPausa;
  valor: string;
  valor_legivel: string;
  motivo: string;
  ate: string | null;
  created_by: string | null;
  created_at: string;
  qtd_retidos: number;
}

export interface PagosJanela {
  qtd_cobrados: number;
  qtd_pagaram: number;
  percentual: string;
  valor_pago: string;
  qtd_em_maturacao: number;
  // null = qualquer data após a cobrança
  dias_janela: number | null;
}

export type PainelTempoReal = Pick<
  DashboardSummary,
  "total_pendentes" | "total_pausados" | "total_enviados" | "total_erros" | "total_telefones_invalidos"
>;

// Fechamentos do /dashboard/ws em que não adianta reconectar: período sem tempo real e sessão inválida
export const WS_SEM_RECONEXAO = [4000, 4401];

export interface DashboardSummary {
  total_pendentes: number;
  total_pausados: number;
  total_enviados: number;
  total_erros: number;
  total_telefones_invalidos: number;
  por_faixa: DashboardPorFaixa[];
  total_por_faixa: DashboardTotalPorFaixa;
}

// Linha de total de "Por faixa" no que não é soma da coluna: cada cliente (e
// cada pagamento) uma vez, mesmo cobrado em mais de uma faixa
export interface DashboardTotalPorFaixa {
  clientes_cobrados: number;
  enviados_cobrados: number;
  clientes_com_envio: number;
  pagaram: number;
  valor_pago: string;
}

export interface DashboardPorFaixa {
  faixa: string;
  faixa_id: string;
  pending: number;
  sent: number;
  error: number;
  clientes_cobrados: number;
  // só entre os clientes cobrados no período: mensagens enviadas no período
  // e quantos receberam alguma (base da Frequência)
  enviados_cobrados: number;
  clientes_com_envio: number;
  pagaram: number;
  valor_pago: string;
}

// --- Cobrança ---

export interface RegrasCobranca {
  clusters: string[];
  rotulos_cluster: Record<string, string>; // cluster -> "ESPECIAL (R$ 0 a <400)"
  faixas: string[];
  faixas_whatsapp: Record<string, string[]>; // cluster -> faixas que recebem WhatsApp
  primeiro_dia: Record<string, number>;
  faixas_compra: string[];
  faixas_so_campanhas?: string[]; // ex.: "Antecipado": só no filtro das campanhas
}

// --- Configuração da cobrança (clusters, faixas de atraso, matriz do WhatsApp) ---

export interface ClusterConfig {
  id: string;
  nome: string;
  valor_min: string;
}

export interface ClusterConfigIn {
  id?: string | null;
  nome: string;
  valor_min: string | number;
}

export interface FaixaAtrasoConfig {
  id: string;
  nome: string;
  dia_min: number;
  dia_max: number | null;
  so_campanhas?: boolean;
}

export interface FaixaAtrasoConfigIn {
  id?: string | null;
  nome: string;
  dia_min: number;
  dia_max: number | null;
}

export interface CelulaMatriz {
  cluster_id: string;
  faixa_id: string;
}

export interface ParametrosCobranca {
  juros_mes_percentual: string;
  multa_percentual: string;
  dias_min_juros: number;
  // janela do card de pagamentos do Dashboard; null = qualquer data após a cobrança
  dias_janela_dashboard: number | null;
}

export interface ConfigCobrancaOut {
  clusters: ClusterConfig[];
  faixas: FaixaAtrasoConfig[];
  matriz: CelulaMatriz[];
  parametros: ParametrosCobranca;
}

export interface OrcamentoMes {
  ano: number;
  mes: number;
  valor_orcado: string;
}

export interface OrcamentoProgressaoDia {
  data: string;
  gasto_acumulado_brl: string | null; // null = dia que ainda não aconteceu
  mensagens_acumuladas: number | null; // mensagens cobradas pela Meta até o dia
}

export interface OrcamentoProgressao {
  de: string;
  ate: string;
  valor_orcado: string;
  valor_gasto_brl: string | null;
  motivo_sem_gasto: string | null;
  avisos: { waba_id: string; numeros: string[]; motivo: string }[];
  gasto_por_numero: { numero: string; gasto_brl: string; qtd_mensagens: number }[];
  dias: OrcamentoProgressaoDia[];
}

export interface ClienteCobranca {
  codigo: string;
  nome: string;
  celular: string | null;
  celular_origem: string | null;
  cpfcnpj: string | null;
  status: string;
  status_descricao: string;
  loja_cadastro: string | null;
  salario: string | null;
  limite_rotativo: string | null;
  nascimento: string | null;
  cadastro: string | null;
  cluster: string;
  valor_pago: string;
  qtd_compras: number;
  faixa_compra: string | null;
  ultima_compra: string | null;
  faixa: string | null;
  dias_atraso: number;
  entra_whatsapp: boolean;
  qtd_titulos: number;
  valor_em_aberto: string;
  qtd_parcelas_cobranca: number;
  valor_cobrar: string;
  vencimento_mais_antigo: string;
  lojas: string[];
  portadores: string[];
  spc_restricao: "sim" | "nao" | "indeterminado";
  spc_data_consulta: string | null;
}

export interface MatrizDados<T> {
  celulas: Record<string, Record<string, T>>;
  total_por_cluster: Record<string, T>;
  total_por_faixa: Record<string, T>;
  total: T;
}

export interface RelatorioCobranca {
  clusters: string[];
  faixas: string[];
  quantidade: MatrizDados<number>;
  quantidade_com_restricao_spc: MatrizDados<number>;
  valor_em_aberto: MatrizDados<string>;
  // só parcelas já vencidas, original ou com multa/juros conforme o filtro
  valor_em_atraso: MatrizDados<string>;
  valor_em_atraso_com_juros: boolean;
}

export interface FiltrosCobranca {
  apenas_primeiro_dia?: boolean;
  somente_regra_whatsapp?: boolean;
  faixa?: string[];
  cluster?: string[];
  faixa_compra?: string[];
  loja?: string[];
  regional?: string[];
  estado?: string[];
  cluster_inad?: string[];
  cluster_populacao?: string[];
  cobradora?: string[];
  status_cliente?: string[];
  restricao_spc?: string[];
  vencimento_de?: string;
  vencimento_ate?: string;
  // Total das parcelas já vencidas, pelo valor original ou com multa e juros
  valor_atraso_min?: string;
  valor_atraso_max?: string;
  valor_atraso_com_juros?: boolean;
}

// --- Campanhas ---

export interface CampanhaIn {
  nome: string;
  /** "Envio automático": roda sozinha todo dia de disparo no período. */
  ativa: boolean;
  data_inicio: string | null;
  data_fim: string | null;
  fonte_valores: "seta" | "planilha";
  recontato_dias: number | null;
  filtros: FiltrosCobranca;
}

export interface Campanha extends CampanhaIn {
  id: string;
  faixa_id: string;
  clientes_total: number;
  clientes_arquivo: string | null;
  planilha_colunas: string[];
  envios_ativos: number;
  templates: string[];
  ultima_execucao: string | null;
  ultimo_resultado: { encontrados?: number; na_fila?: number };
  enviados: number;
  pendentes: number;
  erros: number;
  parada_em: string | null;
  /** Data final já passou (GMT-3): a campanha acabou. */
  finalizada: boolean;
  pausa: { id: string; motivo: string; ate: string | null; created_by: string | null; created_at: string } | null;
  created_at: string;
}

export interface PreviaCampanha {
  total_base: number;
  total: number;
  itens: {
    codigo: string;
    nome: string;
    celular: string | null;
    cluster: string;
    faixa: string | null;
    dias_atraso: number;
    valor_cobrar: string;
    valor_atraso_original: string;
    valor_atraso_juros: string;
    vencimento_mais_antigo: string;
    lojas: string[];
  }[];
}

// --- Leads ---

export interface Lead {
  id: string;
  codigo_cliente: string;
  nome: string;
  cpf: string | null;
  celular: string | null;
  celular_origem: string | null;
  cluster: string;
  faixa: string;
  faixa_compra: string | null;
  qtd_compras: number;
  dias_atraso: number;
  qtd_parcelas: number;
  valor_em_aberto: string;
  valor_cobrar: string;
  vencimento_mais_antigo: string;
  lojas: string[];
  portadores: string[];
  status_cliente: string;
  spc_restricao: string;
  spc_data_consulta: string | null;
  status: "novo" | "cobrado";
  cobrado_em: string | null;
  created_at: string;
}

/** Filtro "Campanha": "" = todas; "regua" = só faixas de atraso; ou o id da campanha. */
export interface OpcaoCampanha {
  id: string;
  nome: string;
  arquivada: boolean;
  /** Remarketing do Renegocie: campanha fixa, uma por segmento. */
  fixa: boolean;
}

/** Remarketing do Renegocie na lista de Campanhas (campanha fixa por segmento). */
export interface CampanhaFixa {
  id: string;
  nome: string;
  faixa_id: string;
  segmento: string;
  ativo: boolean;
  enviados: number;
  pendentes: number;
  erros: number;
  pausada: boolean;
}

export interface FiltrosLeads {
  loja?: string[];
  regional?: string[];
  estado?: string[];
  cluster_inad?: string[];
  cluster_populacao?: string[];
  cobradora?: string[];
  faixa?: string[];
  cluster?: string[];
  status?: "novo" | "cobrado";
  busca?: string;
  com_celular?: boolean;
  criado_de?: string;
  criado_ate?: string;
  enviado_de?: string;
  enviado_ate?: string;
  campanha?: string;
}

// --- Blacklist ---

export interface Bloqueado {
  id: string;
  tipo: "seta" | "cpf";
  valor: string;
  motivo: string;
  created_at: string;
}

// --- Lojas ---

export interface Loja {
  filial: string;
  nome_com_cod: string | null;
  regional: string | null;
  estado: string | null;
  cluster_cobradora: string | null;
  cluster_inad: string | null;
  cluster_populacao: string | null;
}

export type LojaEditavel = Omit<Loja, "filial">;

export interface FiltrosLoja {
  regionais: string[];
  estados: string[];
  clusters_inad: string[];
  cobradoras: string[];
  clusters_populacao: string[];
}

// --- Configurações ---

export interface StatusSeta {
  configurado: boolean;
  conectado: boolean;
  banco: string | null;
  usuario: string | null;
  versao: string | null;
  somente_leitura: boolean | null;
  latencia_ms: number | null;
  erro: string | null;
}

export interface StatusGoogle {
  configurado: boolean;
  conectado: boolean;
  email: string | null;
  redirect_uri: string;
}

export interface StatusChatwoot {
  configurado: boolean;
  base_url: string | null;
  account_id: string | null;
}

export interface ChatwootTestResult {
  ok: boolean;
  detalhe: string;
}

// --- Efetividade da cobrança ---

export interface LinhaEfetividade {
  qtd_envios: number;
  clientes_cobrados: number;
  valor_cobrado: string;
  clientes_pagaram: number;
  valor_pago: string;
  parcelas_cobradas: number;
  parcelas_pagas: number;
  parcelas_renegociadas: number;
  conversao_clientes: string; // razão 0–1
  recuperacao_valor: string; // razão 0–1
}

export interface LinhaEfetividadeFaixa extends LinhaEfetividade {
  faixa: string;
}

export interface LinhaEfetividadeLoja extends LinhaEfetividade {
  loja: string;
  loja_nome: string | null;
  regional: string | null;
  cluster_inad: string | null;
}

export interface LinhaEfetividadeCampanha extends LinhaEfetividade {
  campanha: string;
  campanha_id: string;
}

export interface RelatorioEfetividade {
  por_faixa: LinhaEfetividadeFaixa[];
  por_loja: LinhaEfetividadeLoja[];
  por_campanha: LinhaEfetividadeCampanha[];
  total: LinhaEfetividade;
  leads_sem_parcelas: number;
  dias_janela: number | null;
  valor_a_pagar_brl: string | null;
  // hora em que o SETA foi lido; desatualizado = dado de antes do prazo (recalculando ou SETA fora)
  gerado_em: string | null;
  desatualizado: boolean;
}

export interface FiltrosEfetividade extends OrdenacaoParams {
  cobrado_de?: string;
  cobrado_ate?: string;
  dias_janela?: number;
  faixa?: string[];
  cluster?: string[];
  loja?: string[];
  regional?: string[];
  estado?: string[];
  cluster_inad?: string[];
  cobradora?: string[];
  campanha?: string;
}

// --- Relatório de pagamentos por cliente ---
export interface FiltrosPagamentos {
  faixa?: string[];
  campanha?: string;
  cobrado_de?: string;
  cobrado_ate?: string;
  pago_de?: string;
  pago_ate?: string;
  dias_janela?: number;
  // "envios" = clientes cobrados do Dashboard (com mensagem enviada no período)
  base?: "envios";
}

export interface PagamentoCliente {
  codigo_cliente: string;
  nome: string;
  cpf: string | null;
  loja: string;
  faixa: string;
  data_cobranca: string;
  valor_cobrado: string;
  valor_pago: string;
  qtd_titulos_pagos: number;
  primeiro_pagamento: string | null;
  ultimo_pagamento: string | null;
}

export interface PagamentosPage {
  total: number;
  total_clientes: number;
  valor_cobrado: string;
  valor_pago: string;
  itens: PagamentoCliente[];
  gerado_em: string | null;
  desatualizado: boolean;
}

export interface ConexaoRenegocie {
  configurado: boolean;
  base_url: string | null;
}

export interface SegmentoRemarketingIn {
  ativo: boolean;
  janela_dias: number;
  recontato_dias: number;
  cobradoras: string[];
  faixas_atraso: string[];
  clusters: string[];
  valor_min: string | null;
  valor_max: string | null;
}

export interface SegmentoRemarketing extends SegmentoRemarketingIn {
  segmento: string;
  nome: string;
  descricao: string;
  faixa_id: string;
  faixa_nome: string;
  envios_ativos: number;
  ultima_execucao: string | null;
  ultimo_resultado: { encontrados?: number; na_fila?: number };
}

export interface PreviaRemarketing {
  total_renegocie: number;
  total: number;
  gerado_em: string;
  clientes: {
    codigo: string;
    nome: string;
    celular: string | null;
    faixa: string | null;
    dias_atraso: number;
    valor_cobrar: string;
    cluster: string;
    evento_em: string;
    proposta: string | null;
    referencia_seta: string | null;
    entrada_vencimento: string | null;
  }[];
}
