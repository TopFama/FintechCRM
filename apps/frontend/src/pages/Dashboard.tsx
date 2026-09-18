import { useEffect, useState } from "react";
import { api, DashboardSummary } from "../api";

export default function Dashboard() {
  const [summary, setSummary] = useState<DashboardSummary | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    api.dashboardSummary().then(setSummary).catch((e) => setError(e.message));
  }, []);

  if (error) return <div className="error-box">{error}</div>;
  if (!summary) return <p>Carregando...</p>;

  return (
    <div>
      <h2>Dashboard</h2>
      <div className="stat-grid">
        <div className="stat">
          <div className="value">{summary.total_pendentes}</div>
          <div className="label">Pendentes na fila</div>
        </div>
        <div className="stat">
          <div className="value">{summary.total_enviados}</div>
          <div className="label">Cobrados (enviados)</div>
        </div>
        <div className="stat">
          <div className="value">{summary.total_erros}</div>
          <div className="label">Erros de envio</div>
        </div>
        <div className="stat">
          <div className="value">{summary.total_telefones_invalidos}</div>
          <div className="label">Telefones inválidos</div>
        </div>
      </div>

      <div className="card">
        <h3>Por faixa</h3>
        <table>
          <thead>
            <tr>
              <th>Faixa</th>
              <th>Pendente</th>
              <th>Enviado</th>
              <th>Erro</th>
            </tr>
          </thead>
          <tbody>
            {summary.por_faixa.map((row, i) => (
              <tr key={i}>
                <td>{String(row.faixa)}</td>
                <td>{String(row.pending ?? 0)}</td>
                <td>{String(row.sent ?? 0)}</td>
                <td>{String(row.error ?? 0)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      <div className="card">
        <h3>Erros recentes</h3>
        <table>
          <thead>
            <tr>
              <th>Quando</th>
              <th>Mensagem</th>
            </tr>
          </thead>
          <tbody>
            {summary.erros_recentes.map((row, i) => (
              <tr key={i}>
                <td>{new Date(String(row.created_at)).toLocaleString("pt-BR")}</td>
                <td>{String(row.message)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}
