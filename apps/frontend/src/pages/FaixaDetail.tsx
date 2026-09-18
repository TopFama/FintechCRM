import { useEffect, useState } from "react";
import { useParams } from "react-router-dom";
import { api, DispatchConfig, Faixa, QueueItem, UploadResult } from "../api";

export default function FaixaDetail() {
  const { id } = useParams<{ id: string }>();
  const [faixa, setFaixa] = useState<Faixa | null>(null);
  const [queue, setQueue] = useState<QueueItem[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [uploadResult, setUploadResult] = useState<UploadResult | null>(null);
  const [config, setConfig] = useState<DispatchConfig | null>(null);

  function load() {
    if (!id) return;
    api.getFaixa(id).then((f) => {
      setFaixa(f);
      setConfig(f.dispatch_config);
    }).catch((e) => setError(e.message));
    api.listQueue(id).then(setQueue).catch((e) => setError(e.message));
  }

  useEffect(load, [id]);

  async function handleUpload(file: File) {
    if (!id) return;
    setError(null);
    try {
      const result = await api.uploadPlanilha(id, file);
      setUploadResult(result);
      load();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Erro ao subir planilha");
    }
  }

  async function saveConfig() {
    if (!id || !config) return;
    setError(null);
    try {
      await api.updateDispatchConfig(id, config);
      load();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Erro ao salvar configuração");
    }
  }

  async function dispatchNow() {
    if (!id) return;
    setError(null);
    try {
      await api.dispatchNow(id);
      alert("Disparo agendado — o worker vai processar na próxima varredura.");
    } catch (err) {
      setError(err instanceof Error ? err.message : "Erro ao disparar agora");
    }
  }

  if (!faixa) return <p>Carregando...</p>;

  return (
    <div>
      <h2>Faixa: {faixa.name}</h2>
      {error && <div className="error-box">{error}</div>}

      <div className="card">
        <h3>1. Modelo de planilha e upload</h3>
        <p>
          <a href={id ? api.spreadsheetModelUrl(id) : "#"}>Baixar modelo (.csv) desta faixa</a>
        </p>
        <div className="field">
          <label>Subir planilha preenchida</label>
          <input
            type="file"
            accept=".csv,.xlsx"
            onChange={(e) => e.target.files && handleUpload(e.target.files[0])}
          />
        </div>
        {uploadResult && (
          <div>
            <p>
              {uploadResult.accepted_count} aceitos / {uploadResult.rejected_count} rejeitados de{" "}
              {uploadResult.row_count} linhas.
            </p>
            {uploadResult.rejected_reasons.length > 0 && (
              <ul style={{ fontSize: 13, color: "#991b1b" }}>
                {uploadResult.rejected_reasons.map((r, i) => (
                  <li key={i}>{r}</li>
                ))}
              </ul>
            )}
          </div>
        )}
      </div>

      <div className="card">
        <h3>2. Disparo e controles de execução</h3>
        {config && (
          <>
            <div className="field">
              <label>Intervalo entre rodadas de envio (segundos)</label>
              <input
                type="number"
                value={config.interval_seconds}
                onChange={(e) => setConfig({ ...config, interval_seconds: Number(e.target.value) })}
              />
            </div>
            <div className="field">
              <label>Quantas cobranças por rodada</label>
              <input
                type="number"
                value={config.batch_size}
                onChange={(e) => setConfig({ ...config, batch_size: Number(e.target.value) })}
              />
            </div>
            <div className="field">
              <label>Dias da semana (1=segunda ... 7=domingo, separados por vírgula)</label>
              <input
                value={config.schedule_days}
                onChange={(e) => setConfig({ ...config, schedule_days: e.target.value })}
              />
            </div>
            <div style={{ display: "flex", gap: 12 }}>
              <div className="field" style={{ flex: 1 }}>
                <label>Início</label>
                <input
                  value={config.schedule_start}
                  onChange={(e) => setConfig({ ...config, schedule_start: e.target.value })}
                />
              </div>
              <div className="field" style={{ flex: 1 }}>
                <label>Fim</label>
                <input
                  value={config.schedule_end}
                  onChange={(e) => setConfig({ ...config, schedule_end: e.target.value })}
                />
              </div>
            </div>
            <div className="field">
              <label>
                <input
                  type="checkbox"
                  style={{ width: "auto", marginRight: 6 }}
                  checked={config.active}
                  onChange={(e) => setConfig({ ...config, active: e.target.checked })}
                />
                Agendamento ativo
              </label>
            </div>
            <div style={{ display: "flex", gap: 8 }}>
              <button onClick={saveConfig}>Salvar configuração</button>
              <button className="secondary" onClick={dispatchNow}>
                Cobrar esta base agora
              </button>
            </div>
          </>
        )}
      </div>

      <div className="card">
        <h3>Fila desta faixa (últimos 500)</h3>
        <table>
          <thead>
            <tr>
              <th>Nome</th>
              <th>Celular</th>
              <th>Status</th>
              <th>Erro</th>
            </tr>
          </thead>
          <tbody>
            {queue.map((q) => (
              <tr key={q.id}>
                <td>{q.nome}</td>
                <td>{q.celular}</td>
                <td>
                  <span className={`badge ${q.status}`}>{q.status}</span>
                </td>
                <td style={{ fontSize: 12 }}>{q.error_message || "—"}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}
