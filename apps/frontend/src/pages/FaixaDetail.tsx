import { useEffect, useState } from "react";
import { Link, useParams } from "react-router-dom";
import { api, DispatchConfig, Faixa, QueueItem, UploadResult } from "../api";
import { IconAlert, IconBolt, IconCheckCircle, IconDownload, IconInbox, IconUpload } from "../icons";

export default function FaixaDetail() {
  const { id } = useParams<{ id: string }>();
  const [faixa, setFaixa] = useState<Faixa | null>(null);
  const [queue, setQueue] = useState<QueueItem[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [uploadResult, setUploadResult] = useState<UploadResult | null>(null);
  const [config, setConfig] = useState<DispatchConfig | null>(null);
  const [uploading, setUploading] = useState(false);
  const [savingConfig, setSavingConfig] = useState(false);
  const [dispatchMessage, setDispatchMessage] = useState<string | null>(null);

  function load() {
    if (!id) return;
    api
      .getFaixa(id)
      .then((f) => {
        setFaixa(f);
        setConfig(f.dispatch_config);
      })
      .catch((e) => setError(e.message));
    api.listQueue(id).then(setQueue).catch((e) => setError(e.message));
  }

  useEffect(load, [id]);

  async function handleUpload(file: File) {
    if (!id) return;
    setError(null);
    setUploading(true);
    try {
      const result = await api.uploadPlanilha(id, file);
      setUploadResult(result);
      load();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Erro ao subir planilha");
    } finally {
      setUploading(false);
    }
  }

  async function saveConfig() {
    if (!id || !config) return;
    setError(null);
    setSavingConfig(true);
    try {
      await api.updateDispatchConfig(id, config);
      load();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Erro ao salvar configuração");
    } finally {
      setSavingConfig(false);
    }
  }

  async function dispatchNow() {
    if (!id) return;
    setError(null);
    setDispatchMessage(null);
    try {
      await api.dispatchNow(id);
      setDispatchMessage("Disparo agendado — o worker vai processar na próxima varredura.");
    } catch (err) {
      setError(err instanceof Error ? err.message : "Erro ao disparar agora");
    }
  }

  if (!faixa) return <div className="loading-state">Carregando faixa...</div>;

  return (
    <div>
      <Link to="/faixas" className="back-link">
        ← Faixas de cobrança
      </Link>
      <div className="page-header">
        <div>
          <h2>{faixa.name}</h2>
          <div className="subtitle">Template: {faixa.template?.name}</div>
        </div>
        <span className={`status-pill ${config?.active ? "on" : "off"}`}>
          {config?.active ? "Agendado" : "Pausado"}
        </span>
      </div>

      {error && (
        <div className="error-box">
          <IconAlert width={16} height={16} />
          <span>{error}</span>
        </div>
      )}

      <div className="card">
        <div className="card-header">
          <h3>1. Modelo de planilha e upload</h3>
          <a href={id ? api.spreadsheetModelUrl(id) : "#"} style={{ display: "inline-flex", alignItems: "center", gap: 6, fontSize: 13, fontWeight: 600 }}>
            <IconDownload width={16} height={16} /> Baixar modelo (.csv)
          </a>
        </div>
        <p className="card-subtitle">
          Preencha o modelo com a base de clientes desta faixa e suba de volta abaixo. Telefones inválidos ou
          duplicados são identificados automaticamente.
        </p>
        <label className="dropzone">
          <input
            type="file"
            accept=".csv,.xlsx"
            onChange={(e) => e.target.files && handleUpload(e.target.files[0])}
          />
          <IconUpload width={26} height={26} />
          <div className="dz-title">{uploading ? "Enviando planilha..." : "Clique ou arraste a planilha aqui"}</div>
          <div className="dz-hint">.csv ou .xlsx</div>
        </label>
        {uploadResult && (
          <div className="upload-summary">
            <div className="item">
              <span className="num" style={{ color: "var(--color-success)" }}>
                {uploadResult.accepted_count}
              </span>
              aceitos
            </div>
            <div className="item">
              <span className="num" style={{ color: "var(--color-danger)" }}>
                {uploadResult.rejected_count}
              </span>
              rejeitados
            </div>
            <div className="item">
              <span className="num">{uploadResult.row_count}</span>
              linhas na planilha
            </div>
          </div>
        )}
        {uploadResult && uploadResult.rejected_reasons.length > 0 && (
          <ul style={{ fontSize: 13, color: "var(--color-danger)", marginTop: 10 }}>
            {uploadResult.rejected_reasons.map((r, i) => (
              <li key={i}>{r}</li>
            ))}
          </ul>
        )}
      </div>

      <div className="card">
        <div className="card-header">
          <h3>2. Disparo e controles de execução</h3>
        </div>
        {config && (
          <>
            <div className="form-row">
              <div className="field">
                <label>Intervalo entre rodadas (segundos)</label>
                <input
                  type="number"
                  value={config.interval_seconds}
                  onChange={(e) => setConfig({ ...config, interval_seconds: Number(e.target.value) })}
                />
              </div>
              <div className="field">
                <label>Cobranças por rodada</label>
                <input
                  type="number"
                  value={config.batch_size}
                  onChange={(e) => setConfig({ ...config, batch_size: Number(e.target.value) })}
                />
              </div>
            </div>
            <div className="field">
              <label>Dias da semana (1=segunda ... 7=domingo, separados por vírgula)</label>
              <input
                value={config.schedule_days}
                onChange={(e) => setConfig({ ...config, schedule_days: e.target.value })}
              />
            </div>
            <div className="form-row">
              <div className="field">
                <label>Início da janela</label>
                <input
                  value={config.schedule_start}
                  onChange={(e) => setConfig({ ...config, schedule_start: e.target.value })}
                />
              </div>
              <div className="field">
                <label>Fim da janela</label>
                <input
                  value={config.schedule_end}
                  onChange={(e) => setConfig({ ...config, schedule_end: e.target.value })}
                />
              </div>
            </div>
            <div className="field">
              <label className="checkbox-row">
                <input
                  type="checkbox"
                  checked={config.active}
                  onChange={(e) => setConfig({ ...config, active: e.target.checked })}
                />
                Agendamento ativo
              </label>
            </div>
            {dispatchMessage && (
              <div className="success-box">
                <IconCheckCircle width={16} height={16} />
                <span>{dispatchMessage}</span>
              </div>
            )}
            <div className="actions-row">
              <button onClick={saveConfig} disabled={savingConfig}>
                {savingConfig ? "Salvando..." : "Salvar configuração"}
              </button>
              <button className="secondary" onClick={dispatchNow}>
                <IconBolt width={16} height={16} /> Cobrar esta base agora
              </button>
            </div>
          </>
        )}
      </div>

      <div className="card">
        <div className="card-header">
          <h3>Fila desta faixa</h3>
          <span className="text-faint">últimos 500</span>
        </div>
        {queue.length === 0 ? (
          <div className="empty-state">
            <IconInbox width={28} height={28} />
            <div className="title">Fila vazia</div>
            <p>Suba uma planilha acima para adicionar clientes a esta faixa.</p>
          </div>
        ) : (
          <div className="table-wrap">
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
                    <td className="cell-strong">{q.nome}</td>
                    <td>{q.celular}</td>
                    <td>
                      <span className={`badge ${q.status}`}>{q.status}</span>
                    </td>
                    <td className="text-faint">{q.error_message || "—"}</td>
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
