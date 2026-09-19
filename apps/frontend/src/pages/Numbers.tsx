import { FormEvent, useEffect, useState } from "react";
import { api, WhatsappNumber } from "../api";
import { IconAlert, IconPhone } from "../icons";

export default function Numbers() {
  const [numbers, setNumbers] = useState<WhatsappNumber[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);
  const [form, setForm] = useState({
    waba_id: "",
    phone_number_id: "",
    display_phone_number: "",
    label: "",
  });

  function load() {
    api.listNumbers().then(setNumbers).catch((e) => setError(e.message));
  }

  useEffect(load, []);

  async function handleSubmit(e: FormEvent) {
    e.preventDefault();
    setError(null);
    setSaving(true);
    try {
      await api.createNumber(form);
      setForm({ waba_id: "", phone_number_id: "", display_phone_number: "", label: "" });
      load();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Erro ao adicionar número");
    } finally {
      setSaving(false);
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

      <div className="card">
        <div className="card-header">
          <h3>Adicionar número</h3>
        </div>
        <form onSubmit={handleSubmit}>
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
              <input value={form.label} onChange={(e) => setForm({ ...form, label: e.target.value })} placeholder="ex. Cobrança SP" />
            </div>
          </div>
          <button type="submit" disabled={saving}>
            {saving ? "Adicionando..." : "Adicionar número"}
          </button>
        </form>
      </div>

      <div className="card">
        <div className="card-header">
          <h3>Números cadastrados</h3>
        </div>
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
                  <th>Ativo</th>
                </tr>
              </thead>
              <tbody>
                {numbers.map((n) => (
                  <tr key={n.id}>
                    <td className="cell-strong">{n.label || "—"}</td>
                    <td>{n.display_phone_number}</td>
                    <td className="text-muted">{n.phone_number_id}</td>
                    <td className="text-muted">{n.waba_id}</td>
                    <td>
                      <span className={`status-pill ${n.active ? "on" : "off"}`}>{n.active ? "Sim" : "Não"}</span>
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
