import { useEffect, useRef, useState } from "react";
import { Link } from "react-router-dom";
import {
  api,
  ApiError,
  ClienteCobranca,
  FiltrosCobranca,
  FiltrosLoja,
  Loja,
  RegrasCobranca,
  RelatorioCobranca,
} from "../api";
import { formatBRL, formatCpf, formatData } from "../format";
import MultiSelect from "../components/MultiSelect";
import MatrizTable from "../components/MatrizTable";
import Paginacao from "../components/Paginacao";
import { IconAlert } from "../icons";

const LIMIT = 50;

// Filtros padrão ao entrar na página
const FILTROS_PADRAO: FiltrosCobranca = {
  apenas_primeiro_dia: true,
  somente_regra_whatsapp: true,
  faixa: [],
  cluster: [],
  faixa_compra: [],
  loja: [],
  portador: [],
  status_cliente: [],
  restricao_spc: [],
  regional: [],
  estado: [],
  cluster_inad: [],
  cluster_populacao: [],
  vencimento_de: "",
  vencimento_ate: "",
};

type AbaMatriz = "clientes" | "spc" | "valor";

export default function Cobranca() {
  const [regras, setRegras] = useState<RegrasCobranca | null>(null);
  const [lojas, setLojas] = useState<Loja[]>([]);
  const [filtrosLoja, setFiltrosLoja] = useState<FiltrosLoja | null>(null);
  const [googleIndisponivel, setGoogleIndisponivel] = useState(false);

  // Filtros em edição (ainda não aplicados)
  const [filtrosEdit, setFiltrosEdit] = useState<FiltrosCobranca>(FILTROS_PADRAO);
  // Filtros aplicados (usados nas requisições)
  const [filtrosAplicados, setFiltrosAplicados] = useState<FiltrosCobranca>(FILTROS_PADRAO);

  const [relatorio, setRelatorio] = useState<RelatorioCobranca | null>(null);
  const [relatorioErro, setRelatorioErro] = useState<string | null>(null);
  const [relatorioCarregando, setRelatorioCarregando] = useState(false);

  const [clientes, setClientes] = useState<ClienteCobranca[]>([]);
  const [totalClientes, setTotalClientes] = useState(0);
  const [clientesErro, setClientesErro] = useState<string | null>(null);
  const [clientesCarregando, setClientesCarregando] = useState(false);
  const [offset, setOffset] = useState(0);

  const [abaMatriz, setAbaMatriz] = useState<AbaMatriz>("clientes");
  const [gerandoLeads, setGerandoLeads] = useState(false);
  const [leadsResultado, setLeadsResultado] = useState<{
    criados: number;
    ja_existiam: number;
    sem_celular: number;
  } | null>(null);
  const [leadsErro, setLeadsErro] = useState<string | null>(null);

  const tabelaRef = useRef<HTMLDivElement>(null);

  // Contadores de requisição para evitar respostas obsoletas
  const relReqRef = useRef(0);
  const cliReqRef = useRef(0);

  useEffect(() => {
    api.regrasCobranca().then(setRegras).catch(() => {});
    // Tenta carregar lojas; se 503, marca google indisponível
    api
      .listarLojas()
      .then(setLojas)
      .catch(() => setGoogleIndisponivel(true));
    api
      .filtrosLojas()
      .then(setFiltrosLoja)
      .catch(() => setGoogleIndisponivel(true));
  }, []);

  function formatarErro(e: unknown): string {
    if (e instanceof ApiError && e.status === 503) {
      return e.message.startsWith("ERP") ? e.message : `ERP SETA indisponível: ${e.message}`;
    }
    return e instanceof Error ? e.message : "Erro desconhecido";
  }

  function buscarRelatorio(filtros: FiltrosCobranca) {
    setRelatorioErro(null);
    setRelatorioCarregando(true);
    const seq = ++relReqRef.current;
    api
      .relatorioCobranca(filtros)
      .then((r) => {
        if (seq !== relReqRef.current) return;
        setRelatorio(r);
      })
      .catch((e) => {
        if (seq !== relReqRef.current) return;
        setRelatorioErro(formatarErro(e));
      })
      .finally(() => {
        if (seq === relReqRef.current) setRelatorioCarregando(false);
      });
  }

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
        setClientesErro(formatarErro(e));
      })
      .finally(() => {
        if (seq === cliReqRef.current) setClientesCarregando(false);
      });
  }

  function aplicarFiltros() {
    setOffset(0);
    setFiltrosAplicados(filtrosEdit);
    buscarRelatorio(filtrosEdit);
    buscarClientes(filtrosEdit, 0);
    setLeadsResultado(null);
    setLeadsErro(null);
  }

  function limparFiltros() {
    setFiltrosEdit(FILTROS_PADRAO);
  }

  function mudarPagina(novoOffset: number) {
    setOffset(novoOffset);
    buscarClientes(filtrosAplicados, novoOffset);
  }

  function onCelulaClick(cluster: string, faixa: string) {
    const novos: FiltrosCobranca = {
      ...filtrosEdit,
      cluster: [cluster],
      faixa: [faixa],
    };
    setFiltrosEdit(novos);
    setFiltrosAplicados(novos);
    setOffset(0);
    buscarRelatorio(novos);
    buscarClientes(novos, 0);
    // Rola até a tabela
    setTimeout(() => tabelaRef.current?.scrollIntoView({ behavior: "smooth" }), 100);
  }

  async function gerarLeads() {
    const msg = totalClientes > 0
      ? `Gerar leads para ${totalClientes} cliente(s) com os filtros atuais?`
      : "Gerar leads com os filtros atuais?";
    if (!window.confirm(msg)) return;
    setGerandoLeads(true);
    setLeadsErro(null);
    setLeadsResultado(null);
    try {
      const r = await api.gerarLeads(filtrosAplicados);
      setLeadsResultado(r);
    } catch (e) {
      setLeadsErro(e instanceof Error ? e.message : "Erro ao gerar leads");
    } finally {
      setGerandoLeads(false);
    }
  }

  function elegivel(cluster: string, faixa: string): boolean {
    if (!regras) return true;
    return (regras.faixas_whatsapp[cluster] ?? []).includes(faixa);
  }

  // Opções de loja: quando google disponível, usa lista; senão campo de texto
  const opcoesLoja = lojas.map((l) => ({
    value: l.filial,
    label: l.nome_com_cod ?? l.filial,
  }));

  const opcoesRegional = (filtrosLoja?.regionais ?? []).map((r) => ({ value: r, label: r }));
  const opcoesEstado = (filtrosLoja?.estados ?? []).map((e) => ({ value: e, label: e }));
  const opcoesClusterInad = (filtrosLoja?.clusters_inad ?? []).map((c) => ({ value: c, label: c }));
  const opcoesClusterPop = (filtrosLoja?.clusters_populacao ?? []).map((c) => ({ value: c, label: c }));

  const opcoesFaixa = (regras?.faixas ?? []).map((f) => ({ value: f, label: f }));
  const opcoesCluster = (regras?.clusters ?? []).map((c) => ({ value: c, label: c }));
  const opcoesFaixaCompra = (regras?.faixas_compra ?? []).map((f) => ({ value: f, label: f }));

  const opcoesPortador = [
    { value: "001", label: "001 – TopFama" },
    { value: "114", label: "114 – SYSCO" },
    { value: "216", label: "216 – MJ" },
  ];
  const opcoesStatus = [
    { value: "E", label: "Especial" },
    { value: "A", label: "Ativo" },
    { value: "B", label: "Bloqueado" },
  ];
  const opcoesSpc = [
    { value: "sim", label: "Sim" },
    { value: "nao", label: "Não" },
    { value: "indeterminado", label: "Indeterminado" },
  ];

  function diasAtrasoLabel(dias: number): string {
    if (dias === -1) return "vence amanhã";
    return `${dias} dias`;
  }

  return (
    <div>
      <div className="page-header">
        <div>
          <h2>Cobrança</h2>
          <div className="subtitle">
            Consulte e filtre clientes em atraso no ERP SETA
          </div>
        </div>
      </div>

      {/* Filtros */}
      <div className="card">
        <div className="card-header">
          <h3>Filtros</h3>
          <button
            type="button"
            onClick={gerarLeads}
            disabled={gerandoLeads}
            className="secondary"
          >
            {gerandoLeads ? "Gerando..." : "Gerar leads com estes filtros"}
          </button>
        </div>

        {leadsResultado && (
          <div className="success-box">
            {leadsResultado.criados} leads criados, {leadsResultado.ja_existiam} já existiam,{" "}
            {leadsResultado.sem_celular} sem celular válido.{" "}
            <Link to="/leads">Ver leads →</Link>
          </div>
        )}
        {leadsErro && (
          <div className="error-box">
            <IconAlert width={16} height={16} />
            <span>{leadsErro}</span>
          </div>
        )}

        <div className="form-row" style={{ flexWrap: "wrap", gap: "18px 24px" }}>
          <label className="checkbox-row">
            <input
              type="checkbox"
              checked={!!filtrosEdit.apenas_primeiro_dia}
              onChange={(e) =>
                setFiltrosEdit({ ...filtrosEdit, apenas_primeiro_dia: e.target.checked })
              }
            />
            Somente o primeiro dia da faixa
          </label>
          <label className="checkbox-row">
            <input
              type="checkbox"
              checked={!!filtrosEdit.somente_regra_whatsapp}
              onChange={(e) =>
                setFiltrosEdit({ ...filtrosEdit, somente_regra_whatsapp: e.target.checked })
              }
            />
            Somente clientes da regra WhatsApp
          </label>
        </div>

        <div className="form-row" style={{ flexWrap: "wrap" }}>
          <MultiSelect
            label="Faixa de atraso"
            options={opcoesFaixa}
            value={filtrosEdit.faixa ?? []}
            onChange={(v) => setFiltrosEdit({ ...filtrosEdit, faixa: v })}
          />
          <MultiSelect
            label="Cluster"
            options={opcoesCluster}
            value={filtrosEdit.cluster ?? []}
            onChange={(v) => setFiltrosEdit({ ...filtrosEdit, cluster: v })}
          />
          <MultiSelect
            label="Faixa de compra"
            options={opcoesFaixaCompra}
            value={filtrosEdit.faixa_compra ?? []}
            onChange={(v) => setFiltrosEdit({ ...filtrosEdit, faixa_compra: v })}
          />
        </div>

        <div className="form-row" style={{ flexWrap: "wrap" }}>
          <MultiSelect
            label="Cobradora"
            options={opcoesPortador}
            value={filtrosEdit.portador ?? []}
            onChange={(v) => setFiltrosEdit({ ...filtrosEdit, portador: v })}
          />
          <MultiSelect
            label="Status do cliente"
            options={opcoesStatus}
            value={filtrosEdit.status_cliente ?? []}
            onChange={(v) => setFiltrosEdit({ ...filtrosEdit, status_cliente: v })}
          />
          <MultiSelect
            label="Restrição SPC"
            options={opcoesSpc}
            value={filtrosEdit.restricao_spc ?? []}
            onChange={(v) => setFiltrosEdit({ ...filtrosEdit, restricao_spc: v })}
          />
        </div>

        <div className="form-row" style={{ flexWrap: "wrap" }}>
          {googleIndisponivel ? (
            <div className="field" style={{ flex: "1 1 200px" }}>
              <label htmlFor="loja-texto">Loja (códigos, sep. por vírgula/espaço)</label>
              <input
                id="loja-texto"
                placeholder="ex. 42, C7"
                value={(filtrosEdit.loja ?? []).join(", ")}
                onChange={(e) =>
                  setFiltrosEdit({
                    ...filtrosEdit,
                    loja: e.target.value
                      .split(/[,\s]+/)
                      .map((s) => s.trim())
                      .filter(Boolean),
                  })
                }
              />
            </div>
          ) : (
            <MultiSelect
              label="Loja"
              options={opcoesLoja}
              value={filtrosEdit.loja ?? []}
              onChange={(v) => setFiltrosEdit({ ...filtrosEdit, loja: v })}
            />
          )}
          <MultiSelect
            label="Regional"
            options={opcoesRegional}
            value={filtrosEdit.regional ?? []}
            onChange={(v) => setFiltrosEdit({ ...filtrosEdit, regional: v })}
            disabled={googleIndisponivel}
            placeholder={googleIndisponivel ? "—" : "Todos"}
          />
          <MultiSelect
            label="Estado"
            options={opcoesEstado}
            value={filtrosEdit.estado ?? []}
            onChange={(v) => setFiltrosEdit({ ...filtrosEdit, estado: v })}
            disabled={googleIndisponivel}
            placeholder={googleIndisponivel ? "—" : "Todos"}
          />
        </div>

        <div className="form-row" style={{ flexWrap: "wrap" }}>
          <MultiSelect
            label="Cluster INAD"
            options={opcoesClusterInad}
            value={filtrosEdit.cluster_inad ?? []}
            onChange={(v) => setFiltrosEdit({ ...filtrosEdit, cluster_inad: v })}
            disabled={googleIndisponivel}
            placeholder={googleIndisponivel ? "—" : "Todos"}
          />
          <MultiSelect
            label="Cluster de população"
            options={opcoesClusterPop}
            value={filtrosEdit.cluster_populacao ?? []}
            onChange={(v) => setFiltrosEdit({ ...filtrosEdit, cluster_populacao: v })}
            disabled={googleIndisponivel}
            placeholder={googleIndisponivel ? "—" : "Todos"}
          />
          <div className="field" style={{ flex: "1 1 160px" }}>
            <label htmlFor="venc-de">Vencimento de</label>
            <input
              id="venc-de"
              type="date"
              value={filtrosEdit.vencimento_de ?? ""}
              onChange={(e) => setFiltrosEdit({ ...filtrosEdit, vencimento_de: e.target.value })}
            />
          </div>
          <div className="field" style={{ flex: "1 1 160px" }}>
            <label htmlFor="venc-ate">Vencimento até</label>
            <input
              id="venc-ate"
              type="date"
              value={filtrosEdit.vencimento_ate ?? ""}
              onChange={(e) => setFiltrosEdit({ ...filtrosEdit, vencimento_ate: e.target.value })}
            />
          </div>
        </div>

        {googleIndisponivel && (
          <div className="field-hint" style={{ marginBottom: 8 }}>
            Conecte o Google em{" "}
            <Link to="/configuracoes">Configurações</Link> para filtrar por regional, estado e
            clusters de loja.
          </div>
        )}

        <div className="actions-row">
          <button type="button" onClick={aplicarFiltros}>
            Aplicar filtros
          </button>
          <button type="button" className="secondary" onClick={limparFiltros}>
            Limpar
          </button>
        </div>
      </div>

      {/* Matriz cluster × faixa */}
      <div className="card">
        <div className="card-header">
          <h3>Visão cluster × faixa</h3>
          <div style={{ display: "flex", gap: 8 }}>
            {(["clientes", "spc", "valor"] as AbaMatriz[]).map((aba) => {
              if (aba === "valor" && !relatorio?.valor_em_aberto) return null;
              const rotulos = {
                clientes: "Clientes",
                spc: "Clientes com restrição no SPC",
                valor: "Valor em aberto",
              };
              return (
                <button
                  key={aba}
                  type="button"
                  className={abaMatriz === aba ? "" : "secondary"}
                  onClick={() => setAbaMatriz(aba)}
                >
                  {rotulos[aba]}
                </button>
              );
            })}
          </div>
        </div>

        {relatorioErro && (
          <div className="error-box">
            <IconAlert width={16} height={16} />
            <span>{relatorioErro}</span>
          </div>
        )}

        {relatorioCarregando && (
          <div className="loading-state">Carregando matriz...</div>
        )}

        {relatorio && !relatorioCarregando && (
          <MatrizTable
            clusters={relatorio.clusters}
            faixas={relatorio.faixas}
            matriz={
              abaMatriz === "spc"
                ? (relatorio.quantidade_com_restricao_spc as {
                    celulas: Record<string, Record<string, number | string>>;
                    total_por_cluster: Record<string, number | string>;
                    total_por_faixa: Record<string, number | string>;
                    total: number | string;
                  })
                : abaMatriz === "valor" && relatorio.valor_em_aberto
                ? (relatorio.valor_em_aberto as {
                    celulas: Record<string, Record<string, number | string>>;
                    total_por_cluster: Record<string, number | string>;
                    total_por_faixa: Record<string, number | string>;
                    total: number | string;
                  })
                : (relatorio.quantidade as {
                    celulas: Record<string, Record<string, number | string>>;
                    total_por_cluster: Record<string, number | string>;
                    total_por_faixa: Record<string, number | string>;
                    total: number | string;
                  })
            }
            formato={abaMatriz === "valor" ? formatBRL : (v) => String(v)}
            elegivel={elegivel}
            onCelulaClick={onCelulaClick}
          />
        )}

        {!relatorio && !relatorioCarregando && !relatorioErro && (
          <div className="empty-state">
            <p>Aplique os filtros para ver a matriz cluster × faixa.</p>
          </div>
        )}
      </div>

      {/* Tabela de clientes */}
      <div className="card" ref={tabelaRef}>
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
          <div className="loading-state">
            Consultando o ERP SETA — isso pode levar até 45 segundos...
          </div>
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
            <Paginacao
              total={totalClientes}
              limit={LIMIT}
              offset={offset}
              onChange={mudarPagina}
            />
          </>
        )}
      </div>
    </div>
  );
}
