const API_URL = import.meta.env.VITE_API_URL || "http://localhost:8000";

function getToken(): string | null {
  return localStorage.getItem("token");
}

export class ApiError extends Error {
  status: number;

  constructor(status: number, message: string) {
    super(message);
    this.name = "ApiError";
    this.status = status;
  }
}

async function request<T>(path: string, options: RequestInit = {}): Promise<T> {
  const token = getToken();
  const headers: Record<string, string> = {
    ...(options.body && !(options.body instanceof FormData)
      ? { "Content-Type": "application/json" }
      : {}),
    ...(token ? { Authorization: `Bearer ${token}` } : {}),
    ...((options.headers as Record<string, string>) || {}),
  };

  const response = await fetch(`${API_URL}${path}`, { ...options, headers });
  if (response.status === 401) {
    if (path.startsWith("/auth/login") || !token) {
      const body = await response.json().catch(() => ({}));
      throw new ApiError(401, body.detail || "Email ou senha incorretos");
    }
    localStorage.removeItem("token");
    window.location.href = "/login";
    throw new ApiError(401, "Sessão expirada");
  }
  if (!response.ok) {
    const body = await response.json().catch(() => ({}));
    throw new ApiError(response.status, body.detail || `Erro ${response.status}`);
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
    return e.message.startsWith("ERP") ? e.message : `ERP SETA indisponível: ${e.message}`;
  }
  return e instanceof Error ? e.message : "Erro desconhecido";
}

// Gera query string com arrays como parâmetros repetidos (?a=1&a=2) e ignora vazios.
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
    request<{ access_token: string }>("/auth/login", {
      method: "POST",
      body: JSON.stringify({ email, password }),
    }),

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

  listarTokensMeta: () => request<MetaToken[]>("/meta-tokens"),
  criarTokenMeta: (payload: { nome: string; token: string; waba_id: string }) =>
    request<MetaToken>("/meta-tokens", { method: "POST", body: JSON.stringify(payload) }),
  atualizarTokenMeta: (id: string, payload: { nome?: string; ativo?: boolean; waba_id?: string }) =>
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
  createTemplate: (payload: unknown) =>
    request<Template>("/templates", { method: "POST", body: JSON.stringify(payload) }),
  syncTemplatesFromMeta: () => request<Template[]>("/templates/meta/sync", { method: "POST" }),
  refreshTemplateStatus: (id: string) =>
    request<Template>(`/templates/${id}/refresh-status`, { method: "POST" }),
  listCamposCliente: () => request<CampoCliente[]>("/templates/variaveis/campos"),
  atualizarVariavelTemplate: (templateId: string, variavelId: string, campoSugerido: string | null) =>
    request<TemplateVariable>(`/templates/${templateId}/variaveis/${variavelId}`, {
      method: "PATCH",
      body: JSON.stringify({ campo_sugerido: campoSugerido }),
    }),
  uploadTemplateImage: (id: string, file: File) => {
    const form = new FormData();
    form.append("file", file);
    return request<Template>(`/templates/${id}/image`, { method: "POST", body: form });
  },

  listFaixas: () => request<Faixa[]>("/faixas"),
  getFaixa: (id: string) => request<Faixa>(`/faixas/${id}`),
  createFaixa: (payload: unknown) =>
    request<Faixa>("/faixas", { method: "POST", body: JSON.stringify(payload) }),
  updateDispatchConfig: (id: string, payload: unknown) =>
    request(`/faixas/${id}/dispatch-config`, { method: "PUT", body: JSON.stringify(payload) }),
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
  listQueue: (faixaId: string) => request<QueueItem[]>(`/faixas/${faixaId}/queue`),

  dashboardSummary: () => request<DashboardSummary>("/dashboard/summary"),

  listInvalidPhones: (faixaId?: string) =>
    request<InvalidPhoneRecord[]>(`/relatorios/telefones-invalidos${faixaId ? `?faixa_id=${faixaId}` : ""}`),
  listDispatchReport: (faixaId?: string) =>
    request<DispatchReportItem[]>(`/relatorios/envios${faixaId ? `?faixa_id=${faixaId}` : ""}`),

  // Exportações em Excel exigem o mesmo Bearer token das outras rotas, então
  // baixamos como blob autenticado em vez de um <a href> simples.
  downloadInvalidPhonesXlsx: (faixaId?: string) =>
    downloadFile(`/relatorios/telefones-invalidos/export${faixaId ? `?faixa_id=${faixaId}` : ""}`, "telefones_invalidos.xlsx"),
  downloadDispatchReportXlsx: (faixaId?: string) =>
    downloadFile(`/relatorios/envios/export${faixaId ? `?faixa_id=${faixaId}` : ""}`, "relatorio_envios.xlsx"),

  // --- Cobrança ---
  regrasCobranca: () => request<RegrasCobranca>("/cobranca/regras"),
  listarClientesCobranca: (params: FiltrosCobranca & { limit: number; offset: number }) =>
    request<{ total: number; itens: ClienteCobranca[] }>(`/cobranca/clientes?${montarQuery(params)}`),
  relatorioCobranca: (params: FiltrosCobranca) =>
    request<RelatorioCobranca>(`/cobranca/relatorio?${montarQuery(params)}`),

  // --- Leads ---
  gerarLeads: (params: FiltrosCobranca) =>
    request<{ criados: number; ja_existiam: number; sem_celular: number }>(
      `/leads/gerar?${montarQuery(params)}`,
      { method: "POST" },
    ),
  listarLeads: (params: FiltrosLeads & { limit: number; offset: number }) =>
    request<{ total: number; itens: Lead[] }>(`/leads?${montarQuery(params)}`),
  contarLeads: async (status: "novo" | "cobrado") =>
    (await request<{ total: number }>(`/leads?${montarQuery({ status, limit: 1 })}`)).total,
  exportarLeads: (params: FiltrosLeads) =>
    downloadFile(`/leads/exportar.xlsx?${montarQuery(params)}`, "leads.xlsx"),
  marcarLeadsCobrados: (ids: string[]) =>
    request<{ atualizados: number }>("/leads/marcar-cobrados", {
      method: "POST",
      body: JSON.stringify({ ids }),
    }),

  // --- Efetividade da cobrança ---
  relatorioEfetividade: (params: FiltrosEfetividade) =>
    request<RelatorioEfetividade>(`/reports/efetividade?${montarQuery(params)}`),
  exportarEfetividade: (params: FiltrosEfetividade) =>
    downloadFile(`/reports/efetividade.xlsx?${montarQuery(params)}`, "efetividade.xlsx"),

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

  // --- Configurações ---
  statusSeta: () => request<StatusSeta>("/seta/status"),
  statusGoogle: () => request<StatusGoogle>("/google/status"),
  iniciarOAuthGoogle: () => request<{ url: string }>("/google/oauth/iniciar", { method: "POST" }),
  desconectarGoogle: () => request<void>("/google/oauth", { method: "DELETE" }),
};

async function downloadFile(path: string, nomePadrao: string): Promise<void> {
  const token = getToken();
  const response = await fetch(`${API_URL}${path}`, {
    headers: token ? { Authorization: `Bearer ${token}` } : {},
  });
  if (!response.ok) {
    const body = await response.json().catch(() => ({}));
    throw new ApiError(response.status, body.detail || `Erro ${response.status} ao baixar o arquivo`);
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
}

// Campo do cliente disponível pra mapear numa variável de template — "exemplo"
// é o valor de demonstração usado na pré-visualização.
export interface CampoCliente {
  campo: string;
  rotulo: string;
  exemplo: string;
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
  waba_id: string | null;
  variables: TemplateVariable[];
}

export interface FaixaVariableMapping {
  id: string;
  template_variable_id: string;
  column_name: string;
}

export interface DispatchConfig {
  interval_seconds: number;
  batch_size: number;
  schedule_days: string;
  schedule_start: string;
  schedule_end: string;
  active: boolean;
  last_run_at: string | null;
}

export interface Faixa {
  id: string;
  name: string;
  template_id: string;
  active: boolean;
  template: Template;
  variable_mappings: FaixaVariableMapping[];
  dispatch_config: DispatchConfig | null;
  upload_field_mapping: Partial<UploadFieldMapping>;
}

export interface QueueItem {
  id: string;
  faixa_id: string;
  codigo_cliente: string;
  nome: string;
  cpf: string;
  valor: string | null;
  celular: string;
  status: "pending" | "reserved" | "sent" | "error" | "invalid_phone";
  error_message: string | null;
  created_at: string;
  sent_at: string | null;
}

export interface UploadColumnsResult {
  columns: string[];
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
}

export interface InvalidPhoneRecord {
  id: string;
  faixa_id: string;
  codigo_cliente: string;
  celular_original: string;
  celular_normalizado: string | null;
  motivo: string;
  created_at: string;
}

export interface DispatchReportItem {
  codigo_cliente: string;
  faixa: string;
  nome: string;
  valor: string | null;
  telefone: string;
  enviado_em: string;
}

export interface DashboardSummary {
  total_pendentes: number;
  total_enviados: number;
  total_erros: number;
  total_telefones_invalidos: number;
  por_faixa: Record<string, unknown>[];
  erros_recentes: Record<string, unknown>[];
}

// --- Cobrança ---

export interface RegrasCobranca {
  clusters: string[];
  faixas: string[];
  faixas_whatsapp: Record<string, string[]>; // cluster -> faixas que recebem WhatsApp
  primeiro_dia: Record<string, number>;
  faixas_compra: string[];
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
  portador?: string[];
  status_cliente?: string[];
  restricao_spc?: string[];
  vencimento_de?: string;
  vencimento_ate?: string;
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

export interface FiltrosLeads {
  loja?: string[];
  regional?: string[];
  estado?: string[];
  cluster_inad?: string[];
  cluster_populacao?: string[];
  faixa?: string[];
  cluster?: string[];
  status?: "novo" | "cobrado";
  busca?: string;
  com_celular?: boolean;
  criado_de?: string;
  criado_ate?: string;
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
  cluster_inad: string | null;
  cluster_populacao: string | null;
}

export interface FiltrosLoja {
  regionais: string[];
  estados: string[];
  clusters_inad: string[];
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

// --- Efetividade da cobrança ---

export interface LinhaEfetividade {
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

export interface RelatorioEfetividade {
  por_faixa: LinhaEfetividadeFaixa[];
  por_loja: LinhaEfetividadeLoja[];
  total: LinhaEfetividade;
  leads_sem_parcelas: number;
  dias_janela: number | null;
}

export interface FiltrosEfetividade {
  cobrado_de?: string;
  cobrado_ate?: string;
  dias_janela?: number;
  faixa?: string[];
  cluster?: string[];
  loja?: string[];
  regional?: string[];
  estado?: string[];
  cluster_inad?: string[];
}
