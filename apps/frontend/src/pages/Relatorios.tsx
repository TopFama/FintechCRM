import { useEffect, useRef, useState } from "react";
import { api, DispatchReportItem, Faixa, InvalidPhoneRecord, PagamentoCliente, PagamentosPage } from "../api";
import Paginacao, { LIMIT_OPCOES_PADRAO } from "../components/Paginacao";
import SortableTh from "../components/SortableTh";
import { formatBRL, formatData, formatDataHora } from "../format";
import { IconAlert, IconCheckCircle, IconDownload, IconInbox } from "../icons";
import { SortDirection, useSort } from "../sort";

type Tab = "invalidos" | "envios" | "pagamentos";
type ColunaInvalido = "codigo_cliente" | "celular_original" | "celular_normalizado" | "motivo" | "created_at";
type ColunaPagamento =
  | "codigo_cliente"
  | "nome"
  | "loja"
  | "faixa"
  | "data_cobranca"
  | "valor_cobrado"
  | "valor_pago"
  | "primeiro_pagamento";
type ColunaEnvio = "codigo_cliente" | "faixa" | "nome" | "valor" | "telefone" | "enviado_em";

export default function Relatorios() {
  const [tab, setTab] = useState<Tab>("invalidos");
  const [faixas, setFaixas] = useState<Faixa[]>([]);
  const [faixaId, setFaixaId] = useState<string>("");
  const [invalidPhones, setInvalidPhones] = useState<InvalidPhoneRecord[]>([]);
  const [invalidTotal, setInvalidTotal] = useState(0);
  const [dispatchReport, setDispatchReport] = useState<DispatchReportItem[]>([]);
  const [dispatchTotal, setDispatchTotal] = useState(0);
  const [offset, setOffset] = useState(0);
  const [limit, setLimit] = useState(LIMIT_OPCOES_PADRAO[1]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [downloading, setDownloading] = useState(false);
  const [cobradoDe, setCobradoDe] = useState("");
  const [cobradoAte, setCobradoAte] = useState("");
  const [pagoDe, setPagoDe] = useState("");
  const [pagoAte, setPagoAte] = useState("");
  const [pagamentos, setPagamentos] = useState<PagamentosPage | null>(null);
  const invalidosSort = useSort<ColunaInvalido>(null, (chave, dir) => {
    setOffset(0);
    load(0, limit, chave, dir);
  });
  const enviosSort = useSort<ColunaEnvio>(null, (chave, dir) => {
    setOffset(0);
    load(0, limit, chave, dir);
  });

  const pagamentosSort = useSort<ColunaPagamento>(null, (chave, dir) => {
    setOffset(0);
    load(0, limit, chave, dir);
  });

  useEffect(() => {
    api.listFaixas().then(setFaixas).catch(() => undefined);
  }, []);

  function sortAtual() {
    return tab === "invalidos" ? invalidosSort : tab === "pagamentos" ? pagamentosSort : enviosSort;
  }

  // Descarta resposta de consulta já substituída (ex.: data mínima preenchida
  // antes da máxima dispara duas consultas ao SETA e a primeira pode chegar por último)
  const reqRef = useRef(0);

  function load(
    novoOffset: number = offset,
    novoLimit: number = limit,
    sortBy: string | null = sortAtual().sortKey,
    sortDir: SortDirection = sortAtual().sortDir
  ) {
    setLoading(true);
    setError(null);
    const seq = ++reqRef.current;
    const atual = () => seq === reqRef.current;
    const params = {
      faixa_id: faixaId || undefined,
      de: cobradoDe || undefined,
      ate: cobradoAte || undefined,
      limit: novoLimit,
      offset: novoOffset,
      sort_by: sortBy ?? undefined,
      sort_dir: sortDir,
    };
    const request =
      tab === "pagamentos"
        ? api
            .listPagamentos({
              ...filtrosPagamentos(),
              limit: novoLimit,
              offset: novoOffset,
              sort_by: sortBy ?? undefined,
              sort_dir: sortDir,
            })
            .then((r) => atual() && setPagamentos(r))
        : tab === "invalidos"
        ? api.listInvalidPhones(params).then((r) => {
            if (!atual()) return;
            setInvalidPhones(r.itens);
            setInvalidTotal(r.total);
          })
        : api.listDispatchReport(params).then((r) => {
            if (!atual()) return;
            setDispatchReport(r.itens);
            setDispatchTotal(r.total);
          });
    request
      .catch((e) => atual() && setError(e.message))
      .finally(() => atual() && setLoading(false));
  }

  useEffect(() => {
    setOffset(0);
    load(0, limit);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [tab, faixaId, cobradoDe, cobradoAte, pagoDe, pagoAte]);

  function filtrosPagamentos() {
    const nome = faixas.find((f) => f.id === faixaId)?.name;
    return {
      faixa: nome ? [nome] : undefined,
      cobrado_de: cobradoDe || undefined,
      cobrado_ate: cobradoAte || undefined,
      pago_de: pagoDe || undefined,
      pago_ate: pagoAte || undefined,
    };
  }

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
      const periodo = { faixa_id: faixaId || undefined, de: cobradoDe || undefined, ate: cobradoAte || undefined };
      if (tab === "invalidos") {
        await api.downloadInvalidPhonesXlsx(periodo);
      } else if (tab === "envios") {
        await api.downloadDispatchReportXlsx(periodo);
      } else {
        await api.downloadPagamentosXlsx(filtrosPagamentos());
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
          <div className="subtitle">Telefones inválidos, cobranças enviadas e quem pagou</div>
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
          <button className={tab === "pagamentos" ? "" : "secondary"} onClick={() => setTab("pagamentos")}>
            Quem pagou
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

        <div className="form-row" style={{ flexWrap: "wrap", marginBottom: 12 }}>
          <div className="field">
            <label htmlFor="rel-cobrado-de">{tab === "invalidos" ? "Registrado de" : "Cobrado de"}</label>
            <input id="rel-cobrado-de" type="date" value={cobradoDe} max={cobradoAte || undefined} onChange={(e) => setCobradoDe(e.target.value)} />
          </div>
          <div className="field">
            <label htmlFor="rel-cobrado-ate">até</label>
            <input id="rel-cobrado-ate" type="date" value={cobradoAte} min={cobradoDe || undefined} onChange={(e) => setCobradoAte(e.target.value)} />
          </div>
          {tab === "pagamentos" && (
            <>
              <div className="field">
                <label htmlFor="rel-pago-de">Pago de</label>
                <input id="rel-pago-de" type="date" value={pagoDe} max={pagoAte || undefined} onChange={(e) => setPagoDe(e.target.value)} />
              </div>
              <div className="field">
                <label htmlFor="rel-pago-ate">até</label>
                <input id="rel-pago-ate" type="date" value={pagoAte} min={pagoDe || undefined} onChange={(e) => setPagoAte(e.target.value)} />
              </div>
            </>
          )}
        </div>

        {loading ? (
          <div className="loading-state">Carregando...</div>
        ) : tab === "pagamentos" ? (
          <TabelaPagamentos dados={pagamentos} ordenacao={pagamentosSort} />
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
                  {invalidPhones.map((r) => (
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
            {faixaId || cobradoDe || cobradoAte ? (
              <>
                <div className="title">Nenhum envio encontrado com esses filtros</div>
                <p>Troque a faixa ou o período para ver outros envios.</p>
              </>
            ) : (
              <>
                <div className="title">Nenhum envio realizado ainda</div>
                <p>Assim que uma cobrança for enviada, ela aparece aqui.</p>
              </>
            )}
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
                {dispatchReport.map((r, i) => (
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
        {(tab === "invalidos" ? invalidTotal : tab === "envios" ? dispatchTotal : pagamentos?.total ?? 0) > 0 && (
          <Paginacao
            total={tab === "invalidos" ? invalidTotal : tab === "envios" ? dispatchTotal : pagamentos?.total ?? 0}
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

const COLUNAS_PAGAMENTO: [ColunaPagamento, string][] = [
  ["codigo_cliente", "Código"],
  ["nome", "Nome"],
  ["loja", "Loja"],
  ["faixa", "Faixa"],
  ["data_cobranca", "Cobrado em"],
  ["valor_cobrado", "Valor cobrado"],
  ["valor_pago", "Valor pago"],
  ["primeiro_pagamento", "Pago em"],
];

function TabelaPagamentos({
  dados,
  ordenacao,
}: {
  dados: PagamentosPage | null;
  ordenacao: ReturnType<typeof useSort<ColunaPagamento>>;
}) {
  if (!dados || dados.itens.length === 0) {
    return (
      <div className="empty-state">
        <IconInbox width={28} height={28} />
        <div className="title">Ninguém pagou no período</div>
        <p>Clientes cobrados que quitaram algum título depois da cobrança aparecem aqui.</p>
      </div>
    );
  }
  return (
    <>
      <div className="stat-grid">
        <div className="stat">
          <div>
            <div className="value">{dados.total}</div>
            <div className="label">Clientes que pagaram</div>
          </div>
        </div>
        <div className="stat">
          <div>
            <div className="value">{formatBRL(dados.valor_cobrado)}</div>
            <div className="label">Valor cobrado deles</div>
          </div>
        </div>
        <div className="stat">
          <div>
            <div className="value">{formatBRL(dados.valor_pago)}</div>
            <div className="label">Valor pago</div>
          </div>
        </div>
      </div>
      <div className="table-wrap">
        <table>
          <thead>
            <tr>
              {COLUNAS_PAGAMENTO.map(([coluna, rotulo]) => (
                <SortableTh
                  key={coluna}
                  active={ordenacao.sortKey === coluna}
                  dir={ordenacao.sortDir}
                  onSort={() => ordenacao.toggleSort(coluna)}
                >
                  {rotulo}
                </SortableTh>
              ))}
            </tr>
          </thead>
          <tbody>
            {dados.itens.map((p: PagamentoCliente) => (
              <tr key={`${p.codigo_cliente}-${p.data_cobranca}`}>
                <td className="cell-strong">{p.codigo_cliente}</td>
                <td>{p.nome || "—"}</td>
                <td className="text-muted">{p.loja || "—"}</td>
                <td>{p.faixa}</td>
                <td>{formatData(p.data_cobranca)}</td>
                <td>{formatBRL(p.valor_cobrado)}</td>
                <td>{formatBRL(p.valor_pago)}</td>
                <td className="text-muted">
                  {formatData(p.primeiro_pagamento)}
                  {p.ultimo_pagamento && p.ultimo_pagamento !== p.primeiro_pagamento ? ` a ${formatData(p.ultimo_pagamento)}` : ""}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </>
  );
}
