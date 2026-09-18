import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { api, Faixa } from "../api";

export default function Faixas() {
  const [faixas, setFaixas] = useState<Faixa[]>([]);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    api.listFaixas().then(setFaixas).catch((e) => setError(e.message));
  }, []);

  return (
    <div>
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}>
        <h2>Faixas de cobrança</h2>
        <Link to="/faixas/nova">
          <button>Nova faixa</button>
        </Link>
      </div>
      {error && <div className="error-box">{error}</div>}

      <div className="card">
        <table>
          <thead>
            <tr>
              <th>Faixa</th>
              <th>Template</th>
              <th>Disparo</th>
              <th></th>
            </tr>
          </thead>
          <tbody>
            {faixas.map((f) => (
              <tr key={f.id}>
                <td>{f.name}</td>
                <td>{f.template?.name}</td>
                <td>{f.dispatch_config?.active ? "agendado" : "pausado"}</td>
                <td>
                  <Link to={`/faixas/${f.id}`}>abrir</Link>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}
