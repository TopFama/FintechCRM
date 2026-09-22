import { useEffect, useRef, useState } from "react";
import { Link, useSearchParams } from "react-router-dom";
import { api, ClienteCobranca, FiltrosCobranca, mensagemErroSeta } from "../api";
import { formatBRL, formatCpf, formatData } from "../format";
import BarraFiltrosCobranca, { FILTROS_COBRANCA_PADRAO } from "../components/BarraFiltrosCobranca";
import Paginacao from "../components/Paginacao";
import { useOpcoesCobranca } from "../components/useOpcoesCobranca";
import { IconAlert } from "../icons";

const LIMIT = 50;

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

  const [gerandoLeads, setGerandoLeads] = useState(false);
  const [leadsResultado, setLeadsResultado] = useState<{
    criados: number;
    ja_existiam: number;
    sem_celular: number;
  } | null>(null);
  const [leadsErro, setLeadsErro] = useState<string | null>(null);

  // Descarta respostas de consultas já substituídas por outra mais nova
  const cliReqRef = useRef(0);

  function buscarClientes(filtros: FiltrosCobranca, novoOffset: number) {
    setClientesErro(null);
    setClientesCarregando(true);
    const seq = ++cliReqRef.current;
    api
      .listarClientesCobranca({ ...filtros, limit: LIMIT, offset: novoOffset })
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

  async function gerarLeads() {
    const msg =
      totalClientes > 0
        ? `Gerar leads para ${totalClientes} cliente(s) com os filtros atuais?`
        : "Gerar leads com os filtros atuais?";
    if (!window.confirm(msg)) return;
    setGerandoLeads(true);
    setLeadsErro(null);
    setLeadsResultado(null);
    try {
      setLeadsResultado(await api.gerarLeads(filtrosAplicados));
    } catch (e) {
      setLeadsErro(e instanceof Error ? e.message : "Erro ao gerar leads");
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
            Consulte clientes em atraso no ERP SETA e gere leads — os relatórios ficam no{" "}
            <Link to="/">Dashboard</Link>
          </div>
        </div>
      </div>

      <div className="card">
        <div className="card-header">
          <h3>Filtros</h3>
          <button type="button" onClick={gerarLeads} disabled={gerandoLeads} className="secondary">
            {gerandoLeads ? "Gerando..." : "Gerar leads com estes filtros"}
          </button>
        </div>

        {leadsResultado && (
          <div className="success-box">
            {leadsResultado.criados} leads criados, {leadsResultado.ja_existiam} já existiam,{" "}
            {leadsResultado.sem_celular} sem celular válido. <Link to="/leads">Ver leads →</Link>
          </div>
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
          <div className="loading-state">Consultando o ERP SETA — isso pode levar até 45 segundos...</div>
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
                    <th scope="col">Código</th>
                    <th scope="col">CPF</th>
                    <th scope="col">Nome</th>
                    <th scope="col">Vencimento</th>
                    <th scope="col">Valor</th>
                    <th scope="col">Parcelas</th>
                    <th scope="col">Atraso</th>
                    <th scope="col">Faixa</th>
                    <th scope="col">Cluster</th>
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
            <Paginacao total={totalClientes} limit={LIMIT} offset={offset} onChange={mudarPagina} />
          </>
        )}
      </div>
    </div>
  );
}
