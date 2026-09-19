import { useEffect, useState } from "react";
import { api, DashboardSummary } from "../api";
import { IconAlert, IconBolt, IconCheckCircle, IconInbox, IconPhone } from "../icons";

export default function Dashboard() {
  const [summary, setSummary] = useState<DashboardSummary | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    api.dashboardSummary().then(setSummary).catch((e) => setError(e.message));
  }, []);

  if (error)
    return (
      <div className="error-box">
        <IconAlert width={16} height={16} />
        <span>{error}</span>
      </div>
    );
  if (!summary) return <div className="loading-state">Carregando dashboard...</div>;

  return (
    <div>
      <div className="page-header">
        <div>
          <h2>Dashboard</h2>
          <div className="subtitle">Visão geral da cobrança via WhatsApp</div>
        </div>
      </div>

      <div className="stat-grid">
        <div className="stat">
          <div className="stat-icon tone-primary">
            <IconInbox />
          </div>
          <div>
            <div className="value">{summary.total_pendentes}</div>
            <div className="label">Pendentes na fila</div>
          </div>
        </div>
        <div className="stat">
          <div className="stat-icon tone-success">
            <IconCheckCircle />
          </div>
          <div>
            <div className="value">{summary.total_enviados}</div>
            <div className="label">Cobrados (enviados)</div>
          </div>
        </div>
        <div className="stat">
          <div className="stat-icon tone-danger">
            <IconAlert />
          </div>
          <div>
            <div className="value">{summary.total_erros}</div>
            <div className="label">Erros de envio</div>
          </div>
        </div>
        <div className="stat">
          <div className="stat-icon tone-warning">
            <IconPhone />
          </div>
          <div>
            <div className="value">{summary.total_telefones_invalidos}</div>
            <div className="label">Telefones inválidos</div>
          </div>
        </div>
      </div>

      <div className="card">
        <div className="card-header">
          <h3>Por faixa</h3>
        </div>
        {summary.por_faixa.length === 0 ? (
          <div className="empty-state">
            <IconBolt width={28} height={28} />
            <div className="title">Nenhuma faixa com movimento ainda</div>
            <p>Crie uma faixa de cobrança e suba uma planilha para começar.</p>
          </div>
        ) : (
          <div className="table-wrap">
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
                    <td className="cell-strong">{String(row.faixa)}</td>
                    <td>{String(row.pending ?? 0)}</td>
                    <td>{String(row.sent ?? 0)}</td>
                    <td>{String(row.error ?? 0)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>

      <div className="card">
        <div className="card-header">
          <h3>Erros recentes</h3>
        </div>
        {summary.erros_recentes.length === 0 ? (
          <div className="empty-state">
            <IconCheckCircle width={28} height={28} />
            <div className="title">Sem erros recentes</div>
            <p>Tudo certo por aqui.</p>
          </div>
        ) : (
          <div className="table-wrap">
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
                    <td className="text-muted">{new Date(String(row.created_at)).toLocaleString("pt-BR")}</td>
                    <td>{String(row.message)}</td>
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
