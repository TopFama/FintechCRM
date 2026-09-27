import { ReactNode, useEffect, useMemo, useState } from "react";
import { Link } from "react-router-dom";
import { api, urlImagemTemplate, CampoCliente, Faixa, FaixaEnvio, FaixaVariableMappingIn, Template, TemplateVariable, WhatsappNumber } from "../api";
import { IconAlert, IconCheckCircle, IconEye, IconPlus, IconTrash } from "../icons";

type MapeamentoEdicao = { fonte_tipo: "coluna" | "campo_cliente"; valor: string };

interface Props {
  faixa: Faixa;
  onAlterado: () => void;
  titulo?: string;
  // Texto abaixo do título; o padrão é o da faixa de atraso.
  /** null: sem texto embaixo do título. */
  descricao?: ReactNode;
  // Colunas da planilha de clientes da campanha, que podem alimentar variáveis.
  colunasPlanilha?: string[];
  // Dentro de outro card (segmento do remarketing): vira um sub-bloco.
  embutido?: boolean;
  // Complemento da pergunta de remover ("desta faixa", "desta campanha"...)
  rotuloAlvo?: string;
}

// Números e templates atribuídos a uma faixa (ou campanha): cada par número +
// template cobra em paralelo, com a fila compartilhada, e tem o próprio
// mapeamento de variáveis.
export default function EnviosFaixa({
  faixa,
  onAlterado,
  titulo = "Números e templates desta faixa",
  descricao,
  colunasPlanilha = [],
  embutido = false,
  rotuloAlvo = "desta faixa",
}: Props) {
  const [erro, setErro] = useState<string | null>(null);
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

  useEffect(() => {
    api.listTemplates().then(setTemplates).catch(() => undefined);
    api.listNumbers().then(setNumbers).catch(() => undefined);
    api.listCamposCliente().then(setCampos).catch(() => undefined);
  }, []);

  function mapeamentosParaEdicao(templateId: string): Record<string, MapeamentoEdicao> {
    const template = templates.find((t) => t.id === templateId);
    if (!template) return {};
    const existentes = faixa.variable_mappings.filter((m) => m.template_id === templateId) || [];
    const result: Record<string, MapeamentoEdicao> = {};
    for (const v of template.variables) {
      const existente = existentes.find((m) => m.template_variable_id === v.id);
      if (existente) {
        result[v.id] = {
          fonte_tipo: existente.fonte_tipo === "campo_cliente" ? "campo_cliente" : "coluna",
          valor: existente.column_name || "",
        };
      } else if (v.campo_sugerido) {
        // Sem mapeamento salvo: começa pelo campo sugerido no template
        // (ex.: "Valor em atraso" para a variável de valor).
        result[v.id] = { fonte_tipo: "campo_cliente", valor: v.campo_sugerido };
      }
      // Sem nenhum dos dois: fica sem entrada, pra a lista suspensa mostrar
      // o placeholder até o usuário escolher a origem.
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

  const numeroDoForm = numbers.find((n) => n.id === formNumberId) || null;
  const templateDoForm = templates.find((t) => t.id === formTemplateId) || null;

  // Templates que compartilham o mesmo nome (podem ser de WABAs diferentes)
  const templatesMesmoNome: Template[] = useMemo(() => {
    if (!templateDoForm) return [];
    return templates.filter(
      (t: Template) =>
        t.status === "approved" &&
        (t.name === templateDoForm.name || t.meta_template_name === templateDoForm.meta_template_name)
    );
  }, [templates, templateDoForm]);

  const wabasCompativeis = useMemo(
    () => new Set(templatesMesmoNome.map((t: Template) => t.waba_id).filter(Boolean)),
    [templatesMesmoNome]
  );

  // Template exato para a WABA do número selecionado
  const templateFinal: Template | null = useMemo(() => {
    if (!templateDoForm) return null;
    if (!numeroDoForm || !numeroDoForm.waba_id) return templateDoForm;
    const tplWaba = templatesMesmoNome.find((t: Template) => t.waba_id === numeroDoForm.waba_id);
    return tplWaba || templateDoForm;
  }, [templateDoForm, numeroDoForm, templatesMesmoNome]);

  // Templates aprovados para a lista suspensa (únicos por nome)
  const templatesAprovados = templates.filter(
    (t, idx, arr) => t.status === "approved" && arr.findIndex((x) => x.name === t.name) === idx
  );

  // Telefones disponíveis: libera telefones das WABAs que têm este template aprovado,
  // exceto números que já estão configurados nesta faixa (exceto o que está sendo editado).
  const numerosDisponiveis = numbers.filter((n) => {
    const jaUsado = (faixa.envios || []).some((e: FaixaEnvio) => e.whatsapp_number_id === n.id && e.id !== envioEditandoId);
    if (jaUsado) return false;
    if (!templateDoForm) return true;
    return wabasCompativeis.size === 0 || (n.waba_id && wabasCompativeis.has(n.waba_id));
  });

  function selecionarTemplateForm(templateId: string) {
    setFormTemplateId(templateId);
    const tpl = templates.find((t) => t.id === templateId);
    if (!tpl) {
      setFormMappings({});
      return;
    }
    const mesmoNome = templates.filter(
      (t) => t.status === "approved" && (t.name === tpl.name || t.meta_template_name === tpl.meta_template_name)
    );
    const wabas = new Set(mesmoNome.map((t) => t.waba_id).filter(Boolean));
    if (formNumberId) {
      const num = numbers.find((n) => n.id === formNumberId);
      if (num && wabas.size > 0 && !wabas.has(num.waba_id)) {
        setFormNumberId("");
        setFormMappings({});
      } else if (num && num.waba_id) {
        const tplWaba = mesmoNome.find((t) => t.waba_id === num.waba_id) || tpl;
        setFormMappings(mapeamentosParaEdicao(tplWaba.id));
      }
    } else {
      setFormMappings({});
    }
  }

  function selecionarNumeroForm(numberId: string) {
    setFormNumberId(numberId);
    if (!numberId || !templateDoForm) return;
    const num = numbers.find((n) => n.id === numberId);
    if (num && num.waba_id) {
      const tplWaba = templatesMesmoNome.find((t: Template) => t.waba_id === num.waba_id) || templateDoForm;
      setFormMappings(mapeamentosParaEdicao(tplWaba.id));
    }
  }

  function cancelarFormEnvio() {
    setMostrarFormEnvio(false);
    setEnvioEditandoId(null);
  }

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
    if (!formNumberId || !formTemplateId || !templateFinal) return;
    const semOrigem = templateFinal.variables.filter((v: TemplateVariable) => !formMappings[v.id]);
    if (semOrigem.length > 0) {
      setErro(`Selecione a origem de todas as variáveis (faltando: ${semOrigem.map((v: TemplateVariable) => v.internal_name).join(", ")})`);
      return;
    }
    setErro(null);
    setSalvandoEnvio(true);
    try {
      const variable_mappings: FaixaVariableMappingIn[] = templateFinal.variables.map((v: TemplateVariable) => {
        const m = formMappings[v.id];
        return { template_variable_id: v.id, fonte_tipo: m.fonte_tipo, column_name: m.valor };
      });
      if (envioEditandoId) {
        await api.atualizarEnvio(faixa.id, envioEditandoId, {
          whatsapp_number_id: formNumberId,
          template_id: templateFinal.id,
          active: formAtivo,
          variable_mappings,
        });
      } else {
        await api.adicionarEnvio(faixa.id, {
          whatsapp_number_id: formNumberId,
          template_id: templateFinal.id,
          variable_mappings,
        });
      }
      setMostrarFormEnvio(false);
      setEnvioEditandoId(null);
      setEnvioMsg(envioEditandoId ? "Envio atualizado" : "Envio adicionado");
      onAlterado();
    } catch (err) {
      setErro(err instanceof Error ? err.message : "Erro ao salvar envio");
    } finally {
      setSalvandoEnvio(false);
    }
  }

  async function handleExcluirEnvio(envio: FaixaEnvio) {
    if (
      !window.confirm(
        `Remover ${envio.whatsapp_number.label || envio.whatsapp_number.display_phone_number} (${envio.template.name}) ${rotuloAlvo}?`
      )
    )
      return;
    setErro(null);
    setExcluindoEnvioId(envio.id);
    try {
      await api.excluirEnvio(faixa.id, envio.id);
      onAlterado();
    } catch (err) {
      setErro(err instanceof Error ? err.message : "Erro ao remover envio");
    } finally {
      setExcluindoEnvioId(null);
    }
  }

  return (
    <>
      <div className={embutido ? "sub-card" : "card"} style={embutido ? { marginTop: 16 } : undefined}>
        <div className="card-header">
          {embutido ? <h4 style={{ margin: 0 }}>{titulo}</h4> : <h3>{titulo}</h3>}
          <button type="button" className="secondary small" onClick={abrirNovoEnvio}>
            <IconPlus width={16} height={16} /> Adicionar número e template
          </button>
        </div>
        {descricao !== null && (
          <p className="card-subtitle" style={{ marginTop: 0 }}>
            {descricao ?? (
              <>
                Cada número pode cobrar com um template próprio, em paralelo (WABAs diferentes) — a fila é compartilhada
                entre eles, então nenhum cliente é cobrado duas vezes. O agendamento de cada um (dias, horário, intervalo)
                fica em <Link to="/configuracoes?aba=horario">Configurações → Horário</Link>.
              </>
            )}
          </p>
        )}

        {erro && (
          <div className="error-box" style={{ marginBottom: 16 }}>
            <IconAlert width={16} height={16} />
            <span>{erro}</span>
          </div>
        )}

        {envioMsg && (
          <div className="success-box" style={{ marginBottom: 16 }}>
            <IconCheckCircle width={16} height={16} />
            <span>{envioMsg}</span>
          </div>
        )}

        {faixa.envios.length === 0 && !mostrarFormEnvio && (
          <p className="text-muted">
            {embutido
              ? 'Nenhum template vinculado ainda. Clique em "Adicionar número e template".'
              : "Nenhum número/template atribuído ainda — adicione um acima para poder subir a planilha e ligar o disparo."}
          </p>
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
                <label htmlFor="faixa-template">Template</label>
                <select id="faixa-template" value={formTemplateId} onChange={(e) => selecionarTemplateForm(e.target.value)}>
                  <option value="">Selecione o template...</option>
                  {templatesAprovados.map((t) => (
                    <option key={t.id} value={t.id}>
                      {t.name}
                    </option>
                  ))}
                </select>
                {templateFinal?.header_type === "image" && !templateFinal.image_url && (
                  <span className="field-hint" role="alert" style={{ color: "var(--color-danger)" }}>
                    Este template tem cabeçalho de imagem e ainda não tem imagem. Suba em Configurações → Templates, senão o envio dá erro.
                  </span>
                )}
              </div>
              <div className="field">
                <label htmlFor="faixa-numero-de-envio">Número de envio</label>
                <div style={{ display: "flex", gap: 8, alignItems: "center" }}>
                  <select
                    id="faixa-numero-de-envio"
                    value={formNumberId}
                    onChange={(e) => selecionarNumeroForm(e.target.value)}
                    style={{ flex: 1, minWidth: 0 }}
                  >
                    <option value="">{formTemplateId ? "Selecione o número..." : "Selecione o template primeiro..."}</option>
                    {numerosDisponiveis.map((n) => (
                      <option key={n.id} value={n.id}>
                        {n.label || n.display_phone_number} ({n.display_phone_number})
                      </option>
                    ))}
                  </select>
                  <button
                    type="button"
                    className="secondary small"
                    style={{ flexShrink: 0 }}
                    disabled={!formNumberId || !templateFinal}
                    onClick={() => setMostrarPreviewEnvio((atual) => !atual)}
                    title={!formNumberId ? "Selecione o número para pré-visualizar o template" : ""}
                  >
                    <IconEye width={14} height={14} /> {mostrarPreviewEnvio ? "Fechar" : "Pré-visualizar"}
                  </button>
                </div>
                {numbers.length === 0 ? (
                  <p className="field-hint">Nenhum número ainda — importe os números da WABA em Configurações.</p>
                ) : formTemplateId && numerosDisponiveis.length === 0 ? (
                  <p className="field-hint" style={{ color: "var(--color-danger)" }}>
                    Nenhum número cadastrado para a WABA deste template.
                  </p>
                ) : null}
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

            {formTemplateId && !formNumberId && (
              <p className="field-hint" style={{ marginTop: 12 }}>
                Selecione o número de envio para carregar as variáveis e poder pré-visualizar o template desta WABA.
              </p>
            )}

            {templateFinal && formNumberId && mostrarPreviewEnvio && (
              <div className="template-preview">
                <div className="template-preview-bubble">
                  {templateFinal.header_type === "image" && templateFinal.image_url && (
                    <img
                      src={urlImagemTemplate(templateFinal.image_url)}
                      alt="Cabeçalho do template"
                      style={{ width: "100%", maxWidth: 280, borderRadius: 8, marginBottom: 10, display: "block" }}
                    />
                  )}
                  {renderizarPreviewForm(templateFinal)}
                </div>
                <p className="field-hint">
                  Valores entre colchetes vêm de "Coluna da planilha" (só o nome sugerido — o valor real é o da
                  planilha subida); os demais usam o exemplo do campo do cliente escolhido.
                </p>
              </div>
            )}

            {templateFinal && formNumberId && templateFinal.variables.length > 0 && (
              <>
                <label style={{ marginBottom: 8, marginTop: 16, display: "block" }}>Variáveis do template</label>
                <div className="form-row" style={{ flexWrap: "wrap" }}>
                  {templateFinal.variables.map((v: TemplateVariable) => {
                    const m = formMappings[v.id];
                    const selectValue = !m
                      ? ""
                      : m.fonte_tipo === "campo_cliente"
                        ? `campo:${m.valor}`
                        : colunasPlanilha.includes(m.valor)
                          ? `coluna:${m.valor}`
                          : "";
                    return (
                      <div className="field" key={v.id} style={{ minWidth: 260 }}>
                        <label htmlFor={`faixa-var-${v.id}`}>
                          {`{{${v.position}}}`} ({v.internal_name})
                        </label>
                        <div style={{ display: "flex", gap: 6, minWidth: 0, flexDirection: "column" }}>
                          <select id={`faixa-var-${v.id}`}
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
                                const [tipo, ...resto] = valorSelect.split(":");
                                setFormMappings((atual) => ({
                                  ...atual,
                                  [v.id]: {
                                    fonte_tipo: tipo === "coluna" ? "coluna" : "campo_cliente",
                                    valor: resto.join(":"),
                                  },
                                }));
                              }
                            }}
                          >
                            <option value="" disabled>
                              Selecione o campo do cliente...
                            </option>
                            {colunasPlanilha.length > 0 ? (
                              <>
                                <optgroup label="Campos do cliente">
                                  {campos.map((c) => (
                                    <option key={c.campo} value={`campo:${c.campo}`}>
                                      {c.rotulo}
                                    </option>
                                  ))}
                                </optgroup>
                                <optgroup label="Colunas da planilha da campanha">
                                  {colunasPlanilha.map((c) => (
                                    <option key={c} value={`coluna:${c}`}>
                                      {c}
                                    </option>
                                  ))}
                                </optgroup>
                              </>
                            ) : (
                              campos.map((c) => (
                                <option key={c.campo} value={`campo:${c.campo}`}>
                                  {c.rotulo}
                                </option>
                              ))
                            )}
                          </select>
                        </div>
                      </div>
                    );
                  })}
                </div>
                <p className="field-hint">
                  {colunasPlanilha.length > 0
                    ? "As colunas da planilha só são usadas quando a campanha envia com os valores da planilha."
                    : "Vale só para envios gerados dentro do sistema. Na importação de planilha, cada variável é mapeada para uma coluna."}
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
    </>
  );
}
