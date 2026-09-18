const API_URL = import.meta.env.VITE_API_URL || "http://localhost:8000";

function getToken(): string | null {
  return localStorage.getItem("token");
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
    localStorage.removeItem("token");
    window.location.href = "/login";
    throw new Error("Sessão expirada");
  }
  if (!response.ok) {
    const body = await response.json().catch(() => ({}));
    throw new Error(body.detail || `Erro ${response.status}`);
  }
  if (response.headers.get("content-type")?.includes("application/json")) {
    return response.json();
  }
  return response as unknown as T;
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

  listTemplates: () => request<Template[]>("/templates"),
  createTemplate: (payload: unknown) =>
    request<Template>("/templates", { method: "POST", body: JSON.stringify(payload) }),
  syncTemplatesFromMeta: (wabaId: string) =>
    request<Template[]>(`/templates/meta/sync?waba_id=${encodeURIComponent(wabaId)}`),
  refreshTemplateStatus: (id: string) =>
    request<Template>(`/templates/${id}/refresh-status`, { method: "POST" }),
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
  spreadsheetModelUrl: (id: string) => `${API_URL}/faixas/${id}/spreadsheet-model`,

  uploadPlanilha: (faixaId: string, file: File) => {
    const form = new FormData();
    form.append("file", file);
    return request<UploadResult>(`/faixas/${faixaId}/uploads`, { method: "POST", body: form });
  },
  listQueue: (faixaId: string) => request<QueueItem[]>(`/faixas/${faixaId}/queue`),

  dashboardSummary: () => request<DashboardSummary>("/dashboard/summary"),
};

export interface WhatsappNumber {
  id: string;
  waba_id: string;
  phone_number_id: string;
  display_phone_number: string;
  label: string;
  active: boolean;
}

export interface TemplateVariable {
  id: string;
  position: number;
  internal_name: string;
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
}

export interface QueueItem {
  id: string;
  faixa_id: string;
  nome: string;
  celular: string;
  status: "pending" | "reserved" | "sent" | "error" | "invalid_phone";
  error_message: string | null;
  created_at: string;
  sent_at: string | null;
}

export interface UploadResult {
  filename: string;
  row_count: number;
  accepted_count: number;
  rejected_count: number;
  rejected_reasons: string[];
}

export interface DashboardSummary {
  total_pendentes: number;
  total_enviados: number;
  total_erros: number;
  total_telefones_invalidos: number;
  por_faixa: Record<string, unknown>[];
  erros_recentes: Record<string, unknown>[];
}
