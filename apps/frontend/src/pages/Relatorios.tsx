import { useEffect, useState } from "react";
import { api, DispatchReportItem, Faixa, InvalidPhoneRecord } from "../api";
import { IconAlert, IconCheckCircle, IconDownload, IconInbox } from "../icons";

type Tab = "invalidos" | "envios";

export default function Relatorios() {
  const [tab, setTab] = useState<Tab>("invalidos");
  const [faixas, setFaixas] = useState<Faixa[]>([]);
  const [faixaId, setFaixaId] = useState<string>("");
  const [invalidPhones, setInvalidPhones] = useState<InvalidPhoneRecord[]>([]);
  const [dispatchReport, setDispatchReport] = useState<DispatchReportItem[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [downloading, setDownloading] = useState(false);

  useEffect(() => {
    api.listFaixas().then(setFaixas).catch(() => undefined);
  }, []);

  function load() {
    setLoading(true);
    setError(null);
    const fid = faixaId || undefined;
    const request =
      tab === "invalidos" ? api.listInvalidPhones(fid).then(setInvalidPhones) : api.listDispatchReport(fid).then(setDispatchReport);
    request.catch((e) => setError(e.message)).finally(() => setLoading(false));
  }

  useEffect(load, [tab, faixaId]);

  async function handleDownload() {
    setDownloading(true);
    setError(null);
    try {
      if (tab === "invalidos") {
        await api.downloadInvalidPhonesXlsx(faixaId || undefined);
      } else {
        await api.downloadDispatchReportXlsx(faixaId || undefined);
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : "Erro ao baixar relatório");
    } finally {
      setDownloading(false);
    }
  }

  return (
    <div>
      <div className="page-header">
        <div>
          <h2>Relatórios</h2>
          <div className="subtitle">Telefones inválidos e cobranças já enviadas</div>
        </div>
      </div>

      {error && (
        <div className="error-box">
          <IconAlert width={16} height={16} />
          <span>{error}</span>
        </div>
      )}

      <div className="card">
        <div style={{ display: "flex", gap: 8, marginBottom: 18, flexWrap: "wrap" }}>
          <button className={tab === "invalidos" ? "" : "secondary"} onClick={() => setTab("invalidos")}>
            Telefones inválidos
          </button>
          <button className={tab === "envios" ? "" : "secondary"} onClick={() => setTab("envios")}>
            Envios realizados
          </button>
          <div style={{ marginLeft: "auto", display: "flex", gap: 8 }}>
            <select value={faixaId} onChange={(e) => setFaixaId(e.target.value)} style={{ minWidth: 180 }}>
              <option value="">Todas as faixas</option>
              {faixas.map((f) => (
                <option key={f.id} value={f.id}>
                  {f.name}
                </option>
              ))}
            </select>
            <button className="secondary" onClick={handleDownload} disabled={downloading}>
              <IconDownload width={16} height={16} /> {downloading ? "Baixando..." : "Baixar Excel"}
            </button>
          </div>
        </div>

        {loading ? (
          <div className="loading-state">Carregando...</div>
        ) : tab === "invalidos" ? (
          invalidPhones.length === 0 ? (
            <div className="empty-state">
              <IconCheckCircle width={28} height={28} />
              <div className="title">Nenhum telefone inválido</div>
              <p>Todos os telefones enviados nas planilhas passaram na validação.</p>
            </div>
          ) : (
            <div className="table-wrap">
              <table>
                <thead>
                  <tr>
                    <th>Código do cliente</th>
                    <th>Telefone informado</th>
                    <th>Normalizado</th>
                    <th>Motivo</th>
                    <th>Quando</th>
                  </tr>
                </thead>
                <tbody>
                  {invalidPhones.map((r) => (
                    <tr key={r.id}>
                      <td className="cell-strong">{r.codigo_cliente}</td>
                      <td>{r.celular_original}</td>
                      <td className="text-muted">{r.celular_normalizado || "—"}</td>
                      <td className="text-muted">{r.motivo}</td>
                      <td className="text-faint">{new Date(r.created_at).toLocaleString("pt-BR")}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )
        ) : dispatchReport.length === 0 ? (
          <div className="empty-state">
            <IconInbox width={28} height={28} />
            <div className="title">Nenhum envio realizado ainda</div>
            <p>Assim que uma cobrança for enviada, ela aparece aqui.</p>
          </div>
        ) : (
          <div className="table-wrap">
            <table>
              <thead>
                <tr>
                  <th>Código do cliente</th>
                  <th>Faixa de atraso</th>
                  <th>Nome</th>
                  <th>Valor cobrado</th>
                  <th>Telefone que cobrou</th>
                  <th>Data/hora</th>
                </tr>
              </thead>
              <tbody>
                {dispatchReport.map((r, i) => (
                  <tr key={i}>
                    <td className="cell-strong">{r.codigo_cliente}</td>
                    <td>{r.faixa}</td>
                    <td>{r.nome || "—"}</td>
                    <td>{r.valor || "—"}</td>
                    <td className="text-muted">{r.telefone}</td>
                    <td className="text-faint">{new Date(r.enviado_em).toLocaleString("pt-BR")}</td>
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
