import { useEffect, useState } from "react";
import { useSearchParams } from "react-router-dom";
import { api, StatusGoogle, StatusSeta } from "../api";
import { IconAlert, IconRefresh } from "../icons";

export default function Configuracoes() {
  const [searchParams, setSearchParams] = useSearchParams();

  const [seta, setSeta] = useState<StatusSeta | null>(null);
  const [setaCarregando, setSetaCarregando] = useState(false);
  const [setaErro, setSetaErro] = useState<string | null>(null);

  const [google, setGoogle] = useState<StatusGoogle | null>(null);
  const [googleCarregando, setGoogleCarregando] = useState(false);
  const [googleErro, setGoogleErro] = useState<string | null>(null);
  const [oauthErro, setOauthErro] = useState<string | null>(null);
  const [oauthSucesso, setOauthSucesso] = useState<string | null>(null);

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

  useEffect(() => {
    carregarSeta();
    carregarGoogle();
  }, []);

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
          <div className="subtitle">Status das integrações do sistema</div>
        </div>
      </div>

      {/* ERP SETA */}
      <div className="card">
        <div className="card-header">
          <h3>ERP SETA</h3>
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
    </div>
  );
}
