import { useEffect, useRef, useState } from "react";
import { Link, useParams } from "react-router-dom";
import {
  api,
  CampoCliente,
  DispatchConfig,
  Faixa,
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
  IconBolt,
  IconCheckCircle,
  IconDownload,
  IconEye,
  IconInbox,
  IconRefresh,
  IconUpload,
  IconUsers,
} from "../icons";

const QUEUE_POLL_MS = 4000;

const NO_COLUMN = "";

function pickDefault(columns: string[], previous: string | null | undefined): string {
  if (previous && columns.includes(previous)) return previous;
  return NO_COLUMN;
}

const WEEKDAYS = [
  { value: "1", label: "Seg" },
  { value: "2", label: "Ter" },
  { value: "3", label: "Qua" },
  { value: "4", label: "Qui" },
  { value: "5", label: "Sex" },
  { value: "6", label: "Sáb" },
  { value: "7", label: "Dom" },
];

function toggleWeekday(scheduleDays: string, value: string): string {
  const days = new Set(scheduleDays.split(",").filter(Boolean));
  if (days.has(value)) {
    days.delete(value);
  } else {
    days.add(value);
  }
  return WEEKDAYS.map((d) => d.value).filter((v) => days.has(v)).join(",");
}

export default function FaixaDetail() {
  const { id } = useParams<{ id: string }>();
  const [faixa, setFaixa] = useState<Faixa | null>(null);
  const [queue, setQueue] = useState<QueueItem[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [uploadResult, setUploadResult] = useState<UploadResult | null>(null);
  const [config, setConfig] = useState<DispatchConfig | null>(null);
  const [savingConfig, setSavingConfig] = useState(false);
  const [dispatchMessage, setDispatchMessage] = useState<string | null>(null);
  const [lastQueueUpdate, setLastQueueUpdate] = useState<Date | null>(null);
  const [downloadingModel, setDownloadingModel] = useState(false);

  // Configuração da faixa: template, números de envio e mapeamento de
  // variáveis — o que o wizard define na criação, mas também pode ser
  // reatribuído depois aqui (ex.: faixa criada por "Sincronizar com faixas
  // de atraso", que nasce sem nada disso).
  const [templates, setTemplates] = useState<Template[]>([]);
  const [numbers, setNumbers] = useState<WhatsappNumber[]>([]);
  const [campos, setCampos] = useState<CampoCliente[]>([]);
  const [editTemplateId, setEditTemplateId] = useState("");
  const [editNumberIds, setEditNumberIds] = useState<string[]>([]);
  const [editMappings, setEditMappings] = useState<Record<string, { fonte_tipo: "coluna" | "campo_cliente"; valor: string }>>({});
  const [salvandoFaixa, setSalvandoFaixa] = useState(false);
  const [faixaSalvaMsg, setFaixaSalvaMsg] = useState<string | null>(null);
  const [mostrarPreview, setMostrarPreview] = useState(false);

  // Leads gerados (Cobrança → Leads) para esta mesma faixa de atraso, só
  // pra dar visibilidade de quem existe antes de decidir subir a planilha.
  const [leads, setLeads] = useState<Lead[]>([]);
  const [leadsTotal, setLeadsTotal] = useState(0);
  const [leadsLoading, setLeadsLoading] = useState(false);

  // Upload em duas etapas: 1) escolher arquivo e ler as colunas reais do
  // cabeçalho; 2) mapear cada variável/campo para uma dessas colunas antes
  // de confirmar a importação.
  const [pendingFile, setPendingFile] = useState<File | null>(null);
  const [columns, setColumns] = useState<string[] | null>(null);
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
      .then((f) => {
        setFaixa(f);
        setConfig(f.dispatch_config);
        setEditTemplateId(f.template_id || "");
        setEditNumberIds(f.numbers.map((n) => n.whatsapp_number_id));
        const mapeamentos: Record<string, { fonte_tipo: "coluna" | "campo_cliente"; valor: string }> = {};
        for (const m of f.variable_mappings) {
          mapeamentos[m.template_variable_id] = {
            fonte_tipo: m.fonte_tipo === "campo_cliente" ? "campo_cliente" : "coluna",
            valor: m.column_name || "",
          };
        }
        setEditMappings(mapeamentos);
      })
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

  async function handlePickFile(file: File) {
    setError(null);
    setUploadResult(null);
    setPendingFile(file);
    setColumns(null);
    setLoadingColumns(true);
    try {
      const result = await api.uploadColumns(id!, file);
      setColumns(result.columns);
      const previous = faixa?.upload_field_mapping;
      setFieldMap({
        celular: pickDefault(result.columns, previous?.celular),
        codigo_cliente: pickDefault(result.columns, previous?.codigo_cliente),
        nome: pickDefault(result.columns, previous?.nome),
        cpf: pickDefault(result.columns, previous?.cpf),
        valor: pickDefault(result.columns, previous?.valor),
        variables: Object.fromEntries(
          (faixa?.template?.variables || []).map((v) => [
            v.id,
            pickDefault(result.columns, previous?.variables?.[v.id]),
          ])
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
    if (fileInputRef.current) fileInputRef.current.value = "";
  }

  const requiredVariableIds = faixa?.template?.variables.map((v) => v.id) || [];
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

  async function saveConfig() {
    if (!id || !config) return;
    setError(null);
    setSavingConfig(true);
    try {
      await api.updateDispatchConfig(id, config);
      loadFaixa();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Erro ao salvar configuração");
    } finally {
      setSavingConfig(false);
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

  async function dispatchNow() {
    if (!id) return;
    setError(null);
    setDispatchMessage(null);
    try {
      await api.dispatchNow(id);
      setDispatchMessage("Disparo agendado — o worker vai processar na próxima varredura.");
    } catch (err) {
      setError(err instanceof Error ? err.message : "Erro ao disparar agora");
    }
  }

  function selecionarTemplateEdicao(templateId: string) {
    setEditTemplateId(templateId);
    const template = templates.find((t) => t.id === templateId);
    if (!template) {
      setEditMappings({});
      return;
    }
    // Mudou de template: o mapeamento antigo não serve mais (variáveis são
    // outras), então recomeça com a sugestão padrão (nome interno da
    // variável como coluna, igual ao passo 3 do assistente de nova faixa).
    if (templateId !== faixa?.template_id) {
      const mapeamentos: Record<string, { fonte_tipo: "coluna" | "campo_cliente"; valor: string }> = {};
      for (const v of template.variables) {
        mapeamentos[v.id] = { fonte_tipo: "coluna", valor: v.internal_name };
      }
      setEditMappings(mapeamentos);
    }
  }

  function toggleEditNumber(numberId: string) {
    setEditNumberIds((prev) => (prev.includes(numberId) ? prev.filter((n) => n !== numberId) : [...prev, numberId]));
  }

  const templateEmEdicao = templates.find((t) => t.id === editTemplateId) || null;

  function renderizarPreviewFaixa(t: Template): string {
    return t.body_text.replace(/\{\{(\d+)\}\}/g, (match, pos) => {
      const variavel = t.variables.find((v) => v.position === Number(pos));
      if (!variavel) return match;
      const m = editMappings[variavel.id];
      if (!m) return `[${variavel.internal_name}]`;
      if (m.fonte_tipo === "campo_cliente") {
        const campo = campos.find((c) => c.campo === m.valor);
        return campo ? campo.exemplo : `${match} (campo não escolhido)`;
      }
      return `[${m.valor || variavel.internal_name}]`;
    });
  }

  async function salvarConfigFaixa() {
    if (!id) return;
    setError(null);
    setFaixaSalvaMsg(null);
    setSalvandoFaixa(true);
    try {
      const variable_mappings: FaixaVariableMappingIn[] = editTemplateId
        ? (templateEmEdicao?.variables || []).map((v) => {
            const m = editMappings[v.id] || { fonte_tipo: "coluna" as const, valor: v.internal_name };
            return {
              template_variable_id: v.id,
              fonte_tipo: m.fonte_tipo,
              column_name: m.valor,
            };
          })
        : [];
      const atualizada = await api.atualizarFaixa(id, {
        template_id: editTemplateId || null,
        whatsapp_number_ids: editNumberIds,
        variable_mappings,
      });
      setFaixa(atualizada);
      setConfig(atualizada.dispatch_config);
      setFaixaSalvaMsg("Configuração da faixa salva");
    } catch (err) {
      setError(err instanceof Error ? err.message : "Erro ao salvar a configuração da faixa");
    } finally {
      setSalvandoFaixa(false);
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
          <div className="subtitle">Template: {faixa.template?.name}</div>
        </div>
        <span className={`status-pill ${config?.active ? "on" : "off"}`}>
          {config?.active ? "Agendado" : "Pausado"}
        </span>
      </div>

      {error && (
        <div className="error-box">
          <IconAlert width={16} height={16} />
          <span>{error}</span>
        </div>
      )}

      <div className="card">
        <div className="card-header">
          <h3>Template, números e variáveis</h3>
        </div>
        {!faixa.template_id && (
          <p className="card-subtitle" style={{ marginTop: 0 }}>
            Esta faixa ainda não tem template atribuído — atribua um abaixo para poder subir a planilha e ligar o
            disparo.
          </p>
        )}
        {faixaSalvaMsg && (
          <div className="success-box" style={{ marginBottom: 16 }}>
            <IconCheckCircle width={16} height={16} />
            <span>{faixaSalvaMsg}</span>
          </div>
        )}
        <div className="field">
          <label>Template aprovado</label>
          <div style={{ display: "flex", gap: 8, alignItems: "center" }}>
            <select
              value={editTemplateId}
              onChange={(e) => selecionarTemplateEdicao(e.target.value)}
              style={{ flex: 1, minWidth: 0 }}
            >
              <option value="">Sem template</option>
              {templates.map((t) => (
                <option key={t.id} value={t.id}>
                  {t.name} ({t.status})
                </option>
              ))}
            </select>
            {templateEmEdicao && (
              <button
                type="button"
                className="secondary small"
                style={{ flexShrink: 0 }}
                onClick={() => setMostrarPreview((atual) => !atual)}
              >
                <IconEye width={14} height={14} /> {mostrarPreview ? "Fechar" : "Pré-visualizar"}
              </button>
            )}
          </div>
        </div>

        {templateEmEdicao && mostrarPreview && (
          <div className="template-preview">
            <div className="template-preview-bubble">
              {templateEmEdicao.header_type === "image" && templateEmEdicao.image_url && (
                <img
                  src={templateEmEdicao.image_url}
                  alt="Cabeçalho do template"
                  style={{ width: "100%", maxWidth: 280, borderRadius: 8, marginBottom: 10, display: "block" }}
                />
              )}
              {renderizarPreviewFaixa(templateEmEdicao)}
            </div>
            <p className="field-hint">
              Valores entre colchetes vêm de "Coluna da planilha" (só o nome sugerido — o valor real é o da planilha
              subida); os demais usam o exemplo do campo do cliente escolhido.
            </p>
          </div>
        )}

        <label style={{ marginBottom: 8, display: "block" }}>Números de envio</label>
        <div className="option-list">
          {numbers.map((n) => (
            <label key={n.id} className={`option-item${editNumberIds.includes(n.id) ? " checked" : ""}`}>
              <input type="checkbox" checked={editNumberIds.includes(n.id)} onChange={() => toggleEditNumber(n.id)} />
              {n.label || n.display_phone_number} ({n.display_phone_number})
            </label>
          ))}
          {numbers.length === 0 && (
            <p className="text-muted">Nenhum número ainda — importe os números da WABA em Configurações.</p>
          )}
        </div>

        {templateEmEdicao && templateEmEdicao.variables.length > 0 && (
          <>
            <label style={{ marginBottom: 8, marginTop: 16, display: "block" }}>Variáveis do template</label>
            <div className="form-row" style={{ flexWrap: "wrap" }}>
              {templateEmEdicao.variables.map((v) => {
                const m = editMappings[v.id] || { fonte_tipo: "coluna" as const, valor: v.internal_name };
                return (
                  <div className="field" key={v.id} style={{ minWidth: 260 }}>
                    <label>{`{{${v.position}}}`} ({v.internal_name})</label>
                    <div style={{ display: "flex", gap: 6, minWidth: 0 }}>
                      <select
                        value={m.fonte_tipo}
                        onChange={(e) =>
                          setEditMappings((atual) => ({
                            ...atual,
                            [v.id]: {
                              fonte_tipo: e.target.value as "coluna" | "campo_cliente",
                              valor: e.target.value === "campo_cliente" ? campos[0]?.campo || "" : v.internal_name,
                            },
                          }))
                        }
                        style={{ flex: "0 0 auto" }}
                      >
                        <option value="coluna">Coluna da planilha</option>
                        <option value="campo_cliente">Campo do cliente</option>
                      </select>
                      {m.fonte_tipo === "campo_cliente" ? (
                        <select
                          value={m.valor}
                          onChange={(e) =>
                            setEditMappings((atual) => ({ ...atual, [v.id]: { ...m, valor: e.target.value } }))
                          }
                          style={{ flex: 1, minWidth: 0 }}
                        >
                          {campos.map((c) => (
                            <option key={c.campo} value={c.campo}>
                              {c.rotulo}
                            </option>
                          ))}
                        </select>
                      ) : (
                        <input
                          value={m.valor}
                          onChange={(e) =>
                            setEditMappings((atual) => ({ ...atual, [v.id]: { ...m, valor: e.target.value } }))
                          }
                          placeholder="nome de coluna sugerido"
                          style={{ flex: 1, minWidth: 0 }}
                        />
                      )}
                    </div>
                  </div>
                );
              })}
            </div>
            <p className="field-hint">
              "Coluna da planilha" só define o nome sugerido — ao subir a planilha, você escolhe a coluna real. "Campo
              do cliente" usa um valor fixo do cadastro, sem precisar de planilha.
            </p>
          </>
        )}

        <div className="actions-row">
          <button type="button" onClick={salvarConfigFaixa} disabled={salvandoFaixa}>
            {salvandoFaixa ? "Salvando..." : "Salvar configuração da faixa"}
          </button>
        </div>
      </div>

      {faixa.template && (
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

            {faixa.template.variables.length > 0 && (
              <>
                <label style={{ marginBottom: 8 }}>Variáveis do template</label>
                <div className="form-row" style={{ flexWrap: "wrap" }}>
                  {faixa.template.variables.map((v) => (
                    <div className="field" key={v.id} style={{ minWidth: 220 }}>
                      <label>{v.internal_name} *</label>
                      <select
                        value={fieldMap.variables[v.id] || ""}
                        onChange={(e) =>
                          setFieldMap({ ...fieldMap, variables: { ...fieldMap.variables, [v.id]: e.target.value } })
                        }
                      >
                        <option value="">Selecione...</option>
                        {columns.map((c) => (
                          <option key={c} value={c}>
                            {c}
                          </option>
                        ))}
                      </select>
                    </div>
                  ))}
                </div>
              </>
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
          <h3>Disparo e controles de execução</h3>
        </div>
        {config && (
          <>
            <div className="form-row">
              <div className="field">
                <label>Intervalo entre rodadas (segundos)</label>
                <input
                  type="number"
                  value={config.interval_seconds}
                  onChange={(e) => setConfig({ ...config, interval_seconds: Number(e.target.value) })}
                />
              </div>
              <div className="field">
                <label>Cobranças por rodada</label>
                <input
                  type="number"
                  value={config.batch_size}
                  onChange={(e) => setConfig({ ...config, batch_size: Number(e.target.value) })}
                />
              </div>
            </div>
            <div className="field">
              <label>Dias da semana</label>
              <div style={{ display: "flex", gap: 6, flexWrap: "wrap" }}>
                {WEEKDAYS.map((d) => {
                  const active = config.schedule_days.split(",").includes(d.value);
                  return (
                    <button
                      key={d.value}
                      type="button"
                      className={active ? "small" : "secondary small"}
                      onClick={() => setConfig({ ...config, schedule_days: toggleWeekday(config.schedule_days, d.value) })}
                    >
                      {d.label}
                    </button>
                  );
                })}
              </div>
            </div>
            <div className="form-row">
              <div className="field">
                <label>Início da janela</label>
                <input
                  value={config.schedule_start}
                  onChange={(e) => setConfig({ ...config, schedule_start: e.target.value })}
                />
              </div>
              <div className="field">
                <label>Fim da janela</label>
                <input
                  value={config.schedule_end}
                  onChange={(e) => setConfig({ ...config, schedule_end: e.target.value })}
                />
              </div>
            </div>
            <div className="field">
              <label className="checkbox-row">
                <input
                  type="checkbox"
                  checked={config.active}
                  onChange={(e) => setConfig({ ...config, active: e.target.checked })}
                />
                Agendamento ativo
              </label>
            </div>
            {dispatchMessage && (
              <div className="success-box">
                <IconCheckCircle width={16} height={16} />
                <span>{dispatchMessage}</span>
              </div>
            )}
            <div className="actions-row">
              <button onClick={saveConfig} disabled={savingConfig}>
                {savingConfig ? "Salvando..." : "Salvar configuração"}
              </button>
              <button className="secondary" onClick={dispatchNow}>
                <IconBolt width={16} height={16} /> Cobrar esta base agora
              </button>
            </div>
          </>
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
            <p>Suba uma planilha acima para adicionar clientes a esta faixa.</p>
          </div>
        ) : (
          <div className="table-wrap">
            <table>
              <thead>
                <tr>
                  <th>Código</th>
                  <th>Nome</th>
                  <th>CPF</th>
                  <th>Celular</th>
                  <th>Valor</th>
                  <th>Status</th>
                  <th>Erro</th>
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
                    <th>Nome</th>
                    <th>Celular</th>
                    <th>Cluster</th>
                    <th>Dias de atraso</th>
                    <th>Valor a cobrar</th>
                    <th>Status</th>
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
            {leadsTotal > leads.length && (
              <p className="field-hint">Mostrando {leads.length} de {leadsTotal} leads — veja o restante em Leads.</p>
            )}
          </>
        )}
      </div>
    </div>
  );
}
