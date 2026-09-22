import { useEffect, useRef, useState } from "react";
import { Link } from "react-router-dom";
import {
  api,
  FiltrosLeads,
  FiltrosLoja,
  Lead,
  Loja,
  RegrasCobranca,
} from "../api";
import { formatBRL, formatCpf, formatData, formatDataHora } from "../format";
import MultiSelect from "../components/MultiSelect";
import Paginacao from "../components/Paginacao";
import { IconAlert, IconList } from "../icons";

const LIMIT = 50;

const FILTROS_PADRAO: FiltrosLeads = {
  busca: "",
  status: undefined,
  com_celular: undefined,
  faixa: [],
  cluster: [],
  loja: [],
  regional: [],
  estado: [],
  cluster_inad: [],
  cluster_populacao: [],
  criado_de: "",
  criado_ate: "",
};

export default function Leads() {
  const [regras, setRegras] = useState<RegrasCobranca | null>(null);
  const [lojas, setLojas] = useState<Loja[]>([]);
  const [filtrosLoja, setFiltrosLoja] = useState<FiltrosLoja | null>(null);
  const [googleIndisponivel, setGoogleIndisponivel] = useState(false);

  const [filtrosEdit, setFiltrosEdit] = useState<FiltrosLeads>(FILTROS_PADRAO);
  const [filtrosAplicados, setFiltrosAplicados] = useState<FiltrosLeads>(FILTROS_PADRAO);

  const [leads, setLeads] = useState<Lead[]>([]);
  const [total, setTotal] = useState(0);
  const [offset, setOffset] = useState(0);
  const [carregando, setCarregando] = useState(false);
  const [erro, setErro] = useState<string | null>(null);

  const [selecionados, setSelecionados] = useState<Set<string>>(new Set());
  const [marcandoCobrados, setMarcandoCobrados] = useState(false);
  const [excluindo, setExcluindo] = useState(false);
  const [sucesso, setSucesso] = useState<string | null>(null);

  const reqRef = useRef(0);

  useEffect(() => {
    api.regrasCobranca().then(setRegras).catch(() => {});
    api
      .listarLojas()
      .then(setLojas)
      .catch(() => setGoogleIndisponivel(true));
    api
      .filtrosLojas()
      .then(setFiltrosLoja)
      .catch(() => setGoogleIndisponivel(true));
    buscar(FILTROS_PADRAO, 0);
  }, []);

  function buscar(filtros: FiltrosLeads, novoOffset: number) {
    setErro(null);
    setCarregando(true);
    const params: FiltrosLeads & { limit: number; offset: number } = {
      ...filtros,
      limit: LIMIT,
      offset: novoOffset,
    };
    const seq = ++reqRef.current;
    api
      .listarLeads(params)
      .then((r) => {
        if (seq !== reqRef.current) return;
        setLeads(r.itens);
        setTotal(r.total);
        setSelecionados(new Set());
      })
      .catch((e) => {
        if (seq !== reqRef.current) return;
        setErro(e.message);
      })
      .finally(() => {
        if (seq === reqRef.current) setCarregando(false);
      });
  }

  function aplicar() {
    setFiltrosAplicados(filtrosEdit);
    setOffset(0);
    setSucesso(null);
    buscar(filtrosEdit, 0);
  }

  function limpar() {
    setFiltrosEdit(FILTROS_PADRAO);
  }

  function mudarPagina(novoOffset: number) {
    setOffset(novoOffset);
    buscar(filtrosAplicados, novoOffset);
  }

  function toggleSelecionado(id: string) {
    setSelecionados((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  }

  function toggleTodaPagina() {
    if (leads.every((l) => selecionados.has(l.id))) {
      setSelecionados((prev) => {
        const next = new Set(prev);
        leads.forEach((l) => next.delete(l.id));
        return next;
      });
    } else {
      setSelecionados((prev) => {
        const next = new Set(prev);
        leads.forEach((l) => next.add(l.id));
        return next;
      });
    }
  }

  async function marcarCobrados() {
    const ids = Array.from(selecionados);
    if (!window.confirm(`Marcar ${ids.length} lead(s) como enviado(s)?`)) return;
    setMarcandoCobrados(true);
    setErro(null);
    setSucesso(null);
    try {
      const r = await api.marcarLeadsCobrados(ids);
      setSucesso(`${r.atualizados} lead(s) marcado(s) como enviado(s).`);
      setSelecionados(new Set());
      buscar(filtrosAplicados, offset);
    } catch (e) {
      setErro(e instanceof Error ? e.message : "Erro ao marcar como enviados");
    } finally {
      setMarcandoCobrados(false);
    }
  }

  async function excluirLeads() {
    const ids = Array.from(selecionados);
    const mensagem =
      ids.length > 0
        ? `Excluir ${ids.length} lead(s) selecionado(s)? Só os que ainda não foram enviados serão excluídos.`
        : `Excluir TODOS os leads que casam com os filtros aplicados? Só os que ainda não foram enviados serão excluídos.`;
    if (!window.confirm(mensagem)) return;
    setExcluindo(true);
    setErro(null);
    setSucesso(null);
    try {
      const r = await api.excluirLeads(filtrosAplicados, ids);
      let msg = `${r.excluidos} lead(s) excluído(s).`;
      if (r.ignorados_ja_enviados > 0) {
        msg += ` ${r.ignorados_ja_enviados} já estavam enviados e foram mantidos.`;
      }
      setSucesso(msg);
      setSelecionados(new Set());
      setOffset(0);
      buscar(filtrosAplicados, 0);
    } catch (e) {
      setErro(e instanceof Error ? e.message : "Erro ao excluir leads");
    } finally {
      setExcluindo(false);
    }
  }

  const opcoesFaixa = (regras?.faixas ?? []).map((f) => ({ value: f, label: f }));
  const opcoesCluster = (regras?.clusters ?? []).map((c) => ({ value: c, label: c }));
  const opcoesLoja = lojas.map((l) => ({
    value: l.filial,
    label: l.nome_com_cod ?? l.filial,
  }));
  const opcoesRegional = (filtrosLoja?.regionais ?? []).map((r) => ({ value: r, label: r }));
  const opcoesEstado = (filtrosLoja?.estados ?? []).map((e) => ({ value: e, label: e }));
  const opcoesClusterInad = (filtrosLoja?.clusters_inad ?? []).map((c) => ({ value: c, label: c }));
  const opcoesClusterPop = (filtrosLoja?.clusters_populacao ?? []).map((c) => ({ value: c, label: c }));

  const todaPaginaSelecionada = leads.length > 0 && leads.every((l) => selecionados.has(l.id));

  return (
    <div>
      <div className="page-header">
        <div>
          <h2>Leads</h2>
          <div className="subtitle">Clientes gerados para cobrança por WhatsApp</div>
        </div>
      </div>

      {/* Filtros */}
      <div className="card">
        <div className="card-header">
          <h3>Filtros</h3>
        </div>

        <div className="form-row" style={{ flexWrap: "wrap" }}>
          <div className="field" style={{ flex: "1 1 220px" }}>
            <label htmlFor="busca-lead">Busca (nome, código ou CPF)</label>
            <input
              id="busca-lead"
              value={filtrosEdit.busca ?? ""}
              onChange={(e) => setFiltrosEdit({ ...filtrosEdit, busca: e.target.value })}
              placeholder="Digite para buscar..."
            />
          </div>
          <div className="field" style={{ flex: "0 1 160px" }}>
            <label htmlFor="status-lead">Status</label>
            <select
              id="status-lead"
              value={filtrosEdit.status ?? ""}
              onChange={(e) =>
                setFiltrosEdit({
                  ...filtrosEdit,
                  status: (e.target.value as "novo" | "cobrado") || undefined,
                })
              }
            >
              <option value="">Todos</option>
              <option value="novo">Novo</option>
              <option value="cobrado">Enviado</option>
            </select>
          </div>
          <div className="field" style={{ flex: "0 1 160px" }}>
            <label htmlFor="celular-lead">Celular</label>
            <select
              id="celular-lead"
              value={
                filtrosEdit.com_celular === undefined
                  ? ""
                  : filtrosEdit.com_celular
                  ? "true"
                  : "false"
              }
              onChange={(e) =>
                setFiltrosEdit({
                  ...filtrosEdit,
                  com_celular:
                    e.target.value === "" ? undefined : e.target.value === "true",
                })
              }
            >
              <option value="">Todos</option>
              <option value="true">Com celular</option>
              <option value="false">Sem celular</option>
            </select>
          </div>
        </div>

        <div className="form-row" style={{ flexWrap: "wrap" }}>
          <MultiSelect
            label="Faixa"
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
        </div>

        <div className="form-row" style={{ flexWrap: "wrap" }}>
          {googleIndisponivel ? (
            <div className="field" style={{ flex: "1 1 200px" }}>
              <label htmlFor="loja-lead-texto">Loja (códigos, sep. por vírgula/espaço)</label>
              <input
                id="loja-lead-texto"
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
          <div className="field" style={{ flex: "0 1 160px" }}>
            <label htmlFor="criado-de">Criado de</label>
            <input
              id="criado-de"
              type="date"
              value={filtrosEdit.criado_de ?? ""}
              onChange={(e) => setFiltrosEdit({ ...filtrosEdit, criado_de: e.target.value })}
            />
          </div>
          <div className="field" style={{ flex: "0 1 160px" }}>
            <label htmlFor="criado-ate">Criado até</label>
            <input
              id="criado-ate"
              type="date"
              value={filtrosEdit.criado_ate ?? ""}
              onChange={(e) => setFiltrosEdit({ ...filtrosEdit, criado_ate: e.target.value })}
            />
          </div>
        </div>

        {googleIndisponivel && (
          <div className="field-hint" style={{ marginBottom: 8 }}>
            Conecte o Google em <Link to="/configuracoes">Configurações</Link> para filtrar por
            regional, estado e clusters de loja.
          </div>
        )}

        <div className="actions-row">
          <button type="button" onClick={aplicar}>
            Aplicar filtros
          </button>
          <button type="button" className="secondary" onClick={limpar}>
            Limpar
          </button>
        </div>
      </div>

      {/* Barra de ações */}
      <div className="actions-row" style={{ marginBottom: 12 }}>
        {selecionados.size > 0 && (
          <button type="button" onClick={marcarCobrados} disabled={marcandoCobrados}>
            {marcandoCobrados
              ? "Marcando..."
              : `Marcar como enviados (${selecionados.size})`}
          </button>
        )}
        <button type="button" className="danger" onClick={excluirLeads} disabled={excluindo}>
          {excluindo
            ? "Excluindo..."
            : selecionados.size > 0
            ? `Excluir selecionados (${selecionados.size})`
            : "Excluir todos (filtrados)"}
        </button>
      </div>

      {erro && (
        <div className="error-box">
          <IconAlert width={16} height={16} />
          <span>{erro}</span>
        </div>
      )}
      {sucesso && <div className="success-box">{sucesso}</div>}

      {/* Tabela */}
      <div className="card">
        <div className="card-header">
          <h3>
            Leads
            {total > 0 && (
              <span className="text-muted" style={{ fontWeight: 400, marginLeft: 8 }}>
                ({total.toLocaleString("pt-BR")})
              </span>
            )}
          </h3>
        </div>

        {carregando && <div className="loading-state">Carregando...</div>}

        {!carregando && leads.length === 0 && !erro && (
          <div className="empty-state">
            <IconList width={28} height={28} />
            <div className="title">Nenhum lead encontrado</div>
            <p>
              Gere leads a partir da tela de{" "}
              <Link to="/cobranca">Cobrança</Link>.
            </p>
          </div>
        )}

        {!carregando && leads.length > 0 && (
          <>
            <div className="table-wrap">
              <table>
                <thead>
                  <tr>
                    <th scope="col">
                      <input
                        type="checkbox"
                        checked={todaPaginaSelecionada}
                        onChange={toggleTodaPagina}
                        aria-label="Selecionar todos da página"
                      />
                    </th>
                    <th scope="col">Código</th>
                    <th scope="col">CPF</th>
                    <th scope="col">Nome</th>
                    <th scope="col">Vencimento</th>
                    <th scope="col">Valor</th>
                    <th scope="col">Parcelas</th>
                    <th scope="col">Atraso</th>
                    <th scope="col">Faixa</th>
                    <th scope="col">Cluster</th>
                    <th scope="col">Status</th>
                    <th scope="col">Enviado em</th>
                  </tr>
                </thead>
                <tbody>
                  {leads.map((l) => (
                    <tr key={l.id}>
                      <td>
                        <input
                          type="checkbox"
                          checked={selecionados.has(l.id)}
                          onChange={() => toggleSelecionado(l.id)}
                          aria-label={`Selecionar ${l.nome}`}
                        />
                      </td>
                      <td className="cell-strong">{l.codigo_cliente}</td>
                      <td className="text-muted">{formatCpf(l.cpf)}</td>
                      <td>
                        {l.nome}
                        {l.spc_restricao === "sim" && (
                          <span className="badge rejected" style={{ marginLeft: 6 }}>
                            SPC
                          </span>
                        )}
                      </td>
                      <td>{formatData(l.vencimento_mais_antigo)}</td>
                      <td>{formatBRL(l.valor_cobrar)}</td>
                      <td>{l.qtd_parcelas}</td>
                      <td>
                        {l.dias_atraso === -1 ? "vence amanhã" : `${l.dias_atraso} dias`}
                      </td>
                      <td>{l.faixa}</td>
                      <td>{l.cluster}</td>
                      <td>
                        <span
                          className={`badge ${l.status === "cobrado" ? "approved" : "pending"}`}
                        >
                          {l.status === "cobrado" ? "Enviado" : "Novo"}
                        </span>
                      </td>
                      <td className="text-muted">{formatDataHora(l.cobrado_em)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
            <Paginacao total={total} limit={LIMIT} offset={offset} onChange={mudarPagina} />
          </>
        )}
      </div>
    </div>
  );
}
