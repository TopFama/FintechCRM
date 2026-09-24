import { FormEvent, useEffect, useMemo, useState } from "react";
import { useSearchParams } from "react-router-dom";
import { api, CampoCliente, ChatwootTestResult, pareceAdmin, StatusChatwoot, StatusGoogle, StatusSeta, Template, WhatsappNumber } from "../api";
import BlacklistCard from "../components/config/BlacklistCard";
import DisparoCard from "../components/config/DisparoCard";
import Faixas from "./Faixas";
import NumerosCard from "../components/config/NumerosCard";
import OrcamentoCard from "../components/config/OrcamentoCard";
import JurosMultaCard from "../components/config/JurosMultaCard";
import RegrasCobrancaCard from "../components/config/RegrasCobrancaCard";
import TemplatesCard from "../components/config/TemplatesCard";
import TokensMetaCard from "../components/config/TokensMetaCard";
import UsuariosCard from "../components/config/UsuariosCard";
import { IconAlert, IconRefresh } from "../icons";

type Aba = "conexoes" | "templates" | "faixas" | "horario" | "indicadores" | "blacklist" | "usuarios";

const ABAS: { valor: Aba; rotulo: string }[] = [
  { valor: "templates", rotulo: "Templates" },
  { valor: "conexoes", rotulo: "Conexões" },
  { valor: "faixas", rotulo: "Faixas de cobrança" },
  { valor: "horario", rotulo: "Horário" },
  { valor: "indicadores", rotulo: "Indicadores" },
  { valor: "blacklist", rotulo: "Blacklist" },
];

const ABAS_VALIDAS: Aba[] = ["conexoes", "templates", "faixas", "horario", "indicadores", "blacklist", "usuarios"];

export default function Configuracoes() {
  const [versaoNumeros, setVersaoNumeros] = useState(0);
  const [searchParams, setSearchParams] = useSearchParams();
  const abaParam = searchParams.get("aba");
  const admin = pareceAdmin();
  const aba: Aba =
    abaParam && ABAS_VALIDAS.includes(abaParam as Aba) && (abaParam !== "usuarios" || admin)
      ? (abaParam as Aba)
      : "conexoes";
  const abas = admin ? [...ABAS, { valor: "usuarios" as Aba, rotulo: "Usuários" }] : ABAS;

  function irParaAba(novaAba: Aba) {
    const next = new URLSearchParams(searchParams);
    if (novaAba === "conexoes") {
      next.delete("aba");
    } else {
      next.set("aba", novaAba);
    }
    setSearchParams(next, { replace: true });
  }

  const [seta, setSeta] = useState<StatusSeta | null>(null);
  const [setaCarregando, setSetaCarregando] = useState(false);
  const [setaErro, setSetaErro] = useState<string | null>(null);

  const [google, setGoogle] = useState<StatusGoogle | null>(null);
  const [googleCarregando, setGoogleCarregando] = useState(false);
  const [googleErro, setGoogleErro] = useState<string | null>(null);
  const [oauthErro, setOauthErro] = useState<string | null>(null);
  const [oauthSucesso, setOauthSucesso] = useState<string | null>(null);

  const [chatwoot, setChatwoot] = useState<StatusChatwoot | null>(null);
  const [chatwootErro, setChatwootErro] = useState<string | null>(null);
  const [chatwootSalvando, setChatwootSalvando] = useState(false);
  const [chatwootTestando, setChatwootTestando] = useState(false);
  const [chatwootTeste, setChatwootTeste] = useState<{ ok: boolean; detalhe: string } | null>(null);
  const [formChatwoot, setFormChatwoot] = useState({ base_url: "", account_id: "", api_access_token: "" });

  // Testar envio de template (via Chatwoot) pra um número específico
  const [templates, setTemplates] = useState<Template[]>([]);
  const [numbers, setNumbers] = useState<WhatsappNumber[]>([]);
  const [campos, setCampos] = useState<CampoCliente[]>([]);
  const [testeTemplateId, setTesteTemplateId] = useState("");
  const [testeNumeroId, setTesteNumeroId] = useState("");
  const [testeCelular, setTesteCelular] = useState("");
  const [testeVariaveis, setTesteVariaveis] = useState<Record<string, string>>({});
  const [testeEnviando, setTesteEnviando] = useState(false);
  const [testeResultado, setTesteResultado] = useState<ChatwootTestResult | null>(null);

  const testeTemplate = useMemo(
    () => templates.find((t) => t.id === testeTemplateId) || null,
    [templates, testeTemplateId]
  );
  const numerosChatwoot = useMemo(() => numbers.filter((n) => n.chatwoot_inbox_id), [numbers]);

  // Mensagem do callback OAuth (google=ok ou google=erro&motivo=...)
  useEffect(() => {
    const status = searchParams.get("google");
    const motivo = searchParams.get("motivo");
    if (status === "ok") {
      setOauthSucesso("Conta Google conectada");
    } else if (status === "erro") {
      setOauthErro(motivo || "Erro ao conectar conta Google.");
    }
    // Limpa os parâmetros da URL sem recarregar
    if (status) {
      const next = new URLSearchParams(searchParams);
      next.delete("google");
      next.delete("motivo");
      setSearchParams(next, { replace: true });
    }
  }, []);

  function carregarSeta() {
    setSetaErro(null);
    setSetaCarregando(true);
    api
      .statusSeta()
      .then(setSeta)
      .catch((e) => setSetaErro(e instanceof Error ? e.message : "Erro ao consultar ERP"))
      .finally(() => setSetaCarregando(false));
  }

  function carregarGoogle() {
    setGoogleErro(null);
    setGoogleCarregando(true);
    api
      .statusGoogle()
      .then(setGoogle)
      .catch((e) => setGoogleErro(e instanceof Error ? e.message : "Erro ao consultar Google"))
      .finally(() => setGoogleCarregando(false));
  }

  function carregarChatwoot() {
    setChatwootErro(null);
    api
      .statusChatwoot()
      .then((s) => {
        setChatwoot(s);
        if (s.configurado) {
          setFormChatwoot({ base_url: s.base_url || "", account_id: s.account_id || "", api_access_token: "" });
        }
      })
      .catch((e) => setChatwootErro(e instanceof Error ? e.message : "Erro ao consultar Chatwoot"));
  }

  useEffect(() => {
    carregarSeta();
    carregarGoogle();
    carregarChatwoot();
    api.listTemplates().then(setTemplates).catch(() => undefined);
    api.listCamposCliente().then(setCampos).catch(() => undefined);
  }, []);

  // Números mudam nos cards de token e de números: o teste de envio acompanha
  useEffect(() => {
    api.listNumbers().then(setNumbers).catch(() => undefined);
  }, [versaoNumeros]);

  function selecionarTemplateTeste(templateId: string) {
    setTesteTemplateId(templateId);
    setTesteResultado(null);
    const template = templates.find((t) => t.id === templateId);
    const variaveis: Record<string, string> = {};
    for (const v of template?.variables || []) {
      const campo = v.campo_sugerido ? campos.find((c) => c.campo === v.campo_sugerido) : undefined;
      variaveis[v.internal_name] = campo ? campo.exemplo : "";
    }
    setTesteVariaveis(variaveis);
  }

  function renderizarPreviewTeste(t: Template): string {
    return t.body_text.replace(/\{\{(\d+)\}\}/g, (match, pos) => {
      const variavel = t.variables.find((v) => v.position === Number(pos));
      const valor = variavel ? testeVariaveis[variavel.internal_name] : undefined;
      return valor || match;
    });
  }

  async function handleTestarEnvio() {
    if (!testeTemplate) return;
    setTesteEnviando(true);
    setTesteResultado(null);
    try {
      const resultado = await api.testarEnvioChatwoot(testeTemplate.id, {
        whatsapp_number_id: testeNumeroId,
        celular: testeCelular,
        variables: testeVariaveis,
      });
      setTesteResultado(resultado);
    } catch (err) {
      setTesteResultado({ ok: false, detalhe: err instanceof Error ? err.message : "Erro ao testar envio" });
    } finally {
      setTesteEnviando(false);
    }
  }

  async function salvarChatwoot(e: FormEvent) {
    e.preventDefault();
    setChatwootErro(null);
    setChatwootTeste(null);
    setChatwootSalvando(true);
    try {
      const s = await api.salvarConfigChatwoot(formChatwoot);
      setChatwoot(s);
      setFormChatwoot((f) => ({ ...f, api_access_token: "" }));
    } catch (err) {
      setChatwootErro(err instanceof Error ? err.message : "Erro ao salvar configuração do Chatwoot");
    } finally {
      setChatwootSalvando(false);
    }
  }

  async function testarChatwoot() {
    setChatwootTeste(null);
    setChatwootTestando(true);
    try {
      setChatwootTeste(await api.testarChatwoot());
    } catch (err) {
      setChatwootTeste({ ok: false, detalhe: err instanceof Error ? err.message : "Erro ao testar" });
    } finally {
      setChatwootTestando(false);
    }
  }

  async function conectarGoogle() {
    setOauthErro(null);
    setOauthSucesso(null);
    setGoogleErro(null);
    try {
      const { url } = await api.iniciarOAuthGoogle();
      window.location.href = url;
    } catch (e) {
      setGoogleErro(e instanceof Error ? e.message : "Erro ao iniciar OAuth");
    }
  }

  async function desconectarGoogle() {
    if (!window.confirm("Desconectar a conta Google?")) return;
    setOauthErro(null);
    setOauthSucesso(null);
    setGoogleErro(null);
    try {
      await api.desconectarGoogle();
      carregarGoogle();
    } catch (e) {
      setGoogleErro(e instanceof Error ? e.message : "Erro ao desconectar");
    }
  }

  return (
    <div>
      <div className="page-header">
        <div>
          <h2>Configurações</h2>
          <div className="subtitle">
            Templates, conexões, horário de disparo, indicadores (clusters, faixas de atraso e regra do WhatsApp) e
            blacklist do sistema
          </div>
        </div>
      </div>

      <div className="tabs" style={{ display: "flex", gap: 8, marginBottom: 16 }}>
        {abas.map((a) => (
          <button
            key={a.valor}
            type="button"
            className={aba === a.valor ? "small" : "secondary small"}
            onClick={() => irParaAba(a.valor)}
          >
            {a.rotulo}
          </button>
        ))}
      </div>

      {aba === "templates" && <TemplatesCard />}
      {aba === "faixas" && <Faixas />}
      {aba === "horario" && <DisparoCard />}
      {aba === "indicadores" && (
        <>
          <RegrasCobrancaCard />
          <div style={{ marginTop: 16 }}>
            <JurosMultaCard />
          </div>
          <div style={{ marginTop: 16 }}>
            <OrcamentoCard />
          </div>
        </>
      )}
      {aba === "blacklist" && <BlacklistCard />}
      {aba === "usuarios" && admin && <UsuariosCard />}

      {aba === "conexoes" && (
        <>
      {/* SETA */}
      <div className="card">
        <div className="card-header">
          <h3>SETA</h3>
          <button
            type="button"
            className="secondary"
            onClick={carregarSeta}
            disabled={setaCarregando}
          >
            <IconRefresh width={16} height={16} />
            {setaCarregando ? "Testando..." : "Testar conexão"}
          </button>
        </div>

        {setaErro && (
          <div className="error-box">
            <IconAlert width={16} height={16} />
            <span>{setaErro}</span>
          </div>
        )}

        {setaCarregando && <div className="loading-state">Consultando ERP...</div>}

        {seta && !setaCarregando && (
          <div>
            <div style={{ marginBottom: 12 }}>
              <span
                className={`status-pill ${seta.conectado ? "on" : "off"}`}
                style={{ fontSize: 14 }}
              >
                {seta.conectado ? "Conectado" : "Desconectado"}
              </span>
            </div>

            {seta.conectado ? (
              <div className="form-row" style={{ flexWrap: "wrap", gap: "8px 24px" }}>
                {seta.banco && (
                  <div>
                    <span className="text-muted" style={{ fontSize: 12 }}>
                      Banco
                    </span>
                    <div className="cell-strong">{seta.banco}</div>
                  </div>
                )}
                {seta.usuario && (
                  <div>
                    <span className="text-muted" style={{ fontSize: 12 }}>
                      Usuário
                    </span>
                    <div className="cell-strong">{seta.usuario}</div>
                  </div>
                )}
                {seta.versao && (
                  <div>
                    <span className="text-muted" style={{ fontSize: 12 }}>
                      Versão
                    </span>
                    <div className="cell-strong">{seta.versao}</div>
                  </div>
                )}
                {seta.latencia_ms !== null && (
                  <div>
                    <span className="text-muted" style={{ fontSize: 12 }}>
                      Latência
                    </span>
                    <div className="cell-strong">{seta.latencia_ms} ms</div>
                  </div>
                )}
                <div>
                  <span className="text-muted" style={{ fontSize: 12 }}>
                    Acesso
                  </span>
                  <div>
                    {seta.somente_leitura ? (
                      <span className="badge approved">Somente leitura ✓</span>
                    ) : (
                      <span className="badge rejected">
                        Atenção: acesso com escrita habilitado
                      </span>
                    )}
                  </div>
                </div>
              </div>
            ) : (
              seta.erro && (
                <div className="error-box" style={{ marginTop: 8 }}>
                  <IconAlert width={16} height={16} />
                  <span>{seta.erro}</span>
                </div>
              )
            )}
          </div>
        )}
      </div>

      {/* Google */}
      <div className="card">
        <div className="card-header">
          <h3>Google (planilha de lojas)</h3>
        </div>

        {oauthErro && (
          <div className="error-box">
            <IconAlert width={16} height={16} />
            <span>{oauthErro}</span>
          </div>
        )}
        {googleErro && (
          <div className="error-box">
            <IconAlert width={16} height={16} />
            <span>{googleErro}</span>
          </div>
        )}
        {oauthSucesso && <div className="success-box">{oauthSucesso}</div>}

        {googleCarregando && <div className="loading-state">Verificando...</div>}

        {google && !googleCarregando && (
          <div>
            {!google.configurado ? (
              <div>
                <p>
                  A integração com o Google não está configurada. Defina as variáveis{" "}
                  <code>GOOGLE_CLIENT_ID</code> e <code>GOOGLE_CLIENT_SECRET</code> no{" "}
                  <code>.env</code> do servidor.
                </p>
                <p>
                  <strong>URI de redirecionamento</strong> para cadastrar no Google Cloud Console:
                </p>
                <code
                  style={{
                    display: "block",
                    background: "var(--color-neutral-bg)",
                    padding: "10px 14px",
                    borderRadius: "var(--radius-sm)",
                    wordBreak: "break-all",
                    fontSize: 13,
                  }}
                >
                  {google.redirect_uri}
                </code>
              </div>
            ) : google.conectado ? (
              <div>
                <div style={{ marginBottom: 12 }}>
                  <span className="status-pill on" style={{ fontSize: 14 }}>
                    Conectado
                  </span>
                  {google.email && (
                    <span style={{ marginLeft: 12, fontSize: 13.5 }}>{google.email}</span>
                  )}
                </div>
                <button type="button" className="danger" onClick={desconectarGoogle}>
                  Desconectar
                </button>
              </div>
            ) : (
              <div>
                <div style={{ marginBottom: 12 }}>
                  <span className="status-pill off" style={{ fontSize: 14 }}>
                    Não conectado
                  </span>
                </div>
                <button type="button" onClick={conectarGoogle}>
                  Conectar conta Google
                </button>
              </div>
            )}
          </div>
        )}
      </div>

      {/* Chatwoot */}
      <div className="card">
        <div className="card-header">
          <h3>Chatwoot</h3>
          {chatwoot?.configurado && (
            <span className="status-pill on" style={{ fontSize: 14 }}>
              Configurado
            </span>
          )}
        </div>
        <p className="card-subtitle">
          Credenciais da conta do Chatwoot usada para enviar cobrança pelos números com inbox vinculada
          (card Números de WhatsApp, abaixo).
        </p>

        {chatwootErro && (
          <div className="error-box">
            <IconAlert width={16} height={16} />
            <span>{chatwootErro}</span>
          </div>
        )}
        {chatwootTeste && (
          <div className={chatwootTeste.ok ? "success-box" : "error-box"}>
            {!chatwootTeste.ok && <IconAlert width={16} height={16} />}
            <span>{chatwootTeste.detalhe}</span>
          </div>
        )}

        <form onSubmit={salvarChatwoot}>
          <div className="form-row">
            <div className="field">
              <label htmlFor="config-url-base">URL base</label>
              <input id="config-url-base"
                placeholder="https://chat.suaempresa.com.br"
                value={formChatwoot.base_url}
                onChange={(e) => setFormChatwoot({ ...formChatwoot, base_url: e.target.value })}
                required
              />
            </div>
            <div className="field">
              <label htmlFor="config-id-da-conta">ID da conta</label>
              <input id="config-id-da-conta"
                value={formChatwoot.account_id}
                onChange={(e) => setFormChatwoot({ ...formChatwoot, account_id: e.target.value })}
                required
              />
            </div>
          </div>
          <div className="field">
            <label htmlFor="config-token-de-acesso">Token de acesso da API</label>
            <input id="config-token-de-acesso"
              type="password"
              placeholder={chatwoot?.configurado ? "•••••••• (deixe em branco pra manter o atual)" : ""}
              value={formChatwoot.api_access_token}
              onChange={(e) => setFormChatwoot({ ...formChatwoot, api_access_token: e.target.value })}
              required={!chatwoot?.configurado}
            />
          </div>
          <div style={{ display: "flex", gap: 10 }}>
            <button type="submit" disabled={chatwootSalvando}>
              {chatwootSalvando ? "Salvando..." : "Salvar"}
            </button>
            {chatwoot?.configurado && (
              <button type="button" className="secondary" onClick={testarChatwoot} disabled={chatwootTestando}>
                <IconRefresh width={16} height={16} />
                {chatwootTestando ? "Testando..." : "Testar conexão"}
              </button>
            )}
          </div>
        </form>

        {chatwoot?.configurado && (
          <div className="chatwoot-teste-envio">
            <h4>Testar envio de template</h4>
            <p className="card-subtitle">
              Dispara agora um template pra um celular específico, pra validar o envio antes de ligar o
              número numa faixa de cobrança.
            </p>
            {numerosChatwoot.length === 0 ? (
              <p className="field-hint">
                Nenhum número tem inbox do Chatwoot vinculada ainda (campo "Inbox do Chatwoot" no card Números,
                abaixo).
              </p>
            ) : (
              <>
                <div className="form-row">
                  <div className="field">
                    <label htmlFor="config-template">Template</label>
                    <select id="config-template" value={testeTemplateId} onChange={(e) => selecionarTemplateTeste(e.target.value)}>
                      <option value="">Selecione...</option>
                      {templates.map((t) => (
                        <option key={t.id} value={t.id}>
                          {t.name}
                        </option>
                      ))}
                    </select>
                  </div>
                  <div className="field">
                    <label htmlFor="config-numero-de-origem">Número de origem</label>
                    <select id="config-numero-de-origem" value={testeNumeroId} onChange={(e) => setTesteNumeroId(e.target.value)}>
                      <option value="">Selecione...</option>
                      {numerosChatwoot.map((n) => (
                        <option key={n.id} value={n.id}>
                          {n.label} ({n.display_phone_number})
                        </option>
                      ))}
                    </select>
                  </div>
                  <div className="field">
                    <label htmlFor="config-celular-de-destino">Celular de destino</label>
                    <input id="config-celular-de-destino"
                      value={testeCelular}
                      onChange={(e) => setTesteCelular(e.target.value)}
                      placeholder="55DDDNÚMERO"
                    />
                  </div>
                </div>

                {testeTemplate && (
                  <div className="template-preview">
                    <div className="template-preview-bubble">{renderizarPreviewTeste(testeTemplate)}</div>
                    {testeTemplate.variables.length > 0 && (
                      <div className="template-preview-vars">
                        {testeTemplate.variables.map((v) => (
                          <div className="field" key={v.id}>
                            <label htmlFor={`config-var-${v.id}`}>{`{{${v.position}}}`} ({v.internal_name})</label>
                            <input id={`config-var-${v.id}`}
                              value={testeVariaveis[v.internal_name] || ""}
                              onChange={(e) =>
                                setTesteVariaveis((atual) => ({ ...atual, [v.internal_name]: e.target.value }))
                              }
                            />
                          </div>
                        ))}
                      </div>
                    )}
                  </div>
                )}

                <button
                  type="button"
                  className="secondary small"
                  disabled={testeEnviando || !testeTemplate || !testeNumeroId || !testeCelular}
                  onClick={handleTestarEnvio}
                >
                  {testeEnviando ? "Enviando..." : "Enviar teste"}
                </button>
                {testeResultado && (
                  <p className={testeResultado.ok ? "field-success" : "field-error"}>{testeResultado.detalhe}</p>
                )}
              </>
            )}
          </div>
        )}
      </div>

      <TokensMetaCard onNumerosAlterados={() => setVersaoNumeros((v) => v + 1)} />
      <NumerosCard versao={versaoNumeros} onSalvo={() => setVersaoNumeros((v) => v + 1)} />
        </>
      )}
    </div>
  );
}
