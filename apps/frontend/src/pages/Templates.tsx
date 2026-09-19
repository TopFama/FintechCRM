import { FormEvent, useEffect, useMemo, useState } from "react";
import { api, Template, WhatsappNumber } from "../api";
import { IconAlert, IconPlus, IconTemplate } from "../icons";

export default function Templates() {
  const [templates, setTemplates] = useState<Template[]>([]);
  const [numbers, setNumbers] = useState<WhatsappNumber[]>([]);
  const [selectedWabaId, setSelectedWabaId] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [showCreate, setShowCreate] = useState(false);
  const [syncing, setSyncing] = useState(false);
  const [saving, setSaving] = useState(false);
  const [form, setForm] = useState({
    name: "",
    meta_template_name: "",
    language: "pt_BR",
    category: "UTILITY",
    header_type: "none" as "none" | "image",
    body_text: "",
    submit_to_meta: false,
  });

  const wabaIds = useMemo(
    () => Array.from(new Set(numbers.map((n) => n.waba_id))),
    [numbers]
  );

  function load() {
    api.listTemplates().then(setTemplates).catch((e) => setError(e.message));
    api.listNumbers().then(setNumbers).catch(() => undefined);
  }

  useEffect(load, []);

  async function handleSync() {
    setError(null);
    setSyncing(true);
    try {
      await api.syncTemplatesFromMeta();
      load();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Erro ao sincronizar com a Meta");
    } finally {
      setSyncing(false);
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
    setSaving(true);
    try {
      const variables = detectVariables(form.body_text);
      const payload = { ...form, variables, waba_id: wabaIds.length > 1 ? selectedWabaId : undefined };
      await api.createTemplate(payload);
      setShowCreate(false);
      setForm({
        name: "",
        meta_template_name: "",
        language: "pt_BR",
        category: "UTILITY",
        header_type: "none",
        body_text: "",
        submit_to_meta: false,
      });
      load();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Erro ao criar template");
    } finally {
      setSaving(false);
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
      <div className="page-header">
        <div>
          <h2>Templates</h2>
          <div className="subtitle">Templates de WhatsApp aprovados na Meta, usados pelas faixas de cobrança</div>
        </div>
      </div>

      {error && (
        <div className="error-box">
          <IconAlert width={16} height={16} />
          <span>{error}</span>
        </div>
      )}

      <div className="card">
        <div className="card-header">
          <h3>Sincronizar templates da Meta</h3>
        </div>
        <p className="card-subtitle">
          Puxa os templates já aprovados/pendentes direto da Meta para todos os números de WhatsApp já
          cadastrados na aba Números — não precisa mais informar o WABA ID na mão.
        </p>
        <button onClick={handleSync} disabled={syncing || numbers.length === 0}>
          {syncing ? "Sincronizando..." : "Sincronizar"}
        </button>
        {numbers.length === 0 && (
          <p className="field-hint">Cadastre um número de WhatsApp na aba Números antes de sincronizar.</p>
        )}
      </div>

      <div className="card">
        <div className="card-header">
          <h3>Novo template</h3>
          <button className="secondary" onClick={() => setShowCreate((v) => !v)}>
            {showCreate ? "Cancelar" : (
              <>
                <IconPlus width={16} height={16} /> Criar template
              </>
            )}
          </button>
        </div>
        {showCreate && (
          <form onSubmit={handleCreate}>
            <div className="form-row">
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
            </div>
            <div className="form-row">
              {wabaIds.length > 1 && (
                <div className="field">
                  <label>WABA</label>
                  <select value={selectedWabaId} onChange={(e) => setSelectedWabaId(e.target.value)} required>
                    <option value="">Selecione...</option>
                    {wabaIds.map((id) => (
                      <option key={id} value={id}>
                        {id}
                      </option>
                    ))}
                  </select>
                </div>
              )}
              <div className="field">
                <label>Idioma</label>
                <input value={form.language} onChange={(e) => setForm({ ...form, language: e.target.value })} />
              </div>
            </div>
            <div className="form-row">
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
            </div>
            <div className="field">
              <label>Corpo do template (use {"{{1}}"}, {"{{2}}"}... para variáveis)</label>
              <textarea
                rows={4}
                value={form.body_text}
                onChange={(e) => setForm({ ...form, body_text: e.target.value })}
                required
              />
              <p className="field-hint">
                Variáveis detectadas: {detectVariables(form.body_text).map((v) => v.internal_name).join(", ") || "nenhuma"}
              </p>
            </div>
            <div className="field">
              <label className="checkbox-row">
                <input
                  type="checkbox"
                  checked={form.submit_to_meta}
                  onChange={(e) => setForm({ ...form, submit_to_meta: e.target.checked })}
                />
                Enviar já para análise na Meta
              </label>
            </div>
            <button type="submit" disabled={saving}>
              {saving ? "Salvando..." : "Salvar template"}
            </button>
          </form>
        )}
      </div>

      <div className="card">
        <div className="card-header">
          <h3>Templates cadastrados</h3>
        </div>
        {templates.length === 0 ? (
          <div className="empty-state">
            <IconTemplate width={28} height={28} />
            <div className="title">Nenhum template cadastrado</div>
            <p>Sincronize com a Meta ou crie um template acima.</p>
          </div>
        ) : (
          <div className="table-wrap">
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
                    <td className="cell-strong">{t.name}</td>
                    <td className="text-muted">{t.meta_template_name}</td>
                    <td>
                      <span className={`badge ${t.status}`}>{t.status}</span>
                    </td>
                    <td className="text-muted">{t.variables.map((v) => v.internal_name).join(", ") || "—"}</td>
                    <td>
                      {t.header_type === "image" ? (
                        t.image_url ? (
                          <span className="badge sent">enviada</span>
                        ) : (
                          <label style={{ cursor: "pointer", color: "var(--color-primary)", fontWeight: 600 }}>
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
                        <span className="text-faint">—</span>
                      )}
                    </td>
                    <td>
                      <button className="secondary small" onClick={() => handleRefreshStatus(t.id)}>
                        Atualizar status
                      </button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>
    </div>
  );
}
