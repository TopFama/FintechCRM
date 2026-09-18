import { FormEvent, useEffect, useState } from "react";
import { api, Template } from "../api";

export default function Templates() {
  const [templates, setTemplates] = useState<Template[]>([]);
  const [wabaId, setWabaId] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [showCreate, setShowCreate] = useState(false);
  const [form, setForm] = useState({
    name: "",
    meta_template_name: "",
    language: "pt_BR",
    category: "UTILITY",
    header_type: "none" as "none" | "image",
    body_text: "",
    waba_id: "",
    submit_to_meta: false,
  });

  function load() {
    api.listTemplates().then(setTemplates).catch((e) => setError(e.message));
  }

  useEffect(load, []);

  async function handleSync(e: FormEvent) {
    e.preventDefault();
    setError(null);
    try {
      await api.syncTemplatesFromMeta(wabaId);
      load();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Erro ao sincronizar com a Meta");
    }
  }

  function detectVariables(bodyText: string) {
    const matches = Array.from(bodyText.matchAll(/\{\{(\d+)\}\}/g)).map((m) => Number(m[1]));
    const positions = Array.from(new Set(matches)).sort((a, b) => a - b);
    return positions.map((position) => ({ position, internal_name: `variavel_${position}` }));
  }

  async function handleCreate(e: FormEvent) {
    e.preventDefault();
    setError(null);
    try {
      const variables = detectVariables(form.body_text);
      const payload = { ...form, variables };
      await api.createTemplate(payload);
      setShowCreate(false);
      setForm({
        name: "",
        meta_template_name: "",
        language: "pt_BR",
        category: "UTILITY",
        header_type: "none",
        body_text: "",
        waba_id: "",
        submit_to_meta: false,
      });
      load();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Erro ao criar template");
    }
  }

  async function handleRefreshStatus(id: string) {
    try {
      await api.refreshTemplateStatus(id);
      load();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Erro ao consultar status");
    }
  }

  async function handleImageUpload(id: string, file: File) {
    try {
      await api.uploadTemplateImage(id, file);
      load();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Erro ao subir imagem");
    }
  }

  return (
    <div>
      <h2>Templates</h2>
      {error && <div className="error-box">{error}</div>}

      <div className="card">
        <h3>Sincronizar templates aprovados da Meta</h3>
        <form onSubmit={handleSync} style={{ display: "flex", gap: 8, alignItems: "flex-end" }}>
          <div className="field" style={{ flex: 1, marginBottom: 0 }}>
            <label>WABA ID</label>
            <input value={wabaId} onChange={(e) => setWabaId(e.target.value)} required />
          </div>
          <button type="submit">Sincronizar</button>
        </form>
      </div>

      <div className="card">
        <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}>
          <h3>Novo template</h3>
          <button className="secondary" onClick={() => setShowCreate((v) => !v)}>
            {showCreate ? "Cancelar" : "Criar template"}
          </button>
        </div>
        {showCreate && (
          <form onSubmit={handleCreate}>
            <div className="field">
              <label>Nome interno</label>
              <input value={form.name} onChange={(e) => setForm({ ...form, name: e.target.value })} required />
            </div>
            <div className="field">
              <label>Nome do template na Meta (snake_case)</label>
              <input
                value={form.meta_template_name}
                onChange={(e) => setForm({ ...form, meta_template_name: e.target.value })}
                required
              />
            </div>
            <div className="field">
              <label>WABA ID</label>
              <input value={form.waba_id} onChange={(e) => setForm({ ...form, waba_id: e.target.value })} required />
            </div>
            <div className="field">
              <label>Idioma</label>
              <input value={form.language} onChange={(e) => setForm({ ...form, language: e.target.value })} />
            </div>
            <div className="field">
              <label>Categoria</label>
              <select value={form.category} onChange={(e) => setForm({ ...form, category: e.target.value })}>
                <option value="UTILITY">UTILITY</option>
                <option value="MARKETING">MARKETING</option>
                <option value="AUTHENTICATION">AUTHENTICATION</option>
              </select>
            </div>
            <div className="field">
              <label>Cabeçalho com imagem?</label>
              <select
                value={form.header_type}
                onChange={(e) => setForm({ ...form, header_type: e.target.value as "none" | "image" })}
              >
                <option value="none">Não</option>
                <option value="image">Sim</option>
              </select>
            </div>
            <div className="field">
              <label>Corpo do template (use {"{{1}}"}, {"{{2}}"}... para variáveis)</label>
              <textarea
                rows={4}
                value={form.body_text}
                onChange={(e) => setForm({ ...form, body_text: e.target.value })}
                required
              />
              <p style={{ fontSize: 12, color: "#64748b" }}>
                Variáveis detectadas: {detectVariables(form.body_text).map((v) => v.internal_name).join(", ") || "nenhuma"}
              </p>
            </div>
            <div className="field">
              <label>
                <input
                  type="checkbox"
                  style={{ width: "auto", marginRight: 6 }}
                  checked={form.submit_to_meta}
                  onChange={(e) => setForm({ ...form, submit_to_meta: e.target.checked })}
                />
                Enviar já para análise na Meta
              </label>
            </div>
            <button type="submit">Salvar template</button>
          </form>
        )}
      </div>

      <div className="card">
        <table>
          <thead>
            <tr>
              <th>Nome</th>
              <th>Template (Meta)</th>
              <th>Status</th>
              <th>Variáveis</th>
              <th>Imagem</th>
              <th></th>
            </tr>
          </thead>
          <tbody>
            {templates.map((t) => (
              <tr key={t.id}>
                <td>{t.name}</td>
                <td>{t.meta_template_name}</td>
                <td>
                  <span className={`badge ${t.status}`}>{t.status}</span>
                </td>
                <td>{t.variables.map((v) => v.internal_name).join(", ") || "—"}</td>
                <td>
                  {t.header_type === "image" ? (
                    t.image_url ? (
                      "enviada"
                    ) : (
                      <label style={{ cursor: "pointer", color: "#2563eb" }}>
                        subir
                        <input
                          type="file"
                          accept="image/*"
                          style={{ display: "none" }}
                          onChange={(e) => e.target.files && handleImageUpload(t.id, e.target.files[0])}
                        />
                      </label>
                    )
                  ) : (
                    "—"
                  )}
                </td>
                <td>
                  <button className="secondary" onClick={() => handleRefreshStatus(t.id)}>
                    Atualizar status
                  </button>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}
