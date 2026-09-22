import { FormEvent, useEffect, useState } from "react";
import { api, MetaToken } from "../../api";
import { IconAlert, IconCheckCircle } from "../../icons";

// Tokens da Meta: cadastrados só aqui, cifrados no banco (nunca no .env). Cada
// número escolhe o seu na tela Números.
export default function TokensMetaCard() {
  const [tokens, setTokens] = useState<MetaToken[]>([]);
  // Formulário de novo token
  const [tokenForm, setTokenForm] = useState({
    nome: "",
    token: "",
  });
  const [savingToken, setSavingToken] = useState(false);
  const [tokenError, setTokenError] = useState<string | null>(null);

  // Resultados dos testes de token por ID
  const [testResults, setTestResults] = useState<
    Record<string, { ok: boolean; detalhe: string; loading?: boolean }>
  >({});

  function load() {
    api.listarTokensMeta().then(setTokens).catch((e) => setTokenError(e.message));
  }

  useEffect(load, []);

  async function handleCreateToken(e: FormEvent) {
    e.preventDefault();
    setTokenError(null);
    setSavingToken(true);
    try {
      await api.criarTokenMeta({
        nome: tokenForm.nome.trim(),
        token: tokenForm.token.trim(),
      });
      setTokenForm({ nome: "", token: "" });
      load();
    } catch (err) {
      setTokenError(err instanceof Error ? err.message : "Erro ao cadastrar token");
    } finally {
      setSavingToken(false);
    }
  }

  async function handleToggleTokenAtivo(token: MetaToken) {
    setTokenError(null);
    try {
      await api.atualizarTokenMeta(token.id, { ativo: !token.ativo });
      load();
    } catch (err) {
      setTokenError(err instanceof Error ? err.message : "Erro ao alterar status do token");
    }
  }

  async function handleDeleteToken(token: MetaToken) {
    if (!window.confirm(`Deseja realmente excluir o token "${token.nome}"?`)) {
      return;
    }
    setTokenError(null);
    try {
      await api.excluirTokenMeta(token.id);
      load();
    } catch (err) {
      setTokenError(err instanceof Error ? err.message : "Erro ao excluir token");
    }
  }

  async function handleTestToken(tokenId: string) {
    setTestResults((prev) => ({
      ...prev,
      [tokenId]: { ok: false, detalhe: "Testando...", loading: true },
    }));
    try {
      const res = await api.testarTokenMeta(tokenId);
      setTestResults((prev) => ({
        ...prev,
        [tokenId]: { ok: res.ok, detalhe: res.detalhe, loading: false },
      }));
    } catch (err) {
      setTestResults((prev) => ({
        ...prev,
        [tokenId]: {
          ok: false,
          detalhe: err instanceof Error ? err.message : "Falha ao testar token",
          loading: false,
        },
      }));
    }
  }

  return (
      <div className="card">
        <div className="card-header">
          <h3>Tokens da Meta</h3>
          <div className="card-subtitle">
            Gerencie múltiplos tokens de acesso da API oficial da Meta (Cloud API / WABA)
          </div>
        </div>

        {tokenError && (
          <div className="error-box" style={{ marginBottom: 16 }}>
            <IconAlert width={16} height={16} />
            <span>{tokenError}</span>
          </div>
        )}

        <form onSubmit={handleCreateToken} style={{ marginBottom: 24 }}>
          <div className="form-row">
            <div className="field">
              <label>Nome do token</label>
              <input
                value={tokenForm.nome}
                onChange={(e) => setTokenForm({ ...tokenForm, nome: e.target.value })}
                placeholder="ex. Token Cobrança SP"
                required
              />
            </div>
            <div className="field">
              <label>Token de acesso (Meta)</label>
              <input
                type="password"
                autoComplete="off"
                value={tokenForm.token}
                onChange={(e) => setTokenForm({ ...tokenForm, token: e.target.value })}
                placeholder="EAA..."
                required
              />
            </div>
          </div>
          <button type="submit" disabled={savingToken}>
            {savingToken ? "Cadastrando..." : "Cadastrar token"}
          </button>
        </form>

        {tokens.length === 0 ? (
          <div className="empty-state">
            <div className="title">Nenhum token cadastrado</div>
            <p>Cadastre um token de sistema da Meta para utilizá-lo nos números de WhatsApp.</p>
          </div>
        ) : (
          <div className="table-wrap">
            <table>
              <thead>
                <tr>
                  <th>Nome</th>
                  <th>Final</th>
                  <th>Ativo</th>
                  <th>Números vinculados</th>
                  <th>Ações</th>
                </tr>
              </thead>
              <tbody>
                {tokens.map((t) => {
                  const testRes = testResults[t.id];
                  return (
                    <tr key={t.id}>
                      <td className="cell-strong">{t.nome}</td>
                      <td className="text-muted">…{t.ultimos4}</td>
                      <td>
                        <span className={`status-pill ${t.ativo ? "on" : "off"}`}>
                          {t.ativo ? "Sim" : "Não"}
                        </span>
                      </td>
                      <td>{t.numeros_vinculados}</td>
                      <td>
                        <div
                          style={{
                            display: "flex",
                            gap: "6px",
                            alignItems: "center",
                            flexWrap: "wrap",
                          }}
                        >
                          <button
                            type="button"
                            className="secondary small"
                            onClick={() => handleTestToken(t.id)}
                            disabled={testRes?.loading}
                          >
                            {testRes?.loading ? "Testando..." : "Testar"}
                          </button>
                          <button
                            type="button"
                            className="secondary small"
                            onClick={() => handleToggleTokenAtivo(t)}
                          >
                            {t.ativo ? "Desativar" : "Ativar"}
                          </button>
                          <button
                            type="button"
                            className="danger small"
                            onClick={() => handleDeleteToken(t)}
                          >
                            Excluir
                          </button>
                        </div>
                        {testRes && !testRes.loading && (
                          <div
                            className={testRes.ok ? "success-box" : "error-box"}
                            style={{
                              marginTop: 8,
                              padding: "6px 10px",
                              fontSize: 12,
                              display: "flex",
                              alignItems: "center",
                              gap: 6,
                            }}
                          >
                            {testRes.ok ? (
                              <IconCheckCircle width={14} height={14} />
                            ) : (
                              <IconAlert width={14} height={14} />
                            )}
                            <span>{testRes.detalhe}</span>
                          </div>
                        )}
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        )}
      </div>
  );
}
