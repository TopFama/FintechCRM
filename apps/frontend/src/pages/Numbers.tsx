import { FormEvent, useEffect, useState } from "react";
import { api, WhatsappNumber } from "../api";

export default function Numbers() {
  const [numbers, setNumbers] = useState<WhatsappNumber[]>([]);
  const [error, setError] = useState<string | null>(null);
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
    try {
      await api.createNumber(form);
      setForm({ waba_id: "", phone_number_id: "", display_phone_number: "", label: "" });
      load();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Erro ao adicionar número");
    }
  }

  return (
    <div>
      <h2>Números de WhatsApp</h2>
      <p style={{ color: "#64748b" }}>
        Cadastre aqui os números conectados à API da Meta (WABA ID + phone number ID). Esses números
        ficam disponíveis para associar a faixas de cobrança.
      </p>

      <div className="card">
        <h3>Adicionar número</h3>
        {error && <div className="error-box">{error}</div>}
        <form onSubmit={handleSubmit}>
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
            <input value={form.label} onChange={(e) => setForm({ ...form, label: e.target.value })} />
          </div>
          <button type="submit">Adicionar número</button>
        </form>
      </div>

      <div className="card">
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
                <td>{n.label || "—"}</td>
                <td>{n.display_phone_number}</td>
                <td>{n.phone_number_id}</td>
                <td>{n.waba_id}</td>
                <td>{n.active ? "Sim" : "Não"}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}
