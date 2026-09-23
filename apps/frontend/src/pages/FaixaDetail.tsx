import { useEffect, useMemo, useRef, useState } from "react";
import { Link, useParams } from "react-router-dom";
import {
  api,
  CampoCliente,
  Faixa,
  FaixaEnvio,
  FaixaVariableMappingIn,
  Lead,
  QueueItem,
  Template,
  UploadFieldMapping,
  UploadResult,
  WhatsappNumber,
} from "../api";
import {
  IconAlert,
  IconCheckCircle,
  IconDownload,
  IconEye,
  IconInbox,
  IconPlus,
  IconRefresh,
  IconTrash,
  IconUpload,
  IconUsers,
} from "../icons";
import Paginacao, { LIMIT_OPCOES_PADRAO } from "../components/Paginacao";
import SortableTh from "../components/SortableTh";
import { ordenarPor, useSort } from "../sort";

type ColunaFila = "codigo_cliente" | "nome" | "cpf" | "celular" | "valor" | "status" | "error_message";
type ColunaLeadFaixa = "nome" | "celular" | "cluster" | "dias_atraso" | "valor_cobrar" | "status";
type MapeamentoEdicao = { fonte_tipo: "coluna" | "campo_cliente"; valor: string };

const QUEUE_POLL_MS = 4000;

const NO_COLUMN = "";

function pickDefault(columns: string[], previous: string | null | undefined): string {
  if (previous && columns.includes(previous)) return previous;
  return NO_COLUMN;
}

export default function FaixaDetail() {
  const { id } = useParams<{ id: string }>();
  const [faixa, setFaixa] = useState<Faixa | null>(null);
  const [queue, setQueue] = useState<QueueItem[]>([]);
  const filaSort = useSort<ColunaFila>();
  const filaOrdenada = ordenarPor(
    queue,
    filaSort.sortKey === "valor"
      ? (q: QueueItem) => (q.valor != null ? Number(q.valor) : null)
      : filaSort.sortKey
      ? (q: QueueItem) => q[filaSort.sortKey as ColunaFila]
      : null,
    filaSort.sortDir
  );
  const [queueTotal, setQueueTotal] = useState(0);
  const [queueOffset, setQueueOffset] = useState(0);
  const [queueLimit, setQueueLimit] = useState(LIMIT_OPCOES_PADRAO[1]);
  const [error, setError] = useState<string | null>(null);
  const [lastQueueUpdate, setLastQueueUpdate] = useState<Date | null>(null);

  // Números e templates atribuídos à faixa — cada par (FaixaEnvio) cobra em
  // paralelo, com seu próprio agendamento (configurado em Configurações →
  // Disparo). Aqui só se atribui/edita/remove o par número+template e o
  // mapeamento de variáveis dele.
  const [templates, setTemplates] = useState<Template[]>([]);
  const [numbers, setNumbers] = useState<WhatsappNumber[]>([]);
  const [campos, setCampos] = useState<CampoCliente[]>([]);
  const [mostrarFormEnvio, setMostrarFormEnvio] = useState(false);
  const [envioEditandoId, setEnvioEditandoId] = useState<string | null>(null);
  const [formNumberId, setFormNumberId] = useState("");
  const [formTemplateId, setFormTemplateId] = useState("");
  const [formAtivo, setFormAtivo] = useState(true);
  const [formMappings, setFormMappings] = useState<Record<string, MapeamentoEdicao>>({});
  const [mostrarPreviewEnvio, setMostrarPreviewEnvio] = useState(false);
  const [salvandoEnvio, setSalvandoEnvio] = useState(false);
  const [excluindoEnvioId, setExcluindoEnvioId] = useState<string | null>(null);
  const [envioMsg, setEnvioMsg] = useState<string | null>(null);

  // Leads gerados (Cobrança → Leads) para esta mesma faixa de atraso, só
  // pra dar visibilidade de quem existe antes de decidir subir a planilha.
  const [leads, setLeads] = useState<Lead[]>([]);
  const leadsFaixaSort = useSort<ColunaLeadFaixa>();
  const leadsOrdenados = ordenarPor(
    leads,
    leadsFaixaSort.sortKey === "valor_cobrar"
      ? (l: Lead) => Number(l.valor_cobrar)
      : leadsFaixaSort.sortKey
      ? (l: Lead) => l[leadsFaixaSort.sortKey as ColunaLeadFaixa]
      : null,
    leadsFaixaSort.sortDir
  );
  const [leadsTotal, setLeadsTotal] = useState(0);
  const [leadsOffset, setLeadsOffset] = useState(0);
  const [leadsLimit, setLeadsLimit] = useState(LIMIT_OPCOES_PADRAO[1]);
  const [leadsLoading, setLeadsLoading] = useState(false);

  function loadFaixa() {
    if (!id) return;
    api
      .getFaixa(id)
      .then(setFaixa)
      .catch((e) => setError(e.message));
  }

  function loadQueue(novoOffset: number = queueOffset, novoLimit: number = queueLimit) {
    if (!id) return;
    api
      .listQueue(id, { limit: novoLimit, offset: novoOffset })
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

  function loadLeads(nomeFaixa: string, novoOffset: number = leadsOffset, novoLimit: number = leadsLimit) {
    setLeadsLoading(true);
    api
      .listarLeads({ faixa: [nomeFaixa], limit: novoLimit, offset: novoOffset })
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
    api.listTemplates().then(setTemplates).catch(() => undefined);
    api.listNumbers().then(setNumbers).catch(() => undefined);
    api.listCamposCliente().then(setCampos).catch(() => undefined);
  }, []);

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
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [id, queueOffset, queueLimit]);

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

  function mapeamentosParaEdicao(templateId: string): Record<string, MapeamentoEdicao> {
    const template = templates.find((t) => t.id === templateId);
    if (!template) return {};
    const existentes = faixa?.variable_mappings.filter((m) => m.template_id === templateId) || [];
    const result: Record<string, MapeamentoEdicao> = {};
    for (const v of template.variables) {
      const existente = existentes.find((m) => m.template_variable_id === v.id);
      if (existente) {
        result[v.id] = {
          fonte_tipo: existente.fonte_tipo === "campo_cliente" ? "campo_cliente" : "coluna",
          valor: existente.column_name || "",
        };
      }
      // variável nova (sem mapeamento salvo ainda): fica sem entrada, pra a
      // lista suspensa mostrar o placeholder até o usuário escolher a origem.
    }
    return result;
  }

  function abrirNovoEnvio() {
    setEnvioEditandoId(null);
    setFormNumberId("");
    setFormTemplateId("");
    setFormAtivo(true);
    setFormMappings({});
    setMostrarPreviewEnvio(false);
    setEnvioMsg(null);
    setMostrarFormEnvio(true);
  }

  function abrirEditarEnvio(envio: FaixaEnvio) {
    setEnvioEditandoId(envio.id);
    setFormNumberId(envio.whatsapp_number_id);
    setFormTemplateId(envio.template_id);
    setFormAtivo(envio.active);
    setFormMappings(mapeamentosParaEdicao(envio.template_id));
    setMostrarPreviewEnvio(false);
    setEnvioMsg(null);
    setMostrarFormEnvio(true);
  }

  function selecionarTemplateForm(templateId: string) {
    setFormTemplateId(templateId);
    setFormMappings(mapeamentosParaEdicao(templateId));
  }

  function cancelarFormEnvio() {
    setMostrarFormEnvio(false);
    setEnvioEditandoId(null);
  }

  const templateDoForm = templates.find((t) => t.id === formTemplateId) || null;
  const templatesAprovados = templates.filter((t) => t.status === "approved");

  const numerosDisponiveis = numbers.filter(
    (n) => n.id === formNumberId || !faixa?.envios.some((e) => e.whatsapp_number_id === n.id && e.id !== envioEditandoId)
  );

  function renderizarPreviewForm(t: Template): string {
    return t.body_text.replace(/\{\{(\d+)\}\}/g, (match, pos) => {
      const variavel = t.variables.find((v) => v.position === Number(pos));
      if (!variavel) return match;
      const m = formMappings[variavel.id];
      if (!m) return `[${variavel.internal_name}]`;
      if (m.fonte_tipo === "campo_cliente") {
        const campo = campos.find((c) => c.campo === m.valor);
        return campo ? campo.exemplo : `${match} (campo não escolhido)`;
      }
      return `[${m.valor || variavel.internal_name}]`;
    });
  }

  async function salvarEnvio() {
    if (!id || !formNumberId || !formTemplateId || !templateDoForm) return;
    const semOrigem = templateDoForm.variables.filter((v) => !formMappings[v.id]);
    if (semOrigem.length > 0) {
      setError(`Selecione a origem de todas as variáveis (faltando: ${semOrigem.map((v) => v.internal_name).join(", ")})`);
      return;
    }
    setError(null);
    setSalvandoEnvio(true);
    try {
      const variable_mappings: FaixaVariableMappingIn[] = templateDoForm.variables.map((v) => {
        const m = formMappings[v.id];
        return { template_variable_id: v.id, fonte_tipo: m.fonte_tipo, column_name: m.valor };
      });
      if (envioEditandoId) {
        await api.atualizarEnvio(id, envioEditandoId, {
          whatsapp_number_id: formNumberId,
          template_id: formTemplateId,
          active: formAtivo,
          variable_mappings,
        });
      } else {
        await api.adicionarEnvio(id, {
          whatsapp_number_id: formNumberId,
          template_id: formTemplateId,
          variable_mappings,
        });
      }
      setMostrarFormEnvio(false);
      setEnvioEditandoId(null);
      setEnvioMsg(envioEditandoId ? "Envio atualizado" : "Envio adicionado");
      loadFaixa();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Erro ao salvar envio");
    } finally {
      setSalvandoEnvio(false);
    }
  }

  async function handleExcluirEnvio(envio: FaixaEnvio) {
    if (!id) return;
    if (
      !window.confirm(
        `Remover ${envio.whatsapp_number.label || envio.whatsapp_number.display_phone_number} (${envio.template.name}) desta faixa?`
      )
    )
      return;
    setError(null);
    setExcluindoEnvioId(envio.id);
    try {
      await api.excluirEnvio(id, envio.id);
      loadFaixa();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Erro ao remover envio");
    } finally {
      setExcluindoEnvioId(null);
    }
  }

  if (!faixa) return <div className="loading-state">Carregando faixa...</div>;

  return (
    <div>
      <Link to="/faixas" className="back-link">
        ← Faixas de cobrança
      </Link>
      <div className="page-header">
        <div>
          <h2>{faixa.name}</h2>
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

      <div className="card">
        <div className="card-header">
          <h3>Números e templates desta faixa</h3>
          <button type="button" className="secondary small" onClick={abrirNovoEnvio}>
            <IconPlus width={16} height={16} /> Adicionar número e template
          </button>
        </div>
        <p className="card-subtitle" style={{ marginTop: 0 }}>
          Cada número pode cobrar com um template próprio, em paralelo (WABAs diferentes) — a fila é compartilhada
          entre eles, então nenhum cliente é cobrado duas vezes. O agendamento de cada um (dias, horário, intervalo)
          fica em <Link to="/configuracoes?aba=horario">Configurações → Horário</Link>.
        </p>

        {envioMsg && (
          <div className="success-box" style={{ marginBottom: 16 }}>
            <IconCheckCircle width={16} height={16} />
            <span>{envioMsg}</span>
          </div>
        )}

        {faixa.envios.length === 0 && !mostrarFormEnvio && (
          <p className="text-muted">Nenhum número/template atribuído ainda — adicione um acima para poder subir a planilha e ligar o disparo.</p>
        )}

        {faixa.envios.length > 0 && (
          <div className="table-wrap">
            <table>
              <thead>
                <tr>
                  <th>Número</th>
                  <th>Template</th>
                  <th>Status</th>
                  <th>Agendamento</th>
                  <th></th>
                </tr>
              </thead>
              <tbody>
                {faixa.envios.map((e) => (
                  <tr key={e.id}>
                    <td className="cell-strong">{e.whatsapp_number.label || e.whatsapp_number.display_phone_number}</td>
                    <td>{e.template.name}</td>
                    <td>
                      <span className={`badge ${e.active ? "approved" : "rejected"}`}>{e.active ? "ativo" : "inativo"}</span>
                    </td>
                    <td>
                      <span className={`status-pill ${e.dispatch_config?.active ? "on" : "off"}`}>
                        {e.dispatch_config?.active ? "agendado" : "pausado"}
                      </span>
                    </td>
                    <td style={{ display: "flex", gap: 8, flexWrap: "wrap" }}>
                      <button type="button" className="secondary small" onClick={() => abrirEditarEnvio(e)}>
                        Editar
                      </button>
                      <button
                        type="button"
                        className="danger small"
                        disabled={excluindoEnvioId === e.id}
                        onClick={() => handleExcluirEnvio(e)}
                      >
                        <IconTrash width={14} height={14} />
                      </button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}

        {mostrarFormEnvio && (
          <div className="sub-card" style={{ marginTop: 16 }}>
            <h4>{envioEditandoId ? "Editar envio" : "Novo envio"}</h4>
            <div className="form-row">
              <div className="field">
                <label>Número de envio</label>
                <select value={formNumberId} onChange={(e) => setFormNumberId(e.target.value)}>
                  <option value="">Selecione...</option>
                  {numerosDisponiveis.map((n) => (
                    <option key={n.id} value={n.id}>
                      {n.label || n.display_phone_number} ({n.display_phone_number})
                    </option>
                  ))}
                </select>
                {numbers.length === 0 && (
                  <p className="field-hint">Nenhum número ainda — importe os números da WABA em Configurações.</p>
                )}
              </div>
              <div className="field">
                <label>Template</label>
                <div style={{ display: "flex", gap: 8, alignItems: "center" }}>
                  <select value={formTemplateId} onChange={(e) => selecionarTemplateForm(e.target.value)} style={{ flex: 1, minWidth: 0 }}>
                    <option value="">Selecione...</option>
                    {templatesAprovados.map((t) => (
                      <option key={t.id} value={t.id}>
                        {t.name}
                      </option>
                    ))}
                  </select>
                  {templateDoForm && (
                    <button
                      type="button"
                      className="secondary small"
                      style={{ flexShrink: 0 }}
                      onClick={() => setMostrarPreviewEnvio((atual) => !atual)}
                    >
                      <IconEye width={14} height={14} /> {mostrarPreviewEnvio ? "Fechar" : "Pré-visualizar"}
                    </button>
                  )}
                </div>
              </div>
            </div>

            {envioEditandoId && (
              <div className="field">
                <label className="checkbox-row">
                  <input type="checkbox" checked={formAtivo} onChange={(e) => setFormAtivo(e.target.checked)} />
                  Envio ativo (entra na fila e no disparo)
                </label>
              </div>
            )}

            {templateDoForm && mostrarPreviewEnvio && (
              <div className="template-preview">
                <div className="template-preview-bubble">
                  {templateDoForm.header_type === "image" && templateDoForm.image_url && (
                    <img
                      src={templateDoForm.image_url}
                      alt="Cabeçalho do template"
                      style={{ width: "100%", maxWidth: 280, borderRadius: 8, marginBottom: 10, display: "block" }}
                    />
                  )}
                  {renderizarPreviewForm(templateDoForm)}
                </div>
                <p className="field-hint">
                  Valores entre colchetes vêm de "Coluna da planilha" (só o nome sugerido — o valor real é o da
                  planilha subida); os demais usam o exemplo do campo do cliente escolhido.
                </p>
              </div>
            )}

            {templateDoForm && templateDoForm.variables.length > 0 && (
              <>
                <label style={{ marginBottom: 8, marginTop: 16, display: "block" }}>Variáveis do template</label>
                <div className="form-row" style={{ flexWrap: "wrap" }}>
                  {templateDoForm.variables.map((v) => {
                    const m = formMappings[v.id];
                    const selectValue = m?.fonte_tipo === "campo_cliente" ? `campo:${m.valor}` : "";
                    return (
                      <div className="field" key={v.id} style={{ minWidth: 260 }}>
                        <label>
                          {`{{${v.position}}}`} ({v.internal_name})
                        </label>
                        <div style={{ display: "flex", gap: 6, minWidth: 0, flexDirection: "column" }}>
                          <select
                            value={selectValue}
                            onChange={(e) => {
                              const valorSelect = e.target.value;
                              if (!valorSelect) {
                                setFormMappings((atual) => {
                                  const proximo = { ...atual };
                                  delete proximo[v.id];
                                  return proximo;
                                });
                              } else {
                                setFormMappings((atual) => ({
                                  ...atual,
                                  [v.id]: { fonte_tipo: "campo_cliente", valor: valorSelect.slice("campo:".length) },
                                }));
                              }
                            }}
                          >
                            <option value="" disabled>
                              Selecione o campo do cliente...
                            </option>
                            {campos.map((c) => (
                              <option key={c.campo} value={`campo:${c.campo}`}>
                                {c.rotulo}
                              </option>
                            ))}
                          </select>
                        </div>
                      </div>
                    );
                  })}
                </div>
                <p className="field-hint">
                  Vale só para envios gerados dentro do sistema. Na importação de planilha, cada variável é
                  mapeada para uma coluna.
                </p>
              </>
            )}

            <div className="actions-row">
              <button type="button" className="secondary" onClick={cancelarFormEnvio} disabled={salvandoEnvio}>
                Cancelar
              </button>
              <button type="button" onClick={salvarEnvio} disabled={!formNumberId || !formTemplateId || salvandoEnvio}>
                {salvandoEnvio ? "Salvando..." : "Salvar envio"}
              </button>
            </div>
          </div>
        )}
      </div>

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
                {filaOrdenada.map((q) => (
                  <tr key={q.id}>
                    <td className="cell-strong">{q.codigo_cliente}</td>
                    <td>{q.nome || "—"}</td>
                    <td className="text-muted">{q.cpf || "—"}</td>
                    <td>{q.celular}</td>
                    <td className="text-muted">{q.valor || "—"}</td>
                    <td>
                      <span className={`badge ${q.status}`}>{q.status}</span>
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

      <div className="card">
        <div className="card-header">
          <h3>Leads gerados nesta faixa de atraso</h3>
          <Link to="/leads" className="ghost small">
            Ver em Leads →
          </Link>
        </div>
        <p className="card-subtitle">
          Clientes já gerados em Cobrança → Leads para a faixa de atraso "{faixa.name}" — não entram automaticamente
          na fila acima, é preciso subir a planilha com esta base.
        </p>
        {leadsLoading ? (
          <div className="loading-state">Carregando leads...</div>
        ) : leads.length === 0 ? (
          <div className="empty-state">
            <IconUsers width={28} height={28} />
            <div className="title">Nenhum lead gerado para esta faixa</div>
            <p>Gere leads em Cobrança → Leads filtrando por esta faixa de atraso.</p>
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
                  {leadsOrdenados.map((l) => (
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
    </div>
  );
}
