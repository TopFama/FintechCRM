import { useEffect, useRef, useState } from "react";
import { Link, useSearchParams } from "react-router-dom";
import { api, ClienteCobranca, Faixa, FiltrosCobranca, mensagemErroSeta } from "../api";
import { formatBRL, formatCpf, formatData } from "../format";
import BarraFiltrosCobranca, { FILTROS_COBRANCA_PADRAO } from "../components/BarraFiltrosCobranca";
import UploadPlanilhaFaixa from "../components/UploadPlanilhaFaixa";
import Paginacao, { LIMIT_OPCOES_PADRAO } from "../components/Paginacao";
import SortableTh from "../components/SortableTh";
import { useOpcoesCobranca } from "../components/useOpcoesCobranca";
import { IconAlert } from "../icons";
import { SortDirection, useSort } from "../sort";

type ColunaCliente = "codigo" | "cpfcnpj" | "nome" | "vencimento_mais_antigo" | "valor_cobrar" | "qtd_parcelas_cobranca" | "dias_atraso" | "faixa" | "cluster";

function diasAtrasoLabel(dias: number): string {
  return dias === -1 ? "vence amanhã" : `${dias} dias`;
}

export default function Cobranca() {
  const opcoes = useOpcoesCobranca();
  const [searchParams] = useSearchParams();

  // Vindo de uma célula da matriz no Dashboard: /cobranca?cluster=X&faixa=Y
  const filtrosIniciais: FiltrosCobranca = {
    ...FILTROS_COBRANCA_PADRAO,
    cluster: searchParams.getAll("cluster"),
    faixa: searchParams.getAll("faixa"),
  };
  const veioDaMatriz = filtrosIniciais.cluster!.length > 0 || filtrosIniciais.faixa!.length > 0;

  const [filtrosEdit, setFiltrosEdit] = useState<FiltrosCobranca>(filtrosIniciais);
  const [filtrosAplicados, setFiltrosAplicados] = useState<FiltrosCobranca>(filtrosIniciais);

  const [clientes, setClientes] = useState<ClienteCobranca[]>([]);
  const [totalClientes, setTotalClientes] = useState(0);
  const [clientesErro, setClientesErro] = useState<string | null>(null);
  const [clientesCarregando, setClientesCarregando] = useState(false);
  const [offset, setOffset] = useState(0);
  const [limit, setLimit] = useState(LIMIT_OPCOES_PADRAO[1]);
  const clientesSort = useSort<ColunaCliente>(null, (chave, dir) => {
    setOffset(0);
    buscarClientes(filtrosAplicados, 0, limit, chave, dir);
  });

  const [gerandoLeads, setGerandoLeads] = useState(false);
  const [leadsResultado, setLeadsResultado] = useState<string | null>(null);
  const [leadsErro, setLeadsErro] = useState<string | null>(null);

  // Importação de planilha: escolher a faixa libera o upload dela.
  const [faixasUpload, setFaixasUpload] = useState<Faixa[]>([]);
  const [faixaUploadId, setFaixaUploadId] = useState("");
  useEffect(() => {
    api.listFaixas().then(setFaixasUpload).catch(() => undefined);
  }, []);

  // Descarta respostas de consultas já substituídas por outra mais nova
  const cliReqRef = useRef(0);

  function buscarClientes(
    filtros: FiltrosCobranca,
    novoOffset: number,
    novoLimit: number = limit,
    sortBy: ColunaCliente | null = clientesSort.sortKey,
    sortDir: SortDirection = clientesSort.sortDir
  ) {
    setClientesErro(null);
    setClientesCarregando(true);
    const seq = ++cliReqRef.current;
    api
      .listarClientesCobranca({ ...filtros, limit: novoLimit, offset: novoOffset, sort_by: sortBy ?? undefined, sort_dir: sortDir })
      .then((r) => {
        if (seq !== cliReqRef.current) return;
        setClientes(r.itens);
        setTotalClientes(r.total);
      })
      .catch((e) => {
        if (seq !== cliReqRef.current) return;
        setClientesErro(mensagemErroSeta(e));
      })
      .finally(() => {
        if (seq === cliReqRef.current) setClientesCarregando(false);
      });
  }

  useEffect(() => {
    if (veioDaMatriz) buscarClientes(filtrosIniciais, 0);
    // só na montagem: a query string define os filtros iniciais
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  function aplicarFiltros() {
    setOffset(0);
    setFiltrosAplicados(filtrosEdit);
    buscarClientes(filtrosEdit, 0);
    setLeadsResultado(null);
    setLeadsErro(null);
  }

  function mudarPagina(novoOffset: number) {
    setOffset(novoOffset);
    buscarClientes(filtrosAplicados, novoOffset);
  }

  function mudarLimite(novoLimit: number) {
    setLimit(novoLimit);
    setOffset(0);
    buscarClientes(filtrosAplicados, 0, novoLimit);
  }

  async function gerarLeads() {
    const msg =
      totalClientes > 0
        ? `Enviar ${totalClientes} cliente(s) com os filtros atuais para a fila de cobrança?`
        : "Enviar os clientes com os filtros atuais para a fila de cobrança?";
    if (!window.confirm(msg)) return;
    setGerandoLeads(true);
    setLeadsErro(null);
    setLeadsResultado(null);
    try {
      await api.gerarLeads(filtrosAplicados);
      // Depois de enviar, a listagem sai da tela: o acompanhamento é pela fila e pelo Dashboard.
      setClientes([]);
      setTotalClientes(0);
      setLeadsResultado("Clientes enviados para a fila de cobrança.");
    } catch (e) {
      setLeadsErro(e instanceof Error ? e.message : "Erro ao enviar para a fila de cobrança");
    } finally {
      setGerandoLeads(false);
    }
  }

  return (
    <div>
      <div className="page-header">
        <div>
          <h2>Cobrança</h2>
          <div className="subtitle">
            Consulte clientes em atraso no SETA e envie para a fila de cobrança — os relatórios ficam no{" "}
            <Link to="/">Dashboard</Link>
          </div>
        </div>
      </div>

      <div className="card">
        <div className="card-header">
          <h3>Importar planilha para a fila</h3>
        </div>
        <p className="card-subtitle">Escolha a faixa de atraso para liberar o envio da planilha.</p>
        <div className="form-row">
          <div className="field">
            <label>Faixa</label>
            <select value={faixaUploadId} onChange={(e) => setFaixaUploadId(e.target.value)}>
              <option value="">Selecione a faixa...</option>
              {faixasUpload.map((f) => (
                <option key={f.id} value={f.id}>
                  {f.name}
                </option>
              ))}
            </select>
          </div>
        </div>
        {faixaUploadId && <UploadPlanilhaFaixa faixaId={faixaUploadId} />}
      </div>

      <div className="card">
        <div className="card-header">
          <h3>Filtros</h3>
          <button type="button" onClick={gerarLeads} disabled={gerandoLeads} className="secondary">
            {gerandoLeads ? "Enviando..." : "Enviar para fila de cobrança"}
          </button>
        </div>

        {leadsResultado && (
          <div className="success-box">{leadsResultado}</div>
        )}
        {leadsErro && (
          <div className="error-box">
            <IconAlert width={16} height={16} />
            <span>{leadsErro}</span>
          </div>
        )}

        <BarraFiltrosCobranca
          valor={filtrosEdit}
          onChange={setFiltrosEdit}
          onAplicar={aplicarFiltros}
          opcoes={opcoes}
          idPrefixo="cobranca"
        />
      </div>

      <div className="card">
        <div className="card-header">
          <h3>
            Clientes
            {totalClientes > 0 && (
              <span className="text-muted" style={{ fontWeight: 400, marginLeft: 8 }}>
                ({totalClientes.toLocaleString("pt-BR")})
              </span>
            )}
          </h3>
        </div>

        {clientesErro && (
          <div className="error-box">
            <IconAlert width={16} height={16} />
            <span>{clientesErro}</span>
          </div>
        )}

        {clientesCarregando && (
          <div className="loading-state">Consultando o SETA — isso pode levar até 45 segundos...</div>
        )}

        {!clientesCarregando && clientes.length === 0 && !clientesErro && (
          <div className="empty-state">
            <p>Aplique os filtros para listar clientes.</p>
          </div>
        )}

        {!clientesCarregando && clientes.length > 0 && (
          <>
            <div className="table-wrap">
              <table>
                <thead>
                  <tr>
                    {(
                      [
                        ["codigo", "Código"],
                        ["cpfcnpj", "CPF"],
                        ["nome", "Nome"],
                        ["vencimento_mais_antigo", "Vencimento"],
                        ["valor_cobrar", "Valor"],
                        ["qtd_parcelas_cobranca", "Parcelas"],
                        ["dias_atraso", "Atraso"],
                        ["faixa", "Faixa"],
                        ["cluster", "Cluster"],
                      ] as [ColunaCliente, string][]
                    ).map(([coluna, rotulo]) => (
                      <SortableTh
                        key={coluna}
                        scope="col"
                        active={clientesSort.sortKey === coluna}
                        dir={clientesSort.sortDir}
                        onSort={() => clientesSort.toggleSort(coluna)}
                      >
                        {rotulo}
                      </SortableTh>
                    ))}
                  </tr>
                </thead>
                <tbody>
                  {clientes.map((c) => (
                    <tr key={c.codigo}>
                      <td className="cell-strong">{c.codigo}</td>
                      <td className="text-muted">{formatCpf(c.cpfcnpj)}</td>
                      <td>
                        {c.nome}
                        {c.spc_restricao === "sim" && (
                          <span className="badge rejected" style={{ marginLeft: 6 }}>
                            SPC
                          </span>
                        )}
                      </td>
                      <td>{formatData(c.vencimento_mais_antigo)}</td>
                      <td>{formatBRL(c.valor_cobrar)}</td>
                      <td>{c.qtd_parcelas_cobranca}</td>
                      <td>{diasAtrasoLabel(c.dias_atraso)}</td>
                      <td>{c.faixa ?? "—"}</td>
                      <td>{c.cluster}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
            <Paginacao total={totalClientes} limit={limit} offset={offset} onChange={mudarPagina} onLimitChange={mudarLimite} />
          </>
        )}
      </div>
    </div>
  );
}
