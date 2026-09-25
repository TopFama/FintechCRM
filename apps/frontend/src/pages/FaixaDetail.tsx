import { useEffect, useMemo, useState } from "react";
import { Link, useParams } from "react-router-dom";
import {
  api,
  Faixa,
  Lead,
  QueueItem,
  Template,
  UploadFieldMapping,
  UploadResult,
} from "../api";
import {
  IconAlert,
  IconInbox,
  IconRefresh,
  IconUsers,
} from "../icons";
import EnviosFaixa from "../components/EnviosFaixa";
import Paginacao, { LIMIT_OPCOES_PADRAO } from "../components/Paginacao";
import SortableTh from "../components/SortableTh";
import { SortDirection, useSort } from "../sort";

type ColunaFila = "codigo_cliente" | "nome" | "cpf" | "celular" | "valor" | "status" | "error_message";
type ColunaLeadFaixa = "nome" | "celular" | "cluster" | "dias_atraso" | "valor_cobrar" | "status";

const QUEUE_POLL_MS = 4000;

const STATUS_FILA: Record<string, string> = {
  pending: "pendente",
  reserved: "enviando",
  sent: "enviado",
  error: "erro",
  invalid_phone: "telefone inválido",
  cancelled: "parado",
};

const NO_COLUMN = "";

function pickDefault(columns: string[], previous: string | null | undefined): string {
  if (previous && columns.includes(previous)) return previous;
  return NO_COLUMN;
}

export default function FaixaDetail() {
  const { id } = useParams<{ id: string }>();
  const [faixa, setFaixa] = useState<Faixa | null>(null);
  const [queue, setQueue] = useState<QueueItem[]>([]);
  const filaSort = useSort<ColunaFila>(null, (chave, dir) => {
    setQueueOffset(0);
    loadQueue(0, queueLimit, chave, dir);
  });
  const [queueTotal, setQueueTotal] = useState(0);
  const [queueOffset, setQueueOffset] = useState(0);
  const [queueLimit, setQueueLimit] = useState(LIMIT_OPCOES_PADRAO[1]);
  const [error, setError] = useState<string | null>(null);
  const [faixaErro, setFaixaErro] = useState<string | null>(null);
  const [lastQueueUpdate, setLastQueueUpdate] = useState<Date | null>(null);


  // Leads gerados para esta mesma faixa de atraso (pela Cobrança ou pela
  // extração automática), só pra dar visibilidade de quem existe.
  const [leads, setLeads] = useState<Lead[]>([]);
  const leadsFaixaSort = useSort<ColunaLeadFaixa>(null, (chave, dir) => {
    setLeadsOffset(0);
    if (faixa) loadLeads(faixa.name, 0, leadsLimit, chave, dir);
  });
  const [leadsTotal, setLeadsTotal] = useState(0);
  const [leadsOffset, setLeadsOffset] = useState(0);
  const [leadsLimit, setLeadsLimit] = useState(LIMIT_OPCOES_PADRAO[1]);
  const [leadsLoading, setLeadsLoading] = useState(false);

  function loadFaixa() {
    if (!id) return;
    api
      .getFaixa(id)
      .then((f) => {
        setFaixa(f);
        setFaixaErro(null);
      })
      .catch((e) => setFaixaErro(e.message));
  }

  function loadQueue(
    novoOffset: number = queueOffset,
    novoLimit: number = queueLimit,
    sortBy: ColunaFila | null = filaSort.sortKey,
    sortDir: SortDirection = filaSort.sortDir
  ) {
    if (!id) return;
    api
      .listQueue(id, { limit: novoLimit, offset: novoOffset, sort_by: sortBy ?? undefined, sort_dir: sortDir })
      .then((r) => {
        setQueue(r.itens);
        setQueueTotal(r.total);
        setLastQueueUpdate(new Date());
      })
      .catch((e) => setError(e.message));
  }

  function mudarPaginaQueue(novoOffset: number) {
    setQueueOffset(novoOffset);
    loadQueue(novoOffset, queueLimit);
  }

  function mudarLimiteQueue(novoLimit: number) {
    setQueueLimit(novoLimit);
    setQueueOffset(0);
    loadQueue(0, novoLimit);
  }

  function loadLeads(
    nomeFaixa: string,
    novoOffset: number = leadsOffset,
    novoLimit: number = leadsLimit,
    sortBy: ColunaLeadFaixa | null = leadsFaixaSort.sortKey,
    sortDir: SortDirection = leadsFaixaSort.sortDir
  ) {
    setLeadsLoading(true);
    api
      .listarLeads({ faixa: [nomeFaixa], limit: novoLimit, offset: novoOffset, sort_by: sortBy ?? undefined, sort_dir: sortDir })
      .then((r) => {
        setLeads(r.itens);
        setLeadsTotal(r.total);
      })
      .catch((e) => setError(e.message))
      .finally(() => setLeadsLoading(false));
  }

  function mudarPaginaLeads(novoOffset: number) {
    setLeadsOffset(novoOffset);
    if (faixa) loadLeads(faixa.name, novoOffset, leadsLimit);
  }

  function mudarLimiteLeads(novoLimit: number) {
    setLeadsLimit(novoLimit);
    setLeadsOffset(0);
    if (faixa) loadLeads(faixa.name, 0, novoLimit);
  }

  useEffect(() => {
    if (faixa) loadLeads(faixa.name, 0, leadsLimit);
    setLeadsOffset(0);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [faixa?.name]);

  useEffect(() => {
    loadFaixa();
    loadQueue(0, queueLimit);
    setQueueOffset(0);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [id]);

  // Acompanhamento da fila em tempo (quase) real: revalida periodicamente
  // enquanto a tela estiver aberta.
  useEffect(() => {
    if (!id) return;
    const interval = setInterval(() => loadQueue(queueOffset, queueLimit), QUEUE_POLL_MS);
    return () => clearInterval(interval);
    // Ordenação entra nas dependências: senão o intervalo usa a ordenação antiga
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [id, queueOffset, queueLimit, filaSort.sortKey, filaSort.sortDir]);

  // Templates distintos entre os envios ATIVOS — o que a planilha subida
  // precisa alimentar, já que qualquer um pode processar um item da fila.
  const templatesAtivos = useMemo(() => {
    const porId = new Map<string, Template>();
    (faixa?.envios || []).forEach((e) => {
      if (e.active) porId.set(e.template_id, e.template);
    });
    return Array.from(porId.values());
  }, [faixa]);

  const algumAgendado = (faixa?.envios || []).some((e) => e.dispatch_config?.active);


  if (!faixa) {
    if (!faixaErro) return <div className="loading-state">Carregando faixa...</div>;
    return (
      <div>
        <Link to="/faixas" className="back-link">
          ← Faixas de cobrança
        </Link>
        <div className="error-box">
          <IconAlert width={16} height={16} />
          <span>Não foi possível abrir a faixa: {faixaErro}</span>
        </div>
      </div>
    );
  }

  return (
    <div>
      {faixa.campanha_id ? (
        <Link to={`/campanhas/${faixa.campanha_id}`} className="back-link">
          ← Campanha
        </Link>
      ) : faixa.remarketing_segmento ? (
        <Link to="/campanhas?aba=remarketing" className="back-link">
          ← Remarketing
        </Link>
      ) : (
        <Link to="/faixas" className="back-link">
          ← Faixas de cobrança
        </Link>
      )}
      <div className="page-header">
        <div>
          <h2>{faixa.name}</h2>
          {faixa.descricao && <p className="faixa-descricao">{faixa.descricao}</p>}
          <div className="subtitle">
            {faixa.envios.length === 0
              ? "Sem número/template atribuído"
              : `${templatesAtivos.length} template(s) ativo(s) · ${faixa.envios.length} número(s)`}
          </div>
        </div>
        <span className={`status-pill ${algumAgendado ? "on" : "off"}`}>{algumAgendado ? "Agendado" : "Pausado"}</span>
      </div>

      {error && (
        <div className="error-box">
          <IconAlert width={16} height={16} />
          <span>{error}</span>
        </div>
      )}

      <EnviosFaixa faixa={faixa} onAlterado={loadFaixa} />

      <div className="card">
        <div className="card-header">
          <h3>Fila desta faixa</h3>
          <span className="text-faint" style={{ display: "inline-flex", alignItems: "center", gap: 5 }}>
            <IconRefresh width={13} height={13} />
            {lastQueueUpdate ? `atualizado ${lastQueueUpdate.toLocaleTimeString("pt-BR")}` : "atualizando..."}
          </span>
        </div>
        {queue.length === 0 ? (
          <div className="empty-state">
            <IconInbox width={28} height={28} />
            <div className="title">Fila vazia</div>
            <p>Suba uma planilha desta faixa na aba <Link to="/cobranca">Cobrança</Link> para adicionar clientes.</p>
          </div>
        ) : (
          <div className="table-wrap">
            <table>
              <thead>
                <tr>
                  {(
                    [
                      ["codigo_cliente", "Código"],
                      ["nome", "Nome"],
                      ["cpf", "CPF"],
                      ["celular", "Celular"],
                      ["valor", "Valor"],
                      ["status", "Status"],
                      ["error_message", "Erro"],
                    ] as [ColunaFila, string][]
                  ).map(([coluna, rotulo]) => (
                    <SortableTh key={coluna} active={filaSort.sortKey === coluna} dir={filaSort.sortDir} onSort={() => filaSort.toggleSort(coluna)}>
                      {rotulo}
                    </SortableTh>
                  ))}
                </tr>
              </thead>
              <tbody>
                {queue.map((q) => (
                  <tr key={q.id}>
                    <td className="cell-strong">{q.codigo_cliente}</td>
                    <td>{q.nome || "—"}</td>
                    <td className="text-muted">{q.cpf || "—"}</td>
                    <td>{q.celular}</td>
                    <td className="text-muted">{q.valor || "—"}</td>
                    <td>
                      <span className={`badge ${q.status}`}>{STATUS_FILA[q.status] ?? q.status}</span>
                    </td>
                    <td className="text-faint">{q.error_message || "—"}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
        {queueTotal > 0 && (
          <Paginacao total={queueTotal} limit={queueLimit} offset={queueOffset} onChange={mudarPaginaQueue} onLimitChange={mudarLimiteQueue} />
        )}
      </div>

      {faixa.remarketing_segmento || faixa.campanha_id ? (
        <div className="card">
          <div className="card-header">
            <h3>De onde vêm os clientes</h3>
          </div>
          {faixa.campanha_id ? (
            <p className="card-subtitle">
              Esta fila é de uma campanha e não recebe planilha. Os filtros, o dia e o período ficam na{" "}
              <Link to={`/campanhas/${faixa.campanha_id}`}>tela da campanha</Link>.
            </p>
          ) : (
            <p className="card-subtitle">
              Esta faixa não recebe planilha. Todo dia de disparo o sistema busca no Renegocie quem se encaixa aqui e
              coloca na fila acima. Os filtros ficam em{" "}
              <Link to="/campanhas?aba=remarketing">Campanhas → Remarketing</Link>.
            </p>
          )}
        </div>
      ) : (
      <div className="card">
        <div className="card-header">
          <h3>Leads gerados nesta faixa de atraso</h3>
        </div>
        <p className="card-subtitle">
          Clientes da faixa de atraso "{faixa.name}" enviados para a fila pela tela Cobrança ou pela extração
          automática.
        </p>
        {leadsLoading ? (
          <div className="loading-state">Carregando leads...</div>
        ) : leads.length === 0 ? (
          <div className="empty-state">
            <IconUsers width={28} height={28} />
            <div className="title">Nenhum lead gerado para esta faixa</div>
            <p>
              Em <Link to="/cobranca">Cobrança</Link>, filtre por esta faixa de atraso e clique em "Enviar para fila de
              cobrança".
            </p>
          </div>
        ) : (
          <>
            <div className="table-wrap">
              <table>
                <thead>
                  <tr>
                    {(
                      [
                        ["nome", "Nome"],
                        ["celular", "Celular"],
                        ["cluster", "Cluster"],
                        ["dias_atraso", "Dias de atraso"],
                        ["valor_cobrar", "Valor a cobrar"],
                        ["status", "Status"],
                      ] as [ColunaLeadFaixa, string][]
                    ).map(([coluna, rotulo]) => (
                      <SortableTh
                        key={coluna}
                        active={leadsFaixaSort.sortKey === coluna}
                        dir={leadsFaixaSort.sortDir}
                        onSort={() => leadsFaixaSort.toggleSort(coluna)}
                      >
                        {rotulo}
                      </SortableTh>
                    ))}
                  </tr>
                </thead>
                <tbody>
                  {leads.map((l) => (
                    <tr key={l.id}>
                      <td className="cell-strong">{l.nome || "—"}</td>
                      <td>{l.celular || "—"}</td>
                      <td className="text-muted">{l.cluster}</td>
                      <td>{l.dias_atraso}</td>
                      <td className="text-muted">{l.valor_cobrar}</td>
                      <td>
                        <span className={`status-pill ${l.status === "cobrado" ? "on" : "off"}`}>{l.status}</span>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
            <Paginacao total={leadsTotal} limit={leadsLimit} offset={leadsOffset} onChange={mudarPaginaLeads} onLimitChange={mudarLimiteLeads} />
          </>
        )}
      </div>
      )}
    </div>
  );
}
