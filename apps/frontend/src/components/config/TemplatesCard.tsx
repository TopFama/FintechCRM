import { Fragment, FormEvent, useEffect, useMemo, useState } from "react";
import { api, CampoCliente, ImagemPendente, Template, urlImagemTemplate, WhatsappNumber } from "../../api";
import SortableTh from "../SortableTh";
import { IconAlert, IconCheckCircle, IconEye, IconPlus, IconTemplate } from "../../icons";
import { ordenarPor, useSort } from "../../sort";

type ColunaTemplate = "meta_template_name" | "waba_id" | "status";

// Imagem que precisou ser comprimida: o usuário vê a original ao lado da
// otimizada e decide se usa; só depois de aprovar ela entra no template.
type ImagemEmValidacao = {
  templateId: string;
  templateNome: string;
  urlOriginal: string;
  pendente: ImagemPendente;
};

function formatarTamanho(bytes: number): string {
  return bytes >= 1024 * 1024
    ? `${(bytes / (1024 * 1024)).toLocaleString("pt-BR", { maximumFractionDigits: 1 })} MB`
    : `${Math.max(1, Math.round(bytes / 1024))} KB`;
}

function rotuloStatusTemplate(status: string): string {
  switch (status.toLowerCase()) {
    case "approved":
      return "Aprovado";
    case "pending":
      return "Pendente";
    case "rejected":
      return "Rejeitado";
    case "draft":
      return "Rascunho";
    default:
      return status;
  }
}

// Templates de WhatsApp aprovados na Meta, usados pelas faixas de cobrança —
// vive em Configurações porque é infraestrutura compartilhada entre faixas,
// não uma configuração de uma faixa específica.
export default function TemplatesCard() {
  const [templates, setTemplates] = useState<Template[]>([]);
  const [numbers, setNumbers] = useState<WhatsappNumber[]>([]);
  const telefonesPorWaba = useMemo(() => {
    const mapa = new Map<string, string[]>();
    for (const n of numbers) {
      if (!n.waba_id) continue;
      const tel = (n.display_phone_number || n.phone_number_id || "").trim();
      if (!tel) continue;
      const list = mapa.get(n.waba_id) || [];
      if (!list.includes(tel)) {
        list.push(tel);
      }
      mapa.set(n.waba_id, list);
    }
    return mapa;
  }, [numbers]);

  const templatesSort = useSort<ColunaTemplate>();
  const templatesOrdenados = ordenarPor(
    templates,
    templatesSort.sortKey
      ? (t: Template) => {
          if (templatesSort.sortKey === "waba_id") return t.waba_id || "";
          if (templatesSort.sortKey === "meta_template_name") return t.meta_template_name;
          if (templatesSort.sortKey === "status") return t.status;
          return "";
        }
      : null,
    templatesSort.sortDir
  );
  const [campos, setCampos] = useState<CampoCliente[]>([]);
  const [previewId, setPreviewId] = useState<string | null>(null);
  const [selectedWabaId, setSelectedWabaId] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [aviso, setAviso] = useState<string | null>(null);
  const [emValidacao, setEmValidacao] = useState<ImagemEmValidacao | null>(null);
  const [decidindo, setDecidindo] = useState(false);
  const [subindoImagem, setSubindoImagem] = useState<string | null>(null);
  const [showCreate, setShowCreate] = useState(false);
  const [syncing, setSyncing] = useState(false);
  const [saving, setSaving] = useState(false);
  const [testeTemplateId, setTesteTemplateId] = useState<string | null>(null);
  const [testeNumeroId, setTesteNumeroId] = useState("");
  const [testeCelular, setTesteCelular] = useState("");
  const [testeVariaveis, setTesteVariaveis] = useState<Record<string, string>>({});
  const [testeEnviando, setTesteEnviando] = useState(false);
  const [testeResultado, setTesteResultado] = useState<{ ok: boolean; detalhe: string } | null>(null);
  const [form, setForm] = useState({
    name: "",
    meta_template_name: "",
    language: "pt_BR",
    category: "UTILITY",
    header_type: "none" as "none" | "image",
    body_text: "",
    submit_to_meta: false,
  });

  const wabaIds = useMemo(
    () => Array.from(new Set(numbers.map((n) => n.waba_id))),
    [numbers]
  );

  function load() {
    api.listTemplates().then(setTemplates).catch((e) => setError(e.message));
    api.listNumbers().then(setNumbers).catch(() => undefined);
  }

  useEffect(load, []);
  useEffect(() => {
    api.listCamposCliente().then(setCampos).catch(() => undefined);
  }, []);

  function renderizarPreview(t: Template): string {
    return t.body_text.replace(/\{\{(\d+)\}\}/g, (match, pos) => {
      const variavel = t.variables.find((v) => v.position === Number(pos));
      const campo = variavel?.campo_sugerido
        ? campos.find((c) => c.campo === variavel.campo_sugerido)
        : undefined;
      return campo ? campo.exemplo : `${match} (não mapeado)`;
    });
  }

  function abrirTesteTemplate(t: Template) {
    if (testeTemplateId === t.id) {
      setTesteTemplateId(null);
      return;
    }
    setTesteTemplateId(t.id);
    setTesteResultado(null);
    const numsWaba = numbers.filter((n) => !t.waba_id || n.waba_id === t.waba_id);
    if (!testeNumeroId || !numsWaba.some((n) => n.id === testeNumeroId)) {
      setTesteNumeroId(numsWaba[0]?.id || "");
    }
    const vars: Record<string, string> = {};
    for (const v of t.variables) {
      const campo = v.campo_sugerido ? campos.find((c) => c.campo === v.campo_sugerido) : undefined;
      vars[v.internal_name] = campo ? campo.exemplo : "";
    }
    setTesteVariaveis(vars);
  }

  function renderizarPreviewComValores(t: Template, vars: Record<string, string>): string {
    return t.body_text.replace(/\{\{(\d+)\}\}/g, (match, pos) => {
      const variavel = t.variables.find((v) => v.position === Number(pos));
      const valor = variavel ? vars[variavel.internal_name] : undefined;
      return valor !== undefined && valor !== "" ? valor : match;
    });
  }

  async function handleEnviarTeste(t: Template) {
    if (!testeNumeroId || !testeCelular.trim()) return;
    const numEscolhido = numbers.find((n) => n.id === testeNumeroId);
    if (t.waba_id && numEscolhido?.waba_id && t.waba_id !== numEscolhido.waba_id) {
      setTesteResultado({
        ok: false,
        detalhe: "O número selecionado não pertence à mesma WABA deste template.",
      });
      return;
    }
    setTesteEnviando(true);
    setTesteResultado(null);
    try {
      const res = await api.testarEnvioTemplate(t.id, {
        whatsapp_number_id: testeNumeroId,
        celular: testeCelular.trim(),
        variables: testeVariaveis,
      });
      setTesteResultado(res);
    } catch (err) {
      setTesteResultado({
        ok: false,
        detalhe: err instanceof Error ? err.message : "Erro ao testar envio",
      });
    } finally {
      setTesteEnviando(false);
    }
  }

  async function handleCampoSugerido(templateId: string, variavelId: string, campo: string) {
    try {
      const atualizada = await api.atualizarVariavelTemplate(templateId, variavelId, campo || null);
      setTemplates((atual) =>
        atual.map((t) =>
          t.id !== templateId
            ? t
            : { ...t, variables: t.variables.map((v) => (v.id === variavelId ? atualizada : v)) }
        )
      );
    } catch (err) {
      setError(err instanceof Error ? err.message : "Erro ao salvar mapeamento da variável");
    }
  }

  async function handleSync() {
    setError(null);
    setSyncing(true);
    try {
      await api.syncTemplatesFromMeta();
      load();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Erro ao sincronizar com a Meta");
    } finally {
      setSyncing(false);
    }
  }

  function detectVariables(bodyText: string) {
    const matches = Array.from(bodyText.matchAll(/\{\{(\d+)\}\}/g)).map((m) => Number(m[1]));
    const positions = Array.from(new Set(matches)).sort((a, b) => a - b);
    return positions.map((position) => ({ position, internal_name: `variavel_${position}` }));
  }

  async function handleCreate(e: FormEvent) {
    e.preventDefault();
    setError(null);
    setSaving(true);
    try {
      const variables = detectVariables(form.body_text);
      const payload = { ...form, variables, waba_id: wabaIds.length > 1 ? selectedWabaId : undefined };
      await api.createTemplate(payload);
      setShowCreate(false);
      setForm({
        name: "",
        meta_template_name: "",
        language: "pt_BR",
        category: "UTILITY",
        header_type: "none",
        body_text: "",
        submit_to_meta: false,
      });
      load();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Erro ao criar template");
    } finally {
      setSaving(false);
    }
  }

  async function handleRefreshStatus(id: string) {
    try {
      await api.refreshTemplateStatus(id);
      load();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Erro ao consultar status");
    }
  }

  function fecharValidacao() {
    if (emValidacao) URL.revokeObjectURL(emValidacao.urlOriginal);
    setEmValidacao(null);
  }

  async function handleImageUpload(t: Template, file: File) {
    setError(null);
    setAviso(null);
    setSubindoImagem(t.id);
    try {
      const resultado = await api.uploadTemplateImage(t.id, file);
      if (resultado.pendente) {
        fecharValidacao();
        setEmValidacao({
          templateId: t.id,
          templateNome: t.name,
          urlOriginal: URL.createObjectURL(file),
          pendente: resultado.pendente,
        });
      }
      load();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Erro ao subir imagem");
    } finally {
      setSubindoImagem(null);
    }
  }

  async function aprovarImagem() {
    if (!emValidacao) return;
    setDecidindo(true);
    try {
      await api.confirmarImagemOtimizada(emValidacao.templateId, emValidacao.pendente.token);
      setAviso(`Imagem otimizada salva no template "${emValidacao.templateNome}".`);
      fecharValidacao();
      load();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Erro ao salvar a imagem");
      fecharValidacao();
    } finally {
      setDecidindo(false);
    }
  }

  async function recusarImagem() {
    if (!emValidacao) return;
    setDecidindo(true);
    try {
      await api.descartarImagemOtimizada(emValidacao.templateId, emValidacao.pendente.token);
    } catch {
      // descartar é só limpeza: a versão pendente expira sozinha
    } finally {
      setError(
        `Imagem não salva no template "${emValidacao.templateNome}". Para usar a imagem sem compressão, é necessário subir uma imagem de até 5 MB (.jpg ou .png).`
      );
      fecharValidacao();
      setDecidindo(false);
    }
  }

  async function handleRemoverImagem(t: Template) {
    if (!window.confirm(`Deseja realmente remover a imagem do template "${t.name}"?`)) return;
    try {
      const atualizado = await api.removerImagemTemplate(t.id);
      setTemplates((prev) => prev.map((item) => (item.id === t.id ? atualizado : item)));
      setAviso(`Imagem do template "${t.name}" removida com sucesso.`);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Erro ao remover imagem do template");
    }
  }

  return (
    <>
      {error && (
        <div className="error-box">
          <IconAlert width={16} height={16} />
          <span>{error}</span>
        </div>
      )}
      {aviso && (
        <div className="success-box">
          <IconCheckCircle width={16} height={16} />
          <span>{aviso}</span>
        </div>
      )}

      {emValidacao && (
        <div className="card" aria-labelledby="validar-imagem-titulo">
          <div className="card-header">
            <h3 id="validar-imagem-titulo">Validar imagem otimizada: {emValidacao.templateNome}</h3>
          </div>
          <p className="card-subtitle">
            A imagem enviada precisou ser otimizada para o que o WhatsApp aceita (até 5 MB, .jpg ou .png) e ficou
            com {formatarTamanho(emValidacao.pendente.tamanho_final)} (era{" "}
            {formatarTamanho(emValidacao.pendente.tamanho_original)}). Confira se ela ficou boa: ela só vai para o
            template se você aprovar.
          </p>
          <div className="comparacao-imagens">
            <figure>
              <img src={emValidacao.urlOriginal} alt="Imagem original enviada" />
              <figcaption>
                Original · {emValidacao.pendente.formato_original} · {emValidacao.pendente.largura_original}×
                {emValidacao.pendente.altura_original} · {formatarTamanho(emValidacao.pendente.tamanho_original)}
              </figcaption>
            </figure>
            <figure>
              <img src={urlImagemTemplate(emValidacao.pendente.url_previa)} alt="Imagem otimizada" />
              <figcaption>
                Otimizada · {emValidacao.pendente.formato_final}
                {emValidacao.pendente.qualidade != null && ` (qualidade ${emValidacao.pendente.qualidade})`} ·{" "}
                {emValidacao.pendente.largura}×{emValidacao.pendente.altura} ·{" "}
                {formatarTamanho(emValidacao.pendente.tamanho_final)}
              </figcaption>
            </figure>
          </div>
          <div className="actions-row">
            <button onClick={aprovarImagem} disabled={decidindo}>
              {decidindo ? "Salvando..." : "Usar imagem otimizada"}
            </button>
            <button className="secondary" onClick={recusarImagem} disabled={decidindo}>
              Não usar
            </button>
          </div>
        </div>
      )}

      <div className="card">
        <div className="card-header">
          <h3>Sincronizar templates da Meta</h3>
        </div>
        <p className="card-subtitle">
          Puxa os templates já aprovados/pendentes direto da Meta para as WABAs dos tokens cadastrados em
          Configurações — não precisa informar o WABA ID na mão.
        </p>
        <button onClick={handleSync} disabled={syncing}>
          {syncing ? "Sincronizando..." : "Sincronizar"}
        </button>
        {numbers.length === 0 && (
          <p className="field-hint">
            Se ainda não há token da Meta, cadastre um em Configurações → Tokens da Meta antes de sincronizar.
          </p>
        )}
      </div>

      <div className="card">
        <div className="card-header">
          <h3>Novo template</h3>
          <button className="secondary" onClick={() => setShowCreate((v) => !v)}>
            {showCreate ? "Cancelar" : (
              <>
                <IconPlus width={16} height={16} /> Criar template
              </>
            )}
          </button>
        </div>
        {showCreate && (
          <form onSubmit={handleCreate}>
            <div className="form-row">
              <div className="field">
                <label htmlFor="tpl-nome-interno">Nome interno</label>
                <input id="tpl-nome-interno" value={form.name} onChange={(e) => setForm({ ...form, name: e.target.value })} required />
              </div>
              <div className="field">
                <label htmlFor="tpl-nome-do-template">Nome do template na Meta (snake_case)</label>
                <input id="tpl-nome-do-template"
                  value={form.meta_template_name}
                  onChange={(e) => setForm({ ...form, meta_template_name: e.target.value })}
                  required
                />
              </div>
            </div>
            <div className="form-row">
              {wabaIds.length > 1 && (
                <div className="field">
                  <label htmlFor="tpl-waba">WABA</label>
                  <select id="tpl-waba" value={selectedWabaId} onChange={(e) => setSelectedWabaId(e.target.value)} required>
                    <option value="">Selecione...</option>
                    {wabaIds.map((id) => (
                      <option key={id} value={id}>
                        {id}
                      </option>
                    ))}
                  </select>
                </div>
              )}
              <div className="field">
                <label htmlFor="tpl-idioma">Idioma</label>
                <input id="tpl-idioma" value={form.language} onChange={(e) => setForm({ ...form, language: e.target.value })} />
              </div>
            </div>
            <div className="form-row">
              <div className="field">
                <label htmlFor="tpl-categoria">Categoria</label>
                <select id="tpl-categoria" value={form.category} onChange={(e) => setForm({ ...form, category: e.target.value })}>
                  <option value="UTILITY">UTILITY</option>
                  <option value="MARKETING">MARKETING</option>
                  <option value="AUTHENTICATION">AUTHENTICATION</option>
                </select>
              </div>
              <div className="field">
                <label htmlFor="tpl-cabecalho-com-imagem">Cabeçalho com imagem?</label>
                <select id="tpl-cabecalho-com-imagem"
                  value={form.header_type}
                  onChange={(e) => setForm({ ...form, header_type: e.target.value as "none" | "image" })}
                >
                  <option value="none">Não</option>
                  <option value="image">Sim</option>
                </select>
              </div>
            </div>
            <div className="field">
              <label htmlFor="tpl-corpo-do-template">Corpo do template (use {"{{1}}"}, {"{{2}}"}... para variáveis)</label>
              <textarea id="tpl-corpo-do-template"
                rows={4}
                value={form.body_text}
                onChange={(e) => setForm({ ...form, body_text: e.target.value })}
                required
              />
              <p className="field-hint">
                Variáveis detectadas: {detectVariables(form.body_text).map((v) => v.internal_name).join(", ") || "nenhuma"}
              </p>
            </div>
            <div className="field">
              <label className="checkbox-row">
                <input
                  type="checkbox"
                  checked={form.submit_to_meta}
                  onChange={(e) => setForm({ ...form, submit_to_meta: e.target.checked })}
                />
                Enviar já para análise na Meta
              </label>
            </div>
            <button type="submit" disabled={saving}>
              {saving ? "Salvando..." : "Salvar template"}
            </button>
          </form>
        )}
      </div>

      <div className="card">
        <div className="card-header">
          <h3>Templates cadastrados</h3>
        </div>
        {templates.length === 0 ? (
          <div className="empty-state">
            <IconTemplate width={28} height={28} />
            <div className="title">Nenhum template cadastrado</div>
            <p>Sincronize com a Meta ou crie um template acima.</p>
          </div>
        ) : (
          <div className="table-wrap">
            <table className="tabela-compacta">
              <thead>
                <tr>
                  <SortableTh
                    active={templatesSort.sortKey === "meta_template_name"}
                    dir={templatesSort.sortDir}
                    onSort={() => templatesSort.toggleSort("meta_template_name")}
                  >
                    Template (Meta)
                  </SortableTh>
                  <SortableTh
                    active={templatesSort.sortKey === "waba_id"}
                    dir={templatesSort.sortDir}
                    onSort={() => templatesSort.toggleSort("waba_id")}
                  >
                    WABA
                  </SortableTh>
                  <th>Telefones</th>
                  <SortableTh active={templatesSort.sortKey === "status"} dir={templatesSort.sortDir} onSort={() => templatesSort.toggleSort("status")}>
                    Status
                  </SortableTh>
                  <th>Variáveis</th>
                  <th>Imagem</th>
                  <th style={{ textAlign: "right" }}></th>
                </tr>
              </thead>
              <tbody>
                {templatesOrdenados.map((t) => {
                  const tels = (t.waba_id ? telefonesPorWaba.get(t.waba_id) : null) || [];
                  return (
                    <Fragment key={t.id}>
                      <tr>
                        <td className="cell-strong" style={{ wordBreak: "break-word" }}>
                          {t.meta_template_name}
                        </td>
                        <td className="text-muted" style={{ fontFamily: "monospace", fontSize: 12, wordBreak: "break-all" }}>
                          {t.waba_id || "—"}
                        </td>
                        <td className="text-muted" style={{ fontSize: 12.5, wordBreak: "break-word" }}>
                          {tels.length > 0 ? tels.join("; ") : "—"}
                        </td>
                        <td>
                          <span className={`badge ${t.status}`}>{rotuloStatusTemplate(t.status)}</span>
                        </td>
                        <td className="text-muted" style={{ wordBreak: "break-word", fontSize: 12 }}>
                          {t.variables.map((v) => v.internal_name).join(", ") || "—"}
                        </td>
                        <td style={{ whiteSpace: "nowrap" }}>
                          {t.header_type === "image" ? (
                            <span style={{ display: "inline-flex", gap: 8, alignItems: "center" }}>
                              {t.image_url && <span className="badge sent">enviada</span>}
                              {subindoImagem === t.id && <span className="text-muted">Enviando e otimizando…</span>}
                              {/* trocar: imagem antiga (sem link público) ou arte nova */}
                              <label style={{ cursor: "pointer", color: "var(--color-primary)", fontWeight: 600 }}>
                                {t.image_url ? "trocar" : "subir"}
                                <input
                                  type="file"
                                  accept="image/*"
                                  style={{ display: "none" }}
                                  onChange={(e) => {
                                    const arquivo = e.target.files?.[0];
                                    e.target.value = "";
                                    if (arquivo) handleImageUpload(t, arquivo);
                                  }}
                                />
                              </label>
                              {t.image_url && (
                                <button
                                  type="button"
                                  className="ghost small"
                                  style={{ color: "var(--color-danger)", padding: "0 4px", fontSize: 12, fontWeight: 600 }}
                                  onClick={() => handleRemoverImagem(t)}
                                  title="Remover imagem deste template"
                                >
                                  remover
                                </button>
                              )}
                            </span>
                          ) : (
                            <span className="text-faint">—</span>
                          )}
                        </td>
                        <td style={{ textAlign: "right" }}>
                          <div style={{ display: "flex", gap: 4, alignItems: "center", justifyContent: "flex-end", flexWrap: "wrap" }}>
                            <button
                              type="button"
                              className="secondary small"
                              style={{ padding: "4px 8px", fontSize: 12, whiteSpace: "nowrap" }}
                              onClick={() => handleRefreshStatus(t.id)}
                            >
                              Atualizar status
                            </button>
                            <button
                              type="button"
                              className="secondary small"
                              style={{ padding: "4px 8px", fontSize: 12, whiteSpace: "nowrap" }}
                              onClick={() => setPreviewId((atual) => (atual === t.id ? null : t.id))}
                            >
                              <IconEye width={14} height={14} /> {previewId === t.id ? "Fechar" : "Pré-visualizar"}
                            </button>
                            <button
                              type="button"
                              className="secondary small"
                              style={{ padding: "4px 8px", fontSize: 12, whiteSpace: "nowrap" }}
                              onClick={() => abrirTesteTemplate(t)}
                            >
                              <IconTemplate width={14} height={14} /> {testeTemplateId === t.id ? "Fechar teste" : "Testar envio"}
                            </button>
                          </div>
                        </td>
                      </tr>
                      {previewId === t.id && (
                        <tr>
                          <td colSpan={7}>
                            <div className="template-preview">
                              <div className="template-preview-bubble">{renderizarPreview(t)}</div>
                              {t.variables.length === 0 ? (
                                <p className="field-hint">Este template não tem variáveis.</p>
                              ) : (
                                <div className="template-preview-vars">
                                  {t.variables.map((v) => (
                                    <div className="field" key={v.id}>
                                      <label htmlFor={`tpl-var-${v.id}`}>{`{{${v.position}}}`} ({v.internal_name})</label>
                                      <select id={`tpl-var-${v.id}`}
                                        value={v.campo_sugerido || ""}
                                        onChange={(e) => handleCampoSugerido(t.id, v.id, e.target.value)}
                                      >
                                        <option value="">Não mapeado</option>
                                        {campos.map((c) => (
                                          <option key={c.campo} value={c.campo}>
                                            {c.rotulo}
                                          </option>
                                        ))}
                                      </select>
                                    </div>
                                  ))}
                                </div>
                              )}
                            </div>
                          </td>
                        </tr>
                      )}
                      {testeTemplateId === t.id && (
                        <tr>
                          <td colSpan={7}>
                            <div className="card" style={{ margin: "8px 0", background: "var(--color-bg-subtle, #f9fafb)", border: "1px solid var(--color-border)" }}>
                              <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 8 }}>
                                <h4 style={{ margin: 0 }}>Testar template: {t.meta_template_name} ({t.language})</h4>
                              <button type="button" className="secondary small" onClick={() => setTesteTemplateId(null)}>
                                Fechar
                              </button>
                            </div>
                            <p className="card-subtitle" style={{ marginBottom: 12 }}>
                              Dispara uma mensagem de teste real para o celular informado com os valores das variáveis abaixo.
                              <strong style={{ display: "block", marginTop: 4 }}>
                                Atenção: este envio de teste não entra na fila e nem conta nos enviados do dia.
                              </strong>
                            </p>
                            <div className="form-row">
                              <div className="field">
                                <label htmlFor={`teste-num-${t.id}`}>Número de origem</label>
                                <select
                                  id={`teste-num-${t.id}`}
                                  value={testeNumeroId}
                                  onChange={(e) => setTesteNumeroId(e.target.value)}
                                >
                                  <option value="">Selecione o número...</option>
                                  {numbers
                                    .filter((n) => !t.waba_id || n.waba_id === t.waba_id)
                                    .map((n) => (
                                      <option key={n.id} value={n.id}>
                                        {n.label} ({n.display_phone_number})
                                      </option>
                                    ))}
                                </select>
                                {numbers.filter((n) => !t.waba_id || n.waba_id === t.waba_id).length === 0 && (
                                  <p className="field-hint" style={{ color: "var(--color-danger)" }}>
                                    Nenhum número cadastrado para a WABA deste template ({t.waba_id || "sem WABA"}).
                                  </p>
                                )}
                              </div>
                              <div className="field">
                                <label htmlFor={`teste-cel-${t.id}`}>Celular de destino</label>
                                <input
                                  id={`teste-cel-${t.id}`}
                                  value={testeCelular}
                                  onChange={(e) => setTesteCelular(e.target.value)}
                                  placeholder="55DDDNÚMERO"
                                />
                              </div>
                            </div>

                            {t.variables.length > 0 && (
                              <div style={{ marginTop: 12 }}>
                                <label style={{ fontWeight: 600, display: "block", marginBottom: 6 }}>
                                  Valores das variáveis (preencha para testar):
                                </label>
                                <div className="form-row" style={{ flexWrap: "wrap", gap: 12 }}>
                                  {t.variables.map((v) => (
                                    <div className="field" key={v.id} style={{ minWidth: 200, flex: "1 1 200px" }}>
                                      <label htmlFor={`teste-var-${v.id}`}>
                                        {`{{${v.position}}}`} ({v.internal_name})
                                      </label>
                                      <input
                                        id={`teste-var-${v.id}`}
                                        value={testeVariaveis[v.internal_name] ?? ""}
                                        onChange={(e) =>
                                          setTesteVariaveis((prev) => ({ ...prev, [v.internal_name]: e.target.value }))
                                        }
                                        placeholder={`Valor para {{${v.position}}}`}
                                      />
                                    </div>
                                  ))}
                                </div>
                              </div>
                            )}

                            <div className="template-preview" style={{ marginTop: 12, marginBottom: 12 }}>
                              <div className="template-preview-bubble">
                                {renderizarPreviewComValores(t, testeVariaveis)}
                              </div>
                            </div>

                            <div className="actions-row" style={{ marginTop: 16 }}>
                              <button
                                type="button"
                                disabled={testeEnviando || !testeNumeroId || !testeCelular.trim()}
                                onClick={() => handleEnviarTeste(t)}
                              >
                                {testeEnviando ? "Enviando teste..." : "Enviar teste"}
                              </button>
                              <button
                                type="button"
                                className="secondary"
                                onClick={() => setTesteTemplateId(null)}
                              >
                                Fechar
                              </button>
                            </div>

                            {testeResultado && (
                              <p
                                className={testeResultado.ok ? "field-success" : "field-error"}
                                style={{ marginTop: 10, fontWeight: 500 }}
                              >
                                {testeResultado.detalhe}
                              </p>
                            )}
                          </div>
                        </td>
                      </tr>
                    )}
                  </Fragment>
                );
              })}
              </tbody>
            </table>
          </div>
        )}
      </div>
    </>
  );
}
