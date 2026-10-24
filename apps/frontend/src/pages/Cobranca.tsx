import { useEffect, useState } from "react";
import { Link, useSearchParams } from "react-router-dom";
import { api, ClienteCobranca, Faixa, FiltrosCobranca, foiCancelada, mensagemErroSeta } from "../api";
import { formatBRL, formatCpf, formatData } from "../format";
import BarraFiltrosCobranca, { FILTROS_COBRANCA_PADRAO } from "../components/BarraFiltrosCobranca";
import UploadPlanilhaFaixa from "../components/UploadPlanilhaFaixa";
import AvisosCategoria from "../components/AvisosCategoria";
import Paginacao, { LIMIT_OPCOES_PADRAO } from "../components/Paginacao";
import { ControleFiltros, ThFiltravel, TipoColuna } from "../components/FiltroColuna";
import { FiltrosColuna, serializarFiltros, useFiltrosColuna } from "../filtrosColuna";
import { useOpcoesCobranca } from "../components/useOpcoesCobranca";
import { useRequisicaoUnica } from "../components/useRequisicaoUnica";
import { IconAlert } from "../icons";
import { SortDirection, useSort } from "../sort";

type ColunaCliente = "codigo" | "cpfcnpj" | "nome" | "vencimento_mais_antigo" | "valor_cobrar" | "qtd_parcelas_cobranca" | "dias_atraso" | "faixa" | "cluster";

const COLUNAS_CLIENTE: [ColunaCliente, string, TipoColuna][] = [
  ["codigo", "Código", "texto"],
  ["cpfcnpj", "CPF", "texto"],
  ["nome", "Nome", "texto"],
  ["vencimento_mais_antigo", "Vencimento", "data"],
  ["valor_cobrar", "Valor", "numero"],
  ["qtd_parcelas_cobranca", "Parcelas", "numero"],
  ["dias_atraso", "Atraso", "numero"],
  ["faixa", "Faixa", "texto"],
  ["cluster", "Cluster", "texto"],
];

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
  // Diferencia "ainda não consultou" de "consultou e não veio ninguém"
  const [consultado, setConsultado] = useState(false);
  const [offset, setOffset] = useState(0);
  const [limit, setLimit] = useState(LIMIT_OPCOES_PADRAO[1]);
  const clientesSort = useSort<ColunaCliente>(null, (chave, dir) => {
    setOffset(0);
    buscarClientes(filtrosAplicados, 0, limit, chave, dir);
  });
  // Filtros das colunas da lista (estilo Excel, como nos Relatórios): a lista vem do servidor já filtrada
  const { filtros: filtrosColuna, alterar: alterarFiltroColuna } = useFiltrosColuna("clientes", "cobranca:filtros");
  const temFiltroColuna = Object.keys(filtrosColuna).length > 0;
  // Exportar e Enviar perguntam se aplicam os filtros das colunas; null = sem pergunta aberta
  const [perguntaColunas, setPerguntaColunas] = useState<"exportar" | "enviar" | null>(null);

  const [gerandoLeads, setGerandoLeads] = useState(false);
  const [leadsResultado, setLeadsResultado] = useState<string | null>(null);
  const [avisosCategoria, setAvisosCategoria] = useState<string[]>([]);
  const [leadsErro, setLeadsErro] = useState<string | null>(null);

  // Importação de planilha: escolher a faixa libera o upload dela.
  const [faixasUpload, setFaixasUpload] = useState<Faixa[]>([]);
  const [faixaUploadId, setFaixaUploadId] = useState("");
  useEffect(() => {
    api.listFaixas().then((fs) => setFaixasUpload(fs.filter((f) => f.tipo === "regua"))).catch(() => undefined);
  }, []);

  // Uma consulta nova cancela a anterior (inclusive o polling dela no backend)
  const novaConsulta = useRequisicaoUnica();
  const novoEnvio = useRequisicaoUnica(); // sair da tela para o polling do envio

  function buscarClientes(
    filtros: FiltrosCobranca,
    novoOffset: number,
    novoLimit: number = limit,
    sortBy: ColunaCliente | null = clientesSort.sortKey,
    sortDir: SortDirection = clientesSort.sortDir,
    colunas: FiltrosColuna = filtrosColuna
  ) {
    setClientesErro(null);
    setClientesCarregando(true);
    const signal = novaConsulta();
    api
      .listarClientesCobranca(
        { ...filtros, limit: novoLimit, offset: novoOffset, sort_by: sortBy ?? undefined, sort_dir: sortDir, filtros: serializarFiltros(colunas) },
        signal
      )
      .then((r) => {
        setClientes(r.itens);
        setTotalClientes(r.total);
        setConsultado(true);
      })
      .catch((e) => {
        if (!foiCancelada(e)) setClientesErro(mensagemErroSeta(e));
      })
      .finally(() => {
        if (!signal.aborted) setClientesCarregando(false);
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

  const controleFiltros: ControleFiltros = {
    filtros: filtrosColuna,
    alterar: (coluna, filtro) => {
      alterarFiltroColuna(coluna, filtro);
      const { [coluna]: _antigo, ...resto } = filtrosColuna;
      setOffset(0);
      buscarClientes(filtrosAplicados, 0, limit, clientesSort.sortKey, clientesSort.sortDir, filtro ? { ...resto, [coluna]: filtro } : resto);
    },
    valores: (coluna, busca) =>
      api.valoresClientesCobranca({ ...filtrosAplicados, coluna, busca: busca || undefined, filtros: serializarFiltros(filtrosColuna) }),
  };

  function mudarPagina(novoOffset: number) {
    setOffset(novoOffset);
    buscarClientes(filtrosAplicados, novoOffset);
  }

  function mudarLimite(novoLimit: number) {
    setLimit(novoLimit);
    setOffset(0);
    buscarClientes(filtrosAplicados, 0, novoLimit);
  }

  const [exportando, setExportando] = useState(false);

  // Enviar e Exportar usam o que está na tela, mesmo que ainda não aplicado
  const filtrosMudaram = JSON.stringify(filtrosEdit) !== JSON.stringify(filtrosAplicados);

  async function exportarExcel(comColunas: boolean) {
    setExportando(true);
    setLeadsErro(null);
    try {
      await api.exportarClientesCobranca({
        ...filtrosEdit,
        sort_by: clientesSort.sortKey ?? undefined,
        sort_dir: clientesSort.sortDir,
        filtros: comColunas ? serializarFiltros(filtrosColuna) : undefined,
      });
    } catch (e) {
      setLeadsErro(e instanceof Error ? e.message : "Erro ao exportar os clientes");
    } finally {
      setExportando(false);
    }
  }

  function decidirColunas(comColunas: boolean) {
    const acao = perguntaColunas;
    setPerguntaColunas(null);
    if (acao === "exportar") exportarExcel(comColunas);
    else gerarLeads(comColunas);
  }

  async function gerarLeads(comColunas: boolean) {
    const msg =
      totalClientes > 0 && !filtrosMudaram && (comColunas || !temFiltroColuna)
        ? `Enviar ${totalClientes} cliente(s) com os filtros atuais para a fila de cobrança?`
        : "Enviar os clientes com os filtros atuais para a fila de cobrança?";
    if (!window.confirm(msg)) return;
    setGerandoLeads(true);
    setLeadsErro(null);
    setLeadsResultado(null);
    setAvisosCategoria([]);
    const signal = novoEnvio();
    try {
      const r = await api.gerarLeads({ ...filtrosEdit, filtros: comColunas ? serializarFiltros(filtrosColuna) : undefined }, signal);
      const semCelular = r.sem_celular > 0 ? ` ${r.sem_celular} sem celular válido.` : "";
      if (r.na_fila === 0) {
        setLeadsErro(
          "Nenhum cliente entrou na fila. Confira se a faixa tem número e template ativos e se os clientes " +
            "já não estão na fila ou foram cobrados hoje." + semCelular
        );
        return;
      }
      // Depois de enviar, a listagem sai da tela: o acompanhamento é pela fila e pelo Dashboard.
      setClientes([]);
      setTotalClientes(0);
      setConsultado(false);
      setLeadsResultado(`${r.na_fila.toLocaleString("pt-BR")} cliente(s) enviado(s) para a fila de cobrança.${semCelular}`);
      setAvisosCategoria(r.avisos_categoria);
    } catch (e) {
      if (!foiCancelada(e)) setLeadsErro(e instanceof Error ? e.message : "Erro ao enviar para a fila de cobrança");
    } finally {
      if (!signal.aborted) setGerandoLeads(false);
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
            <label htmlFor="cobranca-faixa">Faixa</label>
            <select id="cobranca-faixa" value={faixaUploadId} onChange={(e) => setFaixaUploadId(e.target.value)}>
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
          <button type="button" onClick={() => (temFiltroColuna ? setPerguntaColunas("enviar") : gerarLeads(false))} disabled={gerandoLeads} className="secondary">
            {gerandoLeads ? "Enviando..." : "Enviar para fila de cobrança"}
          </button>
        </div>

        {leadsResultado && (
          <div className="success-box">{leadsResultado}</div>
        )}
        <AvisosCategoria avisos={avisosCategoria} />
        {leadsErro && (
          <div className="error-box">
            <IconAlert width={16} height={16} />
            <span>{leadsErro}</span>
          </div>
        )}

        {perguntaColunas && (
          <div className="painel-acao" role="dialog" aria-labelledby="titulo-colunas">
            <strong id="titulo-colunas">Aplicar os filtros das colunas?</strong>
            <p className="text-muted" style={{ margin: "4px 0 10px" }}>
              A lista de clientes tem filtros ativos nas colunas. Deseja aplicá-los {perguntaColunas === "exportar" ? "ao exportar" : "ao enviar para a fila"}?
            </p>
            <div className="acoes">
              <button type="button" onClick={() => decidirColunas(true)}>
                Aplicar filtros das colunas
              </button>
              <button type="button" className="secondary" onClick={() => decidirColunas(false)}>
                Ignorar filtros das colunas
              </button>
              <button type="button" className="secondary" onClick={() => setPerguntaColunas(null)}>
                Cancelar
              </button>
            </div>
          </div>
        )}

        <BarraFiltrosCobranca
          valor={filtrosEdit}
          onChange={setFiltrosEdit}
          onAplicar={aplicarFiltros}
          carregando={clientesCarregando}
          opcoes={opcoes}
          idPrefixo="cobranca"
          acaoDireita={
            <button type="button" className="excel" onClick={() => (temFiltroColuna ? setPerguntaColunas("exportar") : exportarExcel(false))} disabled={exportando}>
              {exportando ? "Exportando..." : "Exportar Excel"}
            </button>
          }
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

        {!clientesCarregando && clientes.length === 0 && !temFiltroColuna && !clientesErro && (
          <div className="empty-state">
            <p>{consultado ? "Nenhum cliente encontrado com esses filtros." : "Aplique os filtros para listar clientes."}</p>
          </div>
        )}

        {!clientesCarregando && (clientes.length > 0 || temFiltroColuna) && (
          <>
            <div className="table-wrap">
              <table>
                <thead>
                  <tr>
                    {COLUNAS_CLIENTE.map(([coluna, rotulo, tipo]) => (
                      <ThFiltravel key={coluna} coluna={coluna} rotulo={rotulo} tipo={tipo} ordenacao={clientesSort} controle={controleFiltros} />
                    ))}
                  </tr>
                </thead>
                <tbody>
                  {clientes.length === 0 && (
                    <tr>
                      <td colSpan={COLUNAS_CLIENTE.length} className="text-muted">
                        Nenhum cliente encontrado com esses filtros.
                      </td>
                    </tr>
                  )}
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
