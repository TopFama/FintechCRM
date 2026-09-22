import { FormEvent, useEffect, useState } from "react";
import { api, MetaToken, WhatsappNumber } from "../api";
import { IconAlert, IconCheckCircle, IconPhone } from "../icons";

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

  // Formulário de novo token
  const [tokenForm, setTokenForm] = useState({
    nome: "",
    token: "",
  });
  const [savingToken, setSavingToken] = useState(false);
  const [tokenError, setTokenError] = useState<string | null>(null);

  // Resultados dos testes de token por ID
  const [testResults, setTestResults] = useState<
    Record<string, { ok: boolean; detalhe: string; loading?: boolean }>
  >({});

  function load() {
    api.listNumbers().then(setNumbers).catch((e) => setError(e.message));
    api.listarTokensMeta().then(setTokens).catch((e) => setTokenError(e.message));
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

  async function handleCreateToken(e: FormEvent) {
    e.preventDefault();
    setTokenError(null);
    setSavingToken(true);
    try {
      await api.criarTokenMeta({
        nome: tokenForm.nome.trim(),
        token: tokenForm.token.trim(),
      });
      setTokenForm({ nome: "", token: "" });
      load();
    } catch (err) {
      setTokenError(err instanceof Error ? err.message : "Erro ao cadastrar token");
    } finally {
      setSavingToken(false);
    }
  }

  async function handleToggleTokenAtivo(token: MetaToken) {
    setTokenError(null);
    try {
      await api.atualizarTokenMeta(token.id, { ativo: !token.ativo });
      load();
    } catch (err) {
      setTokenError(err instanceof Error ? err.message : "Erro ao alterar status do token");
    }
  }

  async function handleDeleteToken(token: MetaToken) {
    if (!window.confirm(`Deseja realmente excluir o token "${token.nome}"?`)) {
      return;
    }
    setTokenError(null);
    try {
      await api.excluirTokenMeta(token.id);
      load();
    } catch (err) {
      setTokenError(err instanceof Error ? err.message : "Erro ao excluir token");
    }
  }

  async function handleTestToken(tokenId: string) {
    setTestResults((prev) => ({
      ...prev,
      [tokenId]: { ok: false, detalhe: "Testando...", loading: true },
    }));
    try {
      const res = await api.testarTokenMeta(tokenId);
      setTestResults((prev) => ({
        ...prev,
        [tokenId]: { ok: res.ok, detalhe: res.detalhe, loading: false },
      }));
    } catch (err) {
      setTestResults((prev) => ({
        ...prev,
        [tokenId]: {
          ok: false,
          detalhe: err instanceof Error ? err.message : "Falha ao testar token",
          loading: false,
        },
      }));
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
                <option value="">Token padrão do servidor (.env)</option>
                {activeTokens.map((t) => (
                  <option key={t.id} value={t.id}>
                    {t.nome} (…{t.ultimos4})
                  </option>
                ))}
              </select>
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
                            <option value="">Token padrão do servidor (.env)</option>
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
                      <td>{n.meta_token_nome || "Padrão do servidor"}</td>
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

      {/* Card 3: Tokens da Meta */}
      <div className="card">
        <div className="card-header">
          <h3>Tokens da Meta</h3>
          <div className="card-subtitle">
            Gerencie múltiplos tokens de acesso da API oficial da Meta (Cloud API / WABA)
          </div>
        </div>

        {tokenError && (
          <div className="error-box" style={{ marginBottom: 16 }}>
            <IconAlert width={16} height={16} />
            <span>{tokenError}</span>
          </div>
        )}

        <form onSubmit={handleCreateToken} style={{ marginBottom: 24 }}>
          <div className="form-row">
            <div className="field">
              <label>Nome do token</label>
              <input
                value={tokenForm.nome}
                onChange={(e) => setTokenForm({ ...tokenForm, nome: e.target.value })}
                placeholder="ex. Token Cobrança SP"
                required
              />
            </div>
            <div className="field">
              <label>Token de acesso (Meta)</label>
              <input
                type="password"
                autoComplete="off"
                value={tokenForm.token}
                onChange={(e) => setTokenForm({ ...tokenForm, token: e.target.value })}
                placeholder="EAA..."
                required
              />
            </div>
          </div>
          <button type="submit" disabled={savingToken}>
            {savingToken ? "Cadastrando..." : "Cadastrar token"}
          </button>
        </form>

        {tokens.length === 0 ? (
          <div className="empty-state">
            <div className="title">Nenhum token cadastrado</div>
            <p>Cadastre um token de sistema da Meta para utilizá-lo nos números de WhatsApp.</p>
          </div>
        ) : (
          <div className="table-wrap">
            <table>
              <thead>
                <tr>
                  <th>Nome</th>
                  <th>Final</th>
                  <th>Ativo</th>
                  <th>Números vinculados</th>
                  <th>Ações</th>
                </tr>
              </thead>
              <tbody>
                {tokens.map((t) => {
                  const testRes = testResults[t.id];
                  return (
                    <tr key={t.id}>
                      <td className="cell-strong">{t.nome}</td>
                      <td className="text-muted">…{t.ultimos4}</td>
                      <td>
                        <span className={`status-pill ${t.ativo ? "on" : "off"}`}>
                          {t.ativo ? "Sim" : "Não"}
                        </span>
                      </td>
                      <td>{t.numeros_vinculados}</td>
                      <td>
                        <div
                          style={{
                            display: "flex",
                            gap: "6px",
                            alignItems: "center",
                            flexWrap: "wrap",
                          }}
                        >
                          <button
                            type="button"
                            className="secondary small"
                            onClick={() => handleTestToken(t.id)}
                            disabled={testRes?.loading}
                          >
                            {testRes?.loading ? "Testando..." : "Testar"}
                          </button>
                          <button
                            type="button"
                            className="secondary small"
                            onClick={() => handleToggleTokenAtivo(t)}
                          >
                            {t.ativo ? "Desativar" : "Ativar"}
                          </button>
                          <button
                            type="button"
                            className="danger small"
                            onClick={() => handleDeleteToken(t)}
                          >
                            Excluir
                          </button>
                        </div>
                        {testRes && !testRes.loading && (
                          <div
                            className={testRes.ok ? "success-box" : "error-box"}
                            style={{
                              marginTop: 8,
                              padding: "6px 10px",
                              fontSize: 12,
                              display: "flex",
                              alignItems: "center",
                              gap: 6,
                            }}
                          >
                            {testRes.ok ? (
                              <IconCheckCircle width={14} height={14} />
                            ) : (
                              <IconAlert width={14} height={14} />
                            )}
                            <span>{testRes.detalhe}</span>
                          </div>
                        )}
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
