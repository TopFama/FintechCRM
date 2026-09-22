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
  const [error, setError] = useState<string | null>(null);
  const [uploadResult, setUploadResult] = useState<UploadResult | null>(null);
  const [lastQueueUpdate, setLastQueueUpdate] = useState<Date | null>(null);
  const [downloadingModel, setDownloadingModel] = useState(false);

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
  const [leadsLoading, setLeadsLoading] = useState(false);

  // Upload em duas etapas: 1) escolher arquivo e ler as colunas reais do
  // cabeçalho; 2) mapear cada variável/campo para uma dessas colunas antes
  // de confirmar a importação.
  const [pendingFile, setPendingFile] = useState<File | null>(null);
  const [columns, setColumns] = useState<string[] | null>(null);
  const [sampleRow, setSampleRow] = useState<Record<string, string> | null>(null);
  const [loadingColumns, setLoadingColumns] = useState(false);
  const [fieldMap, setFieldMap] = useState<UploadFieldMapping>({
    celular: NO_COLUMN,
    codigo_cliente: NO_COLUMN,
    nome: NO_COLUMN,
    cpf: NO_COLUMN,
    valor: NO_COLUMN,
    variables: {},
  });
  const [importing, setImporting] = useState(false);

  const fileInputRef = useRef<HTMLInputElement>(null);

  function loadFaixa() {
    if (!id) return;
    api
      .getFaixa(id)
      .then(setFaixa)
      .catch((e) => setError(e.message));
  }

  function loadQueue() {
    if (!id) return;
    api
      .listQueue(id)
      .then((q) => {
        setQueue(q);
        setLastQueueUpdate(new Date());
      })
      .catch((e) => setError(e.message));
  }

  function loadLeads(nomeFaixa: string) {
    setLeadsLoading(true);
    api
      .listarLeads({ faixa: [nomeFaixa], limit: 50, offset: 0 })
      .then((r) => {
        setLeads(r.itens);
        setLeadsTotal(r.total);
      })
      .catch((e) => setError(e.message))
      .finally(() => setLeadsLoading(false));
  }

  useEffect(() => {
    api.listTemplates().then(setTemplates).catch(() => undefined);
    api.listNumbers().then(setNumbers).catch(() => undefined);
    api.listCamposCliente().then(setCampos).catch(() => undefined);
  }, []);

  useEffect(() => {
    if (faixa) loadLeads(faixa.name);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [faixa?.name]);

  useEffect(() => {
    loadFaixa();
    loadQueue();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [id]);

  // Acompanhamento da fila em tempo (quase) real: revalida periodicamente
  // enquanto a tela estiver aberta.
  useEffect(() => {
    if (!id) return;
    const interval = setInterval(loadQueue, QUEUE_POLL_MS);
    return () => clearInterval(interval);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [id]);

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

  async function handlePickFile(file: File) {
    setError(null);
    setUploadResult(null);
    setPendingFile(file);
    setColumns(null);
    setLoadingColumns(true);
    try {
      const result = await api.uploadColumns(id!, file);
      setColumns(result.columns);
      setSampleRow(result.sample_row);
      const previous = faixa?.upload_field_mapping;
      const variableIds = templatesAtivos.flatMap((t) => t.variables.map((v) => v.id));
      setFieldMap({
        celular: pickDefault(result.columns, previous?.celular),
        codigo_cliente: pickDefault(result.columns, previous?.codigo_cliente),
        nome: pickDefault(result.columns, previous?.nome),
        cpf: pickDefault(result.columns, previous?.cpf),
        valor: pickDefault(result.columns, previous?.valor),
        variables: Object.fromEntries(
          variableIds.map((vid) => [vid, pickDefault(result.columns, previous?.variables?.[vid])])
        ),
      });
    } catch (err) {
      setError(err instanceof Error ? err.message : "Erro ao ler colunas da planilha");
      setPendingFile(null);
    } finally {
      setLoadingColumns(false);
    }
  }

  function cancelMapping() {
    setPendingFile(null);
    setColumns(null);
    setSampleRow(null);
    if (fileInputRef.current) fileInputRef.current.value = "";
  }

  // Variável com fonte_tipo "campo_cliente" vem direto do cadastro do
  // cliente (base de leads) — não precisa de coluna na planilha, então não
  // entra na exigência de mapeamento do upload.
  const mappingByVid = useMemo(() => {
    const m: Record<string, string> = {};
    (faixa?.variable_mappings || []).forEach((vm) => {
      m[vm.template_variable_id] = vm.fonte_tipo;
    });
    return m;
  }, [faixa]);

  const mappingColumnByVid = useMemo(() => {
    const m: Record<string, string> = {};
    (faixa?.variable_mappings || []).forEach((vm) => {
      if (vm.fonte_tipo === "campo_cliente" && vm.column_name) m[vm.template_variable_id] = vm.column_name;
    });
    return m;
  }, [faixa]);

  const requiredVariableIds = templatesAtivos
    .flatMap((t) => t.variables)
    .filter((v) => (mappingByVid[v.id] || "coluna") === "coluna")
    .map((v) => v.id);
  const mappingComplete =
    Boolean(fieldMap.celular) &&
    Boolean(fieldMap.codigo_cliente) &&
    Boolean(fieldMap.nome) &&
    Boolean(fieldMap.cpf) &&
    requiredVariableIds.every((vid) => Boolean(fieldMap.variables[vid]));

  async function confirmImport() {
    if (!id || !pendingFile || !mappingComplete) return;
    setError(null);
    setImporting(true);
    try {
      const result = await api.uploadPlanilha(id, pendingFile, fieldMap);
      setUploadResult(result);
      cancelMapping();
      loadFaixa();
      loadQueue();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Erro ao subir planilha");
    } finally {
      setImporting(false);
    }
  }

  async function handleDownloadModel() {
    if (!id || !faixa) return;
    setError(null);
    setDownloadingModel(true);
    try {
      await api.downloadSpreadsheetModel(id, faixa.name);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Erro ao baixar modelo");
    } finally {
      setDownloadingModel(false);
    }
  }

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

  function renderizarPreviewUpload(t: Template): string {
    return t.body_text.replace(/\{\{(\d+)\}\}/g, (match, pos) => {
      const variavel = t.variables.find((v) => v.position === Number(pos));
      if (!variavel) return match;
      const tipo = mappingByVid[variavel.id] || "coluna";
      if (tipo === "campo_cliente") {
        const campo = campos.find((c) => c.campo === mappingColumnByVid[variavel.id]);
        return campo ? campo.exemplo : match;
      }
      const coluna = fieldMap.variables[variavel.id];
      const valor = coluna && sampleRow ? sampleRow[coluna] : "";
      return valor ? valor : `[${variavel.internal_name}]`;
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
                    <td style={{ display: "flex", gap: 8 }}>
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
                    const selectValue = !m ? "" : m.fonte_tipo === "campo_cliente" ? `campo:${m.valor}` : "coluna";
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
                              } else if (valorSelect === "coluna") {
                                setFormMappings((atual) => ({
                                  ...atual,
                                  [v.id]: { fonte_tipo: "coluna", valor: v.internal_name },
                                }));
                              } else {
                                setFormMappings((atual) => ({
                                  ...atual,
                                  [v.id]: { fonte_tipo: "campo_cliente", valor: valorSelect.slice("campo:".length) },
                                }));
                              }
                            }}
                          >
                            <option value="" disabled>
                              Selecione a origem da variável...
                            </option>
                            <option value="coluna">Coluna da planilha</option>
                            <optgroup label="Campo do cliente">
                              {campos.map((c) => (
                                <option key={c.campo} value={`campo:${c.campo}`}>
                                  {c.rotulo}
                                </option>
                              ))}
                            </optgroup>
                          </select>
                          {m?.fonte_tipo === "coluna" && (
                            <input
                              value={m.valor}
                              onChange={(e) => setFormMappings((atual) => ({ ...atual, [v.id]: { ...m, valor: e.target.value } }))}
                              placeholder="nome de coluna sugerido"
                            />
                          )}
                        </div>
                      </div>
                    );
                  })}
                </div>
                <p className="field-hint">
                  "Coluna da planilha" só define o nome sugerido — ao subir a planilha, você escolhe a coluna real.
                  "Campo do cliente" usa um valor fixo do cadastro, sem precisar de planilha.
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

      {templatesAtivos.length > 0 && (
        <div className="card">
          <div className="card-header">
            <h3>Subir planilha e mapear colunas</h3>
            <button className="ghost small" onClick={handleDownloadModel} disabled={downloadingModel}>
              <IconDownload width={16} height={16} /> {downloadingModel ? "Baixando..." : "Baixar modelo sugerido (.xlsx)"}
            </button>
          </div>
          <p className="card-subtitle">
            Suba a planilha com a base de clientes desta faixa. O sistema lê o cabeçalho (primeira linha) e você
            escolhe, em uma lista suspensa, qual coluna alimenta cada campo — não precisa usar os nomes do modelo.
          </p>

          {!columns && (
            <label className="dropzone">
              <input
                ref={fileInputRef}
                type="file"
                accept=".xlsx"
                onChange={(e) => e.target.files && handlePickFile(e.target.files[0])}
              />
              <IconUpload width={26} height={26} />
              <div className="dz-title">{loadingColumns ? "Lendo colunas da planilha..." : "Clique ou arraste a planilha aqui"}</div>
              <div className="dz-hint">.xlsx</div>
            </label>
          )}

          {columns && (
            <div>
              <p className="card-subtitle" style={{ marginTop: 0 }}>
                Arquivo: <strong>{pendingFile?.name}</strong> — {columns.length} coluna(s) encontrada(s)
              </p>

              <div className="form-row">
                <div className="field">
                  <label>Coluna do código (SETA, até 8 dígitos — completa com zero à esquerda) *</label>
                  <select value={fieldMap.codigo_cliente} onChange={(e) => setFieldMap({ ...fieldMap, codigo_cliente: e.target.value })}>
                    <option value="">Selecione...</option>
                    {columns.map((c) => (
                      <option key={c} value={c}>
                        {c}
                      </option>
                    ))}
                  </select>
                </div>
                <div className="field">
                  <label>Coluna do nome (usa só o primeiro nome) *</label>
                  <select value={fieldMap.nome} onChange={(e) => setFieldMap({ ...fieldMap, nome: e.target.value })}>
                    <option value="">Selecione...</option>
                    {columns.map((c) => (
                      <option key={c} value={c}>
                        {c}
                      </option>
                    ))}
                  </select>
                </div>
              </div>

              <div className="form-row">
                <div className="field">
                  <label>Coluna do CPF (formata com pontos e traço) *</label>
                  <select value={fieldMap.cpf} onChange={(e) => setFieldMap({ ...fieldMap, cpf: e.target.value })}>
                    <option value="">Selecione...</option>
                    {columns.map((c) => (
                      <option key={c} value={c}>
                        {c}
                      </option>
                    ))}
                  </select>
                </div>
                <div className="field">
                  <label>Coluna do celular *</label>
                  <select value={fieldMap.celular} onChange={(e) => setFieldMap({ ...fieldMap, celular: e.target.value })}>
                    <option value="">Selecione...</option>
                    {columns.map((c) => (
                      <option key={c} value={c}>
                        {c}
                      </option>
                    ))}
                  </select>
                </div>
              </div>

              <div className="form-row">
                <div className="field">
                  <label>Coluna do valor cobrado (opcional)</label>
                  <select value={fieldMap.valor || ""} onChange={(e) => setFieldMap({ ...fieldMap, valor: e.target.value })}>
                    <option value="">Nenhuma</option>
                    {columns.map((c) => (
                      <option key={c} value={c}>
                        {c}
                      </option>
                    ))}
                  </select>
                </div>
              </div>

              {templatesAtivos.some((t) => t.variables.length > 0) && (
                <>
                  <label style={{ marginBottom: 8 }}>Variáveis dos templates ativos</label>
                  <div className="form-row" style={{ flexWrap: "wrap" }}>
                    {templatesAtivos.flatMap((t) =>
                      t.variables.map((v) => {
                        const tipo = mappingByVid[v.id] || "coluna";
                        if (tipo === "campo_cliente") {
                          return (
                            <div className="field" key={v.id} style={{ minWidth: 220 }}>
                              <label>
                                {t.name}: {v.internal_name}
                              </label>
                              <div className="text-muted" style={{ paddingTop: 6 }}>
                                Preenchido direto do cadastro do cliente
                              </div>
                            </div>
                          );
                        }
                        return (
                          <div className="field" key={v.id} style={{ minWidth: 220 }}>
                            <label>
                              {t.name}: {v.internal_name} *
                            </label>
                            <select
                              value={fieldMap.variables[v.id] || ""}
                              onChange={(e) => setFieldMap({ ...fieldMap, variables: { ...fieldMap.variables, [v.id]: e.target.value } })}
                            >
                              <option value="">Selecione...</option>
                              {columns.map((c) => (
                                <option key={c} value={c}>
                                  {c}
                                </option>
                              ))}
                            </select>
                          </div>
                        );
                      })
                    )}
                  </div>
                </>
              )}

              {sampleRow && templatesAtivos.length > 0 && (
                <div className="sub-card" style={{ marginTop: 16 }}>
                  <label style={{ marginBottom: 8, display: "block" }}>
                    Pré-visualização (com a primeira linha da planilha subida)
                  </label>
                  {templatesAtivos.map((t) => (
                    <p key={t.id} className="card-subtitle" style={{ whiteSpace: "pre-wrap" }}>
                      <strong>{t.name}:</strong> {renderizarPreviewUpload(t)}
                    </p>
                  ))}
                </div>
              )}

              <div className="actions-row">
                <button className="secondary" onClick={cancelMapping} disabled={importing}>
                  Cancelar
                </button>
                <button onClick={confirmImport} disabled={!mappingComplete || importing}>
                  {importing ? "Importando..." : "Confirmar e importar"}
                </button>
              </div>
            </div>
          )}

          {uploadResult && (
            <>
              <div className="upload-summary">
                <div className="item">
                  <span className="num" style={{ color: "var(--color-success)" }}>
                    {uploadResult.accepted_count}
                  </span>
                  aceitos
                </div>
                <div className="item">
                  <span className="num" style={{ color: "var(--color-danger)" }}>
                    {uploadResult.rejected_count}
                  </span>
                  rejeitados
                </div>
                {uploadResult.invalid_phone_count > 0 && (
                  <div className="item">
                    <span className="num" style={{ color: "var(--color-warning)" }}>
                      {uploadResult.invalid_phone_count}
                    </span>
                    telefone(s) inválido(s)
                  </div>
                )}
                <div className="item">
                  <span className="num">{uploadResult.row_count}</span>
                  linhas na planilha
                </div>
              </div>
              {uploadResult.invalid_phone_count > 0 && (
                <p className="field-hint">
                  <Link to="/relatorios">Ver no relatório de telefones inválidos →</Link>
                </p>
              )}
              {uploadResult.rejected_reasons.length > 0 && (
                <ul style={{ fontSize: 13, color: "var(--color-danger)", marginTop: 10 }}>
                  {uploadResult.rejected_reasons.map((r, i) => (
                    <li key={i}>{r}</li>
                  ))}
                </ul>
              )}
            </>
          )}
        </div>
      )}

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
            <p>Suba uma planilha acima para adicionar clientes a esta faixa.</p>
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
            {leadsTotal > leads.length && (
              <p className="field-hint">Mostrando {leads.length} de {leadsTotal} leads — veja o restante em Leads.</p>
            )}
          </>
        )}
      </div>
    </div>
  );
}
