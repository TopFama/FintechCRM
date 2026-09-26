import { useEffect, useRef, useState } from "react";
import { useSearchParams } from "react-router-dom";
import {
  api,
  DispatchReportItem,
  Faixa,
  FilaReportItem,
  FilaReportPage,
  InvalidPhoneRecord,
  Loja,
  PagamentoCliente,
  PagamentosPage,
  PausaEnvio,
  ROTULO_TIPO_FAIXA,
  TipoFaixa,
} from "../api";
import Paginacao, { LIMIT_OPCOES_PADRAO } from "../components/Paginacao";
import { AcaoPendentes, PainelAcao, PainelDescartar, PainelPausaLote, PausasAtivas } from "../components/PausasPendentes";
import SelectCampanha from "../components/SelectCampanha";
import SortableTh from "../components/SortableTh";
import { formatBRL, formatData, formatDataHora, formatNumero, formatValorFila } from "../format";
import { IconAlert, IconCheckCircle, IconDownload, IconInbox } from "../icons";
import { SortDirection, useSort } from "../sort";

type Tab = "invalidos" | "envios" | "pagamentos" | "pendentes" | "erros";
// mesma ordem dos cards do Dashboard
const ABAS: { aba: Tab; rotulo: string }[] = [
  { aba: "pendentes", rotulo: "Pendentes" },
  { aba: "envios", rotulo: "Envios realizados" },
  { aba: "erros", rotulo: "Erros" },
  { aba: "invalidos", rotulo: "Telefones inválidos" },
  { aba: "pagamentos", rotulo: "Quem pagou" },
];
type ColunaFila =
  | "codigo_cliente"
  | "nome"
  | "faixa"
  | "campanha"
  | "valor"
  | "telefone"
  | "entrou_em"
  | "quando"
  | "mensagem";
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
  // Aba, período e faixa vivem na URL: um link do Dashboard abre direto no
  // relatório certo e F5/voltar mantêm o que estava na tela.
  const [params, setParams] = useSearchParams();
  const abaUrl = params.get("aba") as Tab | null;
  const tab: Tab = abaUrl && ABAS.some((a) => a.aba === abaUrl) ? abaUrl : ABAS[0].aba;
  const faixaId = params.get("faixa_id") ?? "";
  const campanha = params.get("campanha") ?? "";
  const cobradoDe = params.get("de") ?? "";
  const cobradoAte = params.get("ate") ?? "";
  // Vem do card "Pagaram em até 7 dias": mesma janela da efetividade
  const diasJanela = params.get("dias_janela") ?? "";
  const loja = tab === "pendentes" ? params.get("loja") ?? "" : "";
  function mudarUrl(mudancas: Record<string, string>) {
    setParams(
      (atual) => {
        const proximo = new URLSearchParams(atual);
        for (const [k, v] of Object.entries(mudancas)) {
          if (v) proximo.set(k, v);
          else proximo.delete(k);
        }
        return proximo;
      },
      { replace: true }
    );
  }
  const setTab = (t: Tab) => setParams((atual) => {
    const proximo = new URLSearchParams(atual);
    proximo.set("aba", t);
    return proximo;
  });
  const setFaixaId = (v: string) => mudarUrl({ faixa_id: v });
  const setCobradoDe = (v: string) => mudarUrl({ de: v });
  const setCobradoAte = (v: string) => mudarUrl({ ate: v });
  const [faixas, setFaixas] = useState<Faixa[]>([]);
  const [fila, setFila] = useState<FilaReportItem[]>([]);
  const [filaTotal, setFilaTotal] = useState(0);
  const [filaInfo, setFilaInfo] = useState<Pick<FilaReportPage, "total_pausados" | "total_sem_loja">>({
    total_pausados: 0,
    total_sem_loja: 0,
  });
  const [lojas, setLojas] = useState<Loja[]>([]);
  const [pausas, setPausas] = useState<PausaEnvio[]>([]);
  const [acao, setAcao] = useState<AcaoPendentes | null>(null);
  const [pausaLote, setPausaLote] = useState<"faixa" | "loja" | null>(null);
  const [descartar, setDescartar] = useState(false);
  const [aviso, setAviso] = useState<string | null>(null);
  const [invalidPhones, setInvalidPhones] = useState<InvalidPhoneRecord[]>([]);
  const [invalidTotal, setInvalidTotal] = useState(0);
  const [dispatchReport, setDispatchReport] = useState<DispatchReportItem[]>([]);
  const [dispatchTotal, setDispatchTotal] = useState(0);
  const [offset, setOffset] = useState(0);
  const [limit, setLimit] = useState(LIMIT_OPCOES_PADRAO[1]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [downloading, setDownloading] = useState(false);
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
  const pendentesSort = useSort<ColunaFila>(null, (chave, dir) => {
    setOffset(0);
    load(0, limit, chave, dir);
  });
  const errosSort = useSort<ColunaFila>(null, (chave, dir) => {
    setOffset(0);
    load(0, limit, chave, dir);
  });

  useEffect(() => {
    api.listFaixas().then(setFaixas).catch(() => undefined);
  }, []);

  function carregarPausas() {
    api.listarPausas().then(setPausas).catch((e) => setError(e.message));
  }

  useEffect(() => {
    setAcao(null);
    setPausaLote(null);
    setDescartar(false);
    setAviso(null);
    if (tab !== "pendentes") return;
    carregarPausas();
    if (lojas.length === 0) api.listarLojas().then(setLojas).catch(() => undefined);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [tab]);

  function sortAtual() {
    return tab === "invalidos"
      ? invalidosSort
      : tab === "pagamentos"
      ? pagamentosSort
      : tab === "pendentes"
      ? pendentesSort
      : tab === "erros"
      ? errosSort
      : enviosSort;
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
      campanha: campanha || undefined,
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
        : tab === "pendentes" || tab === "erros"
        ? (tab === "pendentes" ? api.listPendentes({ ...params, loja: loja || undefined }) : api.listErros(params)).then(
            (r) => {
              if (!atual()) return;
              setFila(r.itens);
              setFilaTotal(r.total);
              setFilaInfo({ total_pausados: r.total_pausados, total_sem_loja: r.total_sem_loja });
            }
          )
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
  }, [tab, faixaId, campanha, loja, cobradoDe, cobradoAte, pagoDe, pagoAte, diasJanela]);

  function filtrosPagamentos() {
    const nome = faixas.find((f) => f.id === faixaId)?.name;
    return {
      faixa: nome ? [nome] : undefined,
      campanha: campanha || undefined,
      cobrado_de: cobradoDe || undefined,
      cobrado_ate: cobradoAte || undefined,
      pago_de: pagoDe || undefined,
      pago_ate: pagoAte || undefined,
      dias_janela: diasJanela ? Number(diasJanela) : undefined,
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
      const periodo = {
        faixa_id: faixaId || undefined,
        campanha: campanha || undefined,
        de: cobradoDe || undefined,
        ate: cobradoAte || undefined,
      };
      if (tab === "invalidos") {
        await api.downloadInvalidPhonesXlsx(periodo);
      } else if (tab === "envios") {
        await api.downloadDispatchReportXlsx(periodo);
      } else if (tab === "pendentes") {
        await api.downloadPendentesXlsx({ ...periodo, loja: loja || undefined });
      } else if (tab === "erros") {
        await api.downloadErrosXlsx(periodo);
      } else {
        await api.downloadPagamentosXlsx(filtrosPagamentos());
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : "Erro ao baixar relatório");
    } finally {
      setDownloading(false);
    }
  }

  function acaoEscopo(tipo: "pausar" | "parar", escopo: "faixa" | "loja"): AcaoPendentes {
    if (escopo === "faixa") {
      const nome = faixas.find((f) => f.id === faixaId)?.name ?? faixaId;
      return { tipo, escopo, valor: faixaId, rotulo: `a régua ${nome}` };
    }
    const l = lojas.find((x) => x.filial === loja);
    return { tipo, escopo, valor: loja, rotulo: `a loja ${l?.nome_com_cod || loja}` };
  }

  const totalAtual =
    tab === "invalidos"
      ? invalidTotal
      : tab === "envios"
      ? dispatchTotal
      : tab === "pendentes" || tab === "erros"
      ? filaTotal
      : pagamentos?.total ?? 0;

  return (
    <div>
      <div className="page-header">
        <div>
          <h2>Relatórios</h2>
          <div className="subtitle">Pendentes, cobranças enviadas, erros, telefones inválidos e quem pagou</div>
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
          {ABAS.map(({ aba, rotulo }) => (
            <button key={aba} className={tab === aba ? "" : "secondary"} onClick={() => setTab(aba)}>
              {rotulo}
            </button>
          ))}
          <div style={{ marginLeft: "auto", display: "flex", gap: 8, flexWrap: "wrap" }}>
            <select aria-label="Faixa" value={faixaId} onChange={(e) => setFaixaId(e.target.value)} style={{ minWidth: 180 }}>
              <option value="">Todas as faixas</option>
              {(["regua", "campanha", "remarketing"] as TipoFaixa[]).map((tipo) => {
                const doTipo = faixas.filter((f) => f.tipo === tipo);
                return doTipo.length ? (
                  <optgroup key={tipo} label={ROTULO_TIPO_FAIXA[tipo]}>
                    {doTipo.map((f) => (
                      <option key={f.id} value={f.id}>
                        {tipo === "campanha" ? f.name.replace(/^Campanha: /, "") : f.name}
                      </option>
                    ))}
                  </optgroup>
                ) : null;
              })}
            </select>
            <SelectCampanha id="relatorios-campanha" compacto value={campanha} onChange={(v) => mudarUrl({ campanha: v })} />
            {tab === "pendentes" && (
              <select
                aria-label="Loja"
                value={loja}
                onChange={(e) => mudarUrl({ loja: e.target.value })}
                style={{ minWidth: 160 }}
              >
                <option value="">Todas as lojas</option>
                {lojas.map((l) => (
                  <option key={l.filial} value={l.filial}>
                    {l.nome_com_cod || l.filial}
                  </option>
                ))}
              </select>
            )}
            <button className="secondary" onClick={handleDownload} disabled={downloading}>
              <IconDownload width={16} height={16} /> {downloading ? "Baixando..." : "Baixar Excel"}
            </button>
          </div>
        </div>

        <div className="form-row" style={{ flexWrap: "wrap", marginBottom: 12 }}>
          <div className="field">
            <label htmlFor="rel-cobrado-de">
              {tab === "invalidos" ? "Registrado de" : tab === "pendentes" || tab === "erros" ? "Entrou na fila de" : "Cobrado de"}
            </label>
            <input id="rel-cobrado-de" type="date" value={cobradoDe} max={cobradoAte || undefined} onChange={(e) => setCobradoDe(e.target.value)} />
          </div>
          <div className="field">
            <label htmlFor="rel-cobrado-ate">até</label>
            <input id="rel-cobrado-ate" type="date" value={cobradoAte} min={cobradoDe || undefined} onChange={(e) => setCobradoAte(e.target.value)} />
          </div>
          {tab === "pagamentos" && (
            <>
              <div className="field">
                <label htmlFor="rel-dias-janela">Pagou em até</label>
                <select
                  id="rel-dias-janela"
                  value={diasJanela}
                  onChange={(e) => mudarUrl({ dias_janela: e.target.value })}
                >
                  <option value="">Qualquer data após a cobrança</option>
                  {["3", "7", "15", "30"].includes(diasJanela) || !diasJanela ? null : (
                    <option value={diasJanela}>{diasJanela} dias</option>
                  )}
                  <option value="3">3 dias</option>
                  <option value="7">7 dias</option>
                  <option value="15">15 dias</option>
                  <option value="30">30 dias</option>
                </select>
              </div>
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

        {tab === "pendentes" && (
          <>
            {aviso && <div className="success-box" style={{ marginBottom: 12 }}>{aviso}</div>}
            <PausasAtivas
              pausas={pausas}
              onAplicarVariaveis={(p) =>
                api
                  .reaplicarVariaveisFaixa(p.valor)
                  .then((r) =>
                    setAviso(
                      `Variáveis atuais aplicadas a ${r.atualizados} pendente(s) de ${p.valor_legivel}` +
                        (r.sem_cadastro ? ` (${r.sem_cadastro} sem cadastro do cliente ficaram como estavam).` : ".")
                    )
                  )
                  .catch((e) => setError(e.message))
              }
              onRetomar={(p) =>
                api
                  .retomarEnvio(p.id)
                  .then(() => {
                    setAviso(`Envio retomado para ${p.valor_legivel}. Volta a sair no próximo ciclo de disparo.`);
                    carregarPausas();
                    load();
                  })
                  .catch((e) => setError(e.message))
              }
            />
            <div className="barra-escopo">
              <button
                className="secondary small"
                aria-expanded={pausaLote === "faixa"}
                onClick={() => {
                  setAcao(null);
                  setDescartar(false);
                  setPausaLote(pausaLote === "faixa" ? null : "faixa");
                }}
              >
                Pausar faixa
              </button>
              <button
                className="secondary small"
                aria-expanded={pausaLote === "loja"}
                onClick={() => {
                  setAcao(null);
                  setDescartar(false);
                  setPausaLote(pausaLote === "loja" ? null : "loja");
                }}
              >
                Pausar loja
              </button>
              {faixaId && (
                <button className="secondary small" onClick={() => setAcao(acaoEscopo("parar", "faixa"))}>
                  Parar esta régua
                </button>
              )}
              {loja && (
                <button className="secondary small" onClick={() => setAcao(acaoEscopo("parar", "loja"))}>
                  Parar esta loja
                </button>
              )}
              <button
                className="secondary small"
                aria-expanded={descartar}
                disabled={filaTotal === 0}
                onClick={() => {
                  setAcao(null);
                  setPausaLote(null);
                  setDescartar(!descartar);
                }}
              >
                Descartar fila
              </button>
            </div>
            {descartar && (
              <PainelDescartar
                filtros={{
                  faixa_id: faixaId || undefined,
                  campanha: campanha || undefined,
                  loja: loja || undefined,
                  de: cobradoDe || undefined,
                  ate: cobradoAte || undefined,
                }}
                descricao={
                  faixaId || campanha || loja || cobradoDe || cobradoAte
                    ? "os pendentes com os filtros desta tela"
                    : "todos os pendentes"
                }
                onCancelar={() => setDescartar(false)}
                onConcluir={(msg) => {
                  setDescartar(false);
                  setAviso(msg);
                  load();
                }}
              />
            )}
            {pausaLote && (
              <PainelPausaLote
                escopo={pausaLote}
                onCancelar={() => setPausaLote(null)}
                onConcluir={(msg) => {
                  setPausaLote(null);
                  setAviso(msg);
                  carregarPausas();
                  load();
                }}
              />
            )}
            {acao && (
              <PainelAcao
                acao={acao}
                onCancelar={() => setAcao(null)}
                onConcluir={(msg) => {
                  setAcao(null);
                  setAviso(msg);
                  carregarPausas();
                  load();
                }}
              />
            )}
            {filaTotal > 0 && (
              <p className="text-muted" style={{ margin: "0 0 10px" }}>
                {filaTotal} pendente(s) · {filaInfo.total_pausados} pausado(s)
                {filaInfo.total_sem_loja > 0 &&
                  ` · ${filaInfo.total_sem_loja} sem loja (vieram de planilha sem cadastro do cliente; pausa por loja não os pega)`}
              </p>
            )}
          </>
        )}

        {loading ? (
          <div className="loading-state">Carregando...</div>
        ) : tab === "pagamentos" ? (
          <TabelaPagamentos dados={pagamentos} ordenacao={pagamentosSort} />
        ) : tab === "pendentes" || tab === "erros" ? (
          <TabelaFila
            tipo={tab}
            itens={fila}
            ordenacao={tab === "pendentes" ? pendentesSort : errosSort}
            onAcao={(tipo, item) =>
              setAcao({
                tipo,
                escopo: "cliente",
                valor: item.codigo_cliente,
                rotulo: `o cliente ${item.codigo_cliente}${item.nome ? ` · ${item.nome}` : ""}`,
              })
            }
          />
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
                    <td>{formatValorFila(r.valor)}</td>
                    <td className="text-muted">{r.telefone}</td>
                    <td className="text-faint">{formatDataHora(r.enviado_em)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
        {(totalAtual) > 0 && (
          <Paginacao
            total={totalAtual}
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
            <div className="value">{formatNumero(dados.total_clientes)}</div>
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

const COLUNAS_FILA: Record<"pendentes" | "erros", [ColunaFila, string][]> = {
  pendentes: [
    ["codigo_cliente", "Código"],
    ["nome", "Nome"],
    ["faixa", "Faixa de atraso (régua)"],
    ["campanha", "Campanha"],
    ["valor", "Valor"],
    ["telefone", "Telefone"],
    ["entrou_em", "Entrou na fila em"],
  ],
  erros: [
    ["codigo_cliente", "Código"],
    ["nome", "Nome"],
    ["faixa", "Faixa de atraso (régua)"],
    ["campanha", "Campanha"],
    ["valor", "Valor"],
    ["telefone", "Telefone"],
    ["mensagem", "Mensagem"],
    ["quando", "Quando"],
  ],
};

function TabelaFila({
  tipo,
  itens,
  ordenacao,
  onAcao,
}: {
  tipo: "pendentes" | "erros";
  itens: FilaReportItem[];
  ordenacao: ReturnType<typeof useSort<ColunaFila>>;
  onAcao: (tipo: "pausar" | "parar", item: FilaReportItem) => void;
}) {
  if (itens.length === 0) {
    return (
      <div className="empty-state">
        {tipo === "pendentes" ? <IconInbox width={28} height={28} /> : <IconCheckCircle width={28} height={28} />}
        <div className="title">{tipo === "pendentes" ? "Nenhum pendente na fila" : "Nenhum erro de envio"}</div>
        <p>Troque a faixa ou o período para ver outros itens da fila.</p>
      </div>
    );
  }
  return (
    <div className="table-wrap">
      <table>
        <thead>
          <tr>
            {COLUNAS_FILA[tipo].map(([coluna, rotulo]) => (
              <SortableTh
                key={coluna}
                active={ordenacao.sortKey === coluna}
                dir={ordenacao.sortDir}
                onSort={() => ordenacao.toggleSort(coluna)}
              >
                {rotulo}
              </SortableTh>
            ))}
            {tipo === "pendentes" && (
              <>
                <th scope="col">Loja</th>
                <th scope="col">
                  <span className="sr-only">Ações</span>
                </th>
              </>
            )}
          </tr>
        </thead>
        <tbody>
          {itens.map((r) => (
            <tr key={r.id}>
              <td className="cell-strong">{r.codigo_cliente}</td>
              <td>
                {r.nome || "—"} {r.pausado && <span className="badge pausado">Pausado</span>}
              </td>
              <td>{r.faixa || "—"}</td>
              <td>{r.campanha || <span className="text-faint">Régua</span>}</td>
              <td>{formatValorFila(r.valor)}</td>
              <td className="text-muted">{r.telefone}</td>
              {tipo === "pendentes" ? (
                <>
                  <td className="text-faint">{formatDataHora(r.entrou_em)}</td>
                  <td className="text-muted" title={r.lojas.length ? undefined : "Sem loja: pausa por loja não pega este item"}>
                    {r.lojas.length ? r.lojas.join(", ") : "sem loja"}
                  </td>
                  <td>
                    <div className="acoes-linha">
                      {!r.pausado && (
                        <button
                          className="secondary small"
                          onClick={() => onAcao("pausar", r)}
                          aria-label={`Pausar cliente ${r.codigo_cliente}`}
                        >
                          Pausar cliente
                        </button>
                      )}
                      <button className="secondary small" onClick={() => onAcao("parar", r)} aria-label={`Parar ${r.codigo_cliente}`}>
                        Parar
                      </button>
                    </div>
                  </td>
                </>
              ) : (
                <>
                  <td>{r.mensagem}</td>
                  <td className="text-faint">{r.quando ? formatDataHora(r.quando) : "—"}</td>
                </>
              )}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
