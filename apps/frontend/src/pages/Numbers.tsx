import { FormEvent, useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { api, MetaToken, WhatsappNumber } from "../api";
import { IconAlert, IconPhone } from "../icons";

export default function Numbers() {
  const [numbers, setNumbers] = useState<WhatsappNumber[]>([]);
  const [tokens, setTokens] = useState<MetaToken[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);

  // Formulário de novo número
  const [form, setForm] = useState({
    waba_id: "",
    phone_number_id: "",
    display_phone_number: "",
    label: "",
    meta_token_id: "",
    chatwoot_inbox_id: "",
  });

  // Edição inline de número
  const [editingNumberId, setEditingNumberId] = useState<string | null>(null);
  const [editNumberForm, setEditNumberForm] = useState({
    label: "",
    active: true,
    meta_token_id: "",
    chatwoot_inbox_id: "",
  });
  const [savingEdit, setSavingEdit] = useState(false);
  const [editNumberError, setEditNumberError] = useState<string | null>(null);


  function load() {
    api.listNumbers().then(setNumbers).catch((e) => setError(e.message));
    api.listarTokensMeta().then(setTokens).catch((e) => setError(e.message));
  }

  useEffect(load, []);

  const activeTokens = tokens.filter((t) => t.ativo);

  async function handleSubmitNumber(e: FormEvent) {
    e.preventDefault();
    setError(null);
    setSaving(true);
    try {
      const payload: Partial<WhatsappNumber> = {
        waba_id: form.waba_id.trim(),
        phone_number_id: form.phone_number_id.trim(),
        display_phone_number: form.display_phone_number.trim(),
        label: form.label.trim(),
        meta_token_id: form.meta_token_id ? form.meta_token_id : null,
        chatwoot_inbox_id: form.chatwoot_inbox_id ? parseInt(form.chatwoot_inbox_id, 10) : null,
      };
      await api.createNumber(payload);
      setForm({
        waba_id: "",
        phone_number_id: "",
        display_phone_number: "",
        label: "",
        meta_token_id: "",
        chatwoot_inbox_id: "",
      });
      load();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Erro ao adicionar número");
    } finally {
      setSaving(false);
    }
  }

  function handleStartEdit(n: WhatsappNumber) {
    setEditingNumberId(n.id);
    setEditNumberError(null);
    setEditNumberForm({
      label: n.label,
      active: n.active,
      meta_token_id: n.meta_token_id || "",
      chatwoot_inbox_id: n.chatwoot_inbox_id ? String(n.chatwoot_inbox_id) : "",
    });
  }

  function handleCancelEdit() {
    setEditingNumberId(null);
    setEditNumberError(null);
  }

  async function handleSaveEdit(numberId: string) {
    setEditNumberError(null);
    setSavingEdit(true);
    try {
      const payload = {
        label: editNumberForm.label.trim(),
        active: editNumberForm.active,
        meta_token_id: editNumberForm.meta_token_id ? editNumberForm.meta_token_id : null,
        chatwoot_inbox_id: editNumberForm.chatwoot_inbox_id
          ? parseInt(editNumberForm.chatwoot_inbox_id, 10)
          : null,
      };
      await api.atualizarNumero(numberId, payload);
      setEditingNumberId(null);
      load();
    } catch (err) {
      setEditNumberError(err instanceof Error ? err.message : "Erro ao atualizar número");
    } finally {
      setSavingEdit(false);
    }
  }


  return (
    <div>
      <div className="page-header">
        <div>
          <h2>Números de WhatsApp</h2>
          <div className="subtitle">
            Cadastre os números conectados à API da Meta (WABA ID + phone number ID) para associá-los a faixas
          </div>
        </div>
      </div>

      {error && (
        <div className="error-box">
          <IconAlert width={16} height={16} />
          <span>{error}</span>
        </div>
      )}

      {/* Card 1: Adicionar número */}
      <div className="card">
        <div className="card-header">
          <h3>Adicionar número</h3>
        </div>
        <form onSubmit={handleSubmitNumber}>
          <div className="form-row">
            <div className="field">
              <label>WABA ID</label>
              <input
                value={form.waba_id}
                onChange={(e) => setForm({ ...form, waba_id: e.target.value })}
                required
              />
            </div>
            <div className="field">
              <label>Phone Number ID (Meta)</label>
              <input
                value={form.phone_number_id}
                onChange={(e) => setForm({ ...form, phone_number_id: e.target.value })}
                required
              />
            </div>
          </div>
          <div className="form-row">
            <div className="field">
              <label>Número exibido</label>
              <input
                value={form.display_phone_number}
                onChange={(e) => setForm({ ...form, display_phone_number: e.target.value })}
                placeholder="+55 63 9202-1519"
                required
              />
            </div>
            <div className="field">
              <label>Apelido (opcional)</label>
              <input
                value={form.label}
                onChange={(e) => setForm({ ...form, label: e.target.value })}
                placeholder="ex. Cobrança SP"
              />
            </div>
          </div>
          <div className="form-row">
            <div className="field">
              <label>Token da Meta</label>
              <select
                value={form.meta_token_id}
                onChange={(e) => setForm({ ...form, meta_token_id: e.target.value })}
              >
                <option value="">Usar o token de outro número da mesma WABA</option>
                {activeTokens.map((t) => (
                  <option key={t.id} value={t.id}>
                    {t.nome} (…{t.ultimos4})
                  </option>
                ))}
              </select>
              <div className="field-hint">
                {activeTokens.length === 0 ? "Nenhum token ativo: cadastre" : "Os tokens são cadastrados"} em{" "}
                <Link to="/configuracoes">Configurações → Tokens da Meta</Link>.
              </div>
            </div>
            <div className="field">
              <label>ID da inbox do Chatwoot (opcional)</label>
              <input
                type="number"
                min="1"
                step="1"
                value={form.chatwoot_inbox_id}
                onChange={(e) => setForm({ ...form, chatwoot_inbox_id: e.target.value })}
                placeholder="ex. 12"
              />
            </div>
          </div>
          <button type="submit" disabled={saving}>
            {saving ? "Adicionando..." : "Adicionar número"}
          </button>
        </form>
      </div>

      {/* Card 2: Números cadastrados */}
      <div className="card">
        <div className="card-header">
          <h3>Números cadastrados</h3>
        </div>

        {editNumberError && (
          <div className="error-box" style={{ marginBottom: 16 }}>
            <IconAlert width={16} height={16} />
            <span>{editNumberError}</span>
          </div>
        )}

        {numbers.length === 0 ? (
          <div className="empty-state">
            <IconPhone width={28} height={28} />
            <div className="title">Nenhum número cadastrado</div>
            <p>Adicione um número acima para poder usá-lo em uma faixa de cobrança.</p>
          </div>
        ) : (
          <div className="table-wrap">
            <table>
              <thead>
                <tr>
                  <th>Apelido</th>
                  <th>Número</th>
                  <th>Phone Number ID</th>
                  <th>WABA ID</th>
                  <th>Token</th>
                  <th>Inbox Chatwoot</th>
                  <th>Ativo</th>
                  <th>Ações</th>
                </tr>
              </thead>
              <tbody>
                {numbers.map((n) => {
                  const isEditing = editingNumberId === n.id;
                  if (isEditing) {
                    return (
                      <tr key={n.id}>
                        <td>
                          <input
                            value={editNumberForm.label}
                            onChange={(e) =>
                              setEditNumberForm({ ...editNumberForm, label: e.target.value })
                            }
                            placeholder="Apelido"
                            style={{ minWidth: 100 }}
                          />
                        </td>
                        <td>{n.display_phone_number}</td>
                        <td className="text-muted">{n.phone_number_id}</td>
                        <td className="text-muted">{n.waba_id}</td>
                        <td>
                          <select
                            value={editNumberForm.meta_token_id}
                            onChange={(e) =>
                              setEditNumberForm({
                                ...editNumberForm,
                                meta_token_id: e.target.value,
                              })
                            }
                            style={{ minWidth: 160 }}
                          >
                            <option value="">Usar o token de outro número da mesma WABA</option>
                            {tokens
                              .filter((t) => t.ativo || t.id === n.meta_token_id)
                              .map((t) => (
                                <option key={t.id} value={t.id}>
                                  {t.nome} (…{t.ultimos4})
                                  {!t.ativo ? " (inativo)" : ""}
                                </option>
                              ))}
                          </select>
                        </td>
                        <td>
                          <input
                            type="number"
                            min="1"
                            step="1"
                            value={editNumberForm.chatwoot_inbox_id}
                            onChange={(e) =>
                              setEditNumberForm({
                                ...editNumberForm,
                                chatwoot_inbox_id: e.target.value,
                              })
                            }
                            placeholder="—"
                            style={{ width: 80 }}
                          />
                        </td>
                        <td>
                          <select
                            value={editNumberForm.active ? "true" : "false"}
                            onChange={(e) =>
                              setEditNumberForm({
                                ...editNumberForm,
                                active: e.target.value === "true",
                              })
                            }
                            style={{ width: 75 }}
                          >
                            <option value="true">Sim</option>
                            <option value="false">Não</option>
                          </select>
                        </td>
                        <td>
                          <div style={{ display: "flex", gap: "6px" }}>
                            <button
                              type="button"
                              className="small"
                              onClick={() => handleSaveEdit(n.id)}
                              disabled={savingEdit}
                            >
                              {savingEdit ? "Salvando..." : "Salvar"}
                            </button>
                            <button
                              type="button"
                              className="secondary small"
                              onClick={handleCancelEdit}
                              disabled={savingEdit}
                            >
                              Cancelar
                            </button>
                          </div>
                        </td>
                      </tr>
                    );
                  }

                  return (
                    <tr key={n.id}>
                      <td className="cell-strong">{n.label || "—"}</td>
                      <td>{n.display_phone_number}</td>
                      <td className="text-muted">{n.phone_number_id}</td>
                      <td className="text-muted">{n.waba_id}</td>
                      <td>{n.meta_token_nome || <span className="text-muted">da WABA</span>}</td>
                      <td>{n.chatwoot_inbox_id ?? "—"}</td>
                      <td>
                        <span className={`status-pill ${n.active ? "on" : "off"}`}>
                          {n.active ? "Sim" : "Não"}
                        </span>
                      </td>
                      <td>
                        <button
                          type="button"
                          className="secondary small"
                          onClick={() => handleStartEdit(n)}
                        >
                          Editar
                        </button>
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        )}
      </div>

    </div>
  );
}
