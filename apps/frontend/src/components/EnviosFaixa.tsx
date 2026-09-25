import { ReactNode, useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { api, CampoCliente, Faixa, FaixaEnvio, FaixaVariableMappingIn, Template, WhatsappNumber } from "../api";
import { IconAlert, IconCheckCircle, IconEye, IconPlus, IconTrash } from "../icons";

type MapeamentoEdicao = { fonte_tipo: "coluna" | "campo_cliente"; valor: string };

interface Props {
  faixa: Faixa;
  onAlterado: () => void;
  titulo?: string;
  // Texto abaixo do título; o padrão é o da faixa de atraso.
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
    (n) => n.id === formNumberId || !faixa.envios.some((e) => e.whatsapp_number_id === n.id && e.id !== envioEditandoId)
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
    if (!formNumberId || !formTemplateId || !templateDoForm) return;
    const semOrigem = templateDoForm.variables.filter((v) => !formMappings[v.id]);
    if (semOrigem.length > 0) {
      setErro(`Selecione a origem de todas as variáveis (faltando: ${semOrigem.map((v) => v.internal_name).join(", ")})`);
      return;
    }
    setErro(null);
    setSalvandoEnvio(true);
    try {
      const variable_mappings: FaixaVariableMappingIn[] = templateDoForm.variables.map((v) => {
        const m = formMappings[v.id];
        return { template_variable_id: v.id, fonte_tipo: m.fonte_tipo, column_name: m.valor };
      });
      if (envioEditandoId) {
        await api.atualizarEnvio(faixa.id, envioEditandoId, {
          whatsapp_number_id: formNumberId,
          template_id: formTemplateId,
          active: formAtivo,
          variable_mappings,
        });
      } else {
        await api.adicionarEnvio(faixa.id, {
          whatsapp_number_id: formNumberId,
          template_id: formTemplateId,
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
        <p className="card-subtitle" style={{ marginTop: 0 }}>
          {descricao ?? (
            <>
              Cada número pode cobrar com um template próprio, em paralelo (WABAs diferentes) — a fila é compartilhada
              entre eles, então nenhum cliente é cobrado duas vezes. O agendamento de cada um (dias, horário, intervalo)
              fica em <Link to="/configuracoes?aba=horario">Configurações → Horário</Link>.
            </>
          )}
        </p>

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
                <label htmlFor="faixa-numero-de-envio">Número de envio</label>
                <select id="faixa-numero-de-envio" value={formNumberId} onChange={(e) => setFormNumberId(e.target.value)}>
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
                <label htmlFor="faixa-template">Template</label>
                <div style={{ display: "flex", gap: 8, alignItems: "center" }}>
                  <select id="faixa-template" value={formTemplateId} onChange={(e) => selecionarTemplateForm(e.target.value)} style={{ flex: 1, minWidth: 0 }}>
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
