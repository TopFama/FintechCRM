import { useEffect, useState } from "react";
import { api, DispatchReportItem, Faixa, InvalidPhoneRecord } from "../api";
import Paginacao, { LIMIT_OPCOES_PADRAO } from "../components/Paginacao";
import SortableTh from "../components/SortableTh";
import { formatDataHora } from "../format";
import { IconAlert, IconCheckCircle, IconDownload, IconInbox } from "../icons";
import { ordemFaixaFn, ordenarPor, useSort } from "../sort";

type Tab = "invalidos" | "envios";
type ColunaInvalido = "codigo_cliente" | "celular_original" | "celular_normalizado" | "motivo" | "created_at";
type ColunaEnvio = "codigo_cliente" | "faixa" | "nome" | "valor" | "telefone" | "enviado_em";

export default function Relatorios() {
  const [tab, setTab] = useState<Tab>("invalidos");
  const [faixas, setFaixas] = useState<Faixa[]>([]);
  const [faixaId, setFaixaId] = useState<string>("");
  const [nomesFaixa, setNomesFaixa] = useState<string[]>([]);
  const [invalidPhones, setInvalidPhones] = useState<InvalidPhoneRecord[]>([]);
  const [invalidTotal, setInvalidTotal] = useState(0);
  const [dispatchReport, setDispatchReport] = useState<DispatchReportItem[]>([]);
  const [dispatchTotal, setDispatchTotal] = useState(0);
  const [offset, setOffset] = useState(0);
  const [limit, setLimit] = useState(LIMIT_OPCOES_PADRAO[1]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [downloading, setDownloading] = useState(false);
  const invalidosSort = useSort<ColunaInvalido>();
  const enviosSort = useSort<ColunaEnvio>();
  const ordemFaixa = ordemFaixaFn(nomesFaixa);

  useEffect(() => {
    api.listFaixas().then(setFaixas).catch(() => undefined);
    api.regrasCobranca().then((r) => setNomesFaixa(r.faixas)).catch(() => undefined);
  }, []);

  const invalidPhonesOrdenado = ordenarPor(
    invalidPhones,
    invalidosSort.sortKey ? (r: InvalidPhoneRecord) => r[invalidosSort.sortKey as ColunaInvalido] : null,
    invalidosSort.sortDir
  );
  const dispatchReportOrdenado = ordenarPor(
    dispatchReport,
    enviosSort.sortKey === "faixa"
      ? (r: DispatchReportItem) => ordemFaixa(r.faixa)
      : enviosSort.sortKey === "valor"
      ? (r: DispatchReportItem) => (r.valor != null ? Number(r.valor) : null)
      : enviosSort.sortKey
      ? (r: DispatchReportItem) => r[enviosSort.sortKey as ColunaEnvio]
      : null,
    enviosSort.sortDir
  );

  function load(novoOffset: number = offset, novoLimit: number = limit) {
    setLoading(true);
    setError(null);
    const params = { faixa_id: faixaId || undefined, limit: novoLimit, offset: novoOffset };
    const request =
      tab === "invalidos"
        ? api.listInvalidPhones(params).then((r) => {
            setInvalidPhones(r.itens);
            setInvalidTotal(r.total);
          })
        : api.listDispatchReport(params).then((r) => {
            setDispatchReport(r.itens);
            setDispatchTotal(r.total);
          });
    request.catch((e) => setError(e.message)).finally(() => setLoading(false));
  }

  useEffect(() => {
    setOffset(0);
    load(0, limit);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [tab, faixaId]);

  function mudarPagina(novoOffset: number) {
    setOffset(novoOffset);
    load(novoOffset, limit);
  }

  function mudarLimite(novoLimit: number) {
    setLimit(novoLimit);
    setOffset(0);
    load(0, novoLimit);
  }

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
                    {(
                      [
                        ["codigo_cliente", "Código do cliente"],
                        ["celular_original", "Telefone informado"],
                        ["celular_normalizado", "Normalizado"],
                        ["motivo", "Motivo"],
                        ["created_at", "Quando"],
                      ] as [ColunaInvalido, string][]
                    ).map(([coluna, rotulo]) => (
                      <SortableTh
                        key={coluna}
                        active={invalidosSort.sortKey === coluna}
                        dir={invalidosSort.sortDir}
                        onSort={() => invalidosSort.toggleSort(coluna)}
                      >
                        {rotulo}
                      </SortableTh>
                    ))}
                  </tr>
                </thead>
                <tbody>
                  {invalidPhonesOrdenado.map((r) => (
                    <tr key={r.id}>
                      <td className="cell-strong">{r.codigo_cliente}</td>
                      <td>{r.celular_original}</td>
                      <td className="text-muted">{r.celular_normalizado || "—"}</td>
                      <td className="text-muted">{r.motivo}</td>
                      <td className="text-faint">{formatDataHora(r.created_at)}</td>
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
                  {(
                    [
                      ["codigo_cliente", "Código do cliente"],
                      ["faixa", "Faixa de atraso"],
                      ["nome", "Nome"],
                      ["valor", "Valor cobrado"],
                      ["telefone", "Telefone que cobrou"],
                      ["enviado_em", "Data/hora"],
                    ] as [ColunaEnvio, string][]
                  ).map(([coluna, rotulo]) => (
                    <SortableTh
                      key={coluna}
                      active={enviosSort.sortKey === coluna}
                      dir={enviosSort.sortDir}
                      onSort={() => enviosSort.toggleSort(coluna)}
                    >
                      {rotulo}
                    </SortableTh>
                  ))}
                </tr>
              </thead>
              <tbody>
                {dispatchReportOrdenado.map((r, i) => (
                  <tr key={i}>
                    <td className="cell-strong">{r.codigo_cliente}</td>
                    <td>{r.faixa}</td>
                    <td>{r.nome || "—"}</td>
                    <td>{r.valor || "—"}</td>
                    <td className="text-muted">{r.telefone}</td>
                    <td className="text-faint">{formatDataHora(r.enviado_em)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
        {(tab === "invalidos" ? invalidTotal : dispatchTotal) > 0 && (
          <Paginacao
            total={tab === "invalidos" ? invalidTotal : dispatchTotal}
            limit={limit}
            offset={offset}
            onChange={mudarPagina}
            onLimitChange={mudarLimite}
          />
        )}
      </div>
    </div>
  );
}
