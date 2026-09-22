import { FormEvent, useEffect, useState } from "react";
import { api, MetaToken, NumeroMeta } from "../../api";
import { IconAlert, IconCheckCircle } from "../../icons";

type Resultado = { ok: boolean; detalhe: string };

// Tokens da Meta: cadastrados só aqui (WABA ID + token), cifrados no banco —
// nunca no .env. Da WABA de cada token se puxam os números (card Números de WhatsApp).
export default function TokensMetaCard({ onNumerosAlterados }: { onNumerosAlterados?: () => void }) {
  const [tokens, setTokens] = useState<MetaToken[]>([]);
  const [form, setForm] = useState({ nome: "", waba_id: "", token: "" });
  const [salvando, setSalvando] = useState(false);
  const [erro, setErro] = useState<string | null>(null);
  const [testes, setTestes] = useState<Record<string, Resultado & { carregando?: boolean }>>({});

  // Painel "Números da Meta" (um token aberto por vez)
  const [abertoId, setAbertoId] = useState<string | null>(null);
  const [numeros, setNumeros] = useState<NumeroMeta[]>([]);
  const [selecionados, setSelecionados] = useState<Set<string>>(new Set());
  const [carregandoNumeros, setCarregandoNumeros] = useState(false);
  const [importando, setImportando] = useState(false);
  const [resultadoNumeros, setResultadoNumeros] = useState<Resultado | null>(null);

  function carregarTokens() {
    api.listarTokensMeta().then(setTokens).catch((e) => setErro(e.message));
  }

  useEffect(carregarTokens, []);

  async function abrirNumeros(tokenId: string) {
    setAbertoId(tokenId);
    setNumeros([]);
    setSelecionados(new Set());
    setResultadoNumeros(null);
    setCarregandoNumeros(true);
    try {
      const lista = await api.listarNumerosMeta(tokenId);
      setNumeros(lista);
      // pré-marca os que ainda não estão cadastrados
      setSelecionados(new Set(lista.filter((n) => !n.cadastrado).map((n) => n.phone_number_id)));
    } catch (e) {
      setResultadoNumeros({ ok: false, detalhe: e instanceof Error ? e.message : "Erro ao consultar a Meta" });
    } finally {
      setCarregandoNumeros(false);
    }
  }

  async function cadastrar(e: FormEvent) {
    e.preventDefault();
    setErro(null);
    setSalvando(true);
    try {
      const novo = await api.criarTokenMeta({
        nome: form.nome.trim(),
        waba_id: form.waba_id.trim(),
        token: form.token.trim(),
      });
      setForm({ nome: "", waba_id: "", token: "" });
      carregarTokens();
      abrirNumeros(novo.id);
    } catch (err) {
      setErro(err instanceof Error ? err.message : "Erro ao cadastrar token");
    } finally {
      setSalvando(false);
    }
  }

  async function importar() {
    if (!abertoId || selecionados.size === 0) return;
    setImportando(true);
    setResultadoNumeros(null);
    try {
      const r = await api.importarNumerosMeta(abertoId, [...selecionados]);
      const partes = [`${r.importados} número(s) importado(s)`];
      if (r.vinculados) partes.push(`${r.vinculados} já cadastrado(s) agora ligado(s) a este token`);
      if (r.ignorados) partes.push(`${r.ignorados} já usa(m) outro token e ficou(aram) como estava(m)`);
      carregarTokens();
      onNumerosAlterados?.();
      await abrirNumeros(abertoId);
      setResultadoNumeros({ ok: true, detalhe: partes.join("; ") + "." });
    } catch (err) {
      setResultadoNumeros({ ok: false, detalhe: err instanceof Error ? err.message : "Erro ao importar" });
    } finally {
      setImportando(false);
    }
  }

  async function informarWaba(token: MetaToken) {
    const waba = window.prompt(`WABA ID do token "${token.nome}":`, token.waba_id ?? "");
    if (waba === null) return;
    setErro(null);
    try {
      await api.atualizarTokenMeta(token.id, { waba_id: waba.trim() });
      carregarTokens();
    } catch (err) {
      setErro(err instanceof Error ? err.message : "Erro ao salvar a WABA");
    }
  }

  async function alternarAtivo(token: MetaToken) {
    setErro(null);
    try {
      await api.atualizarTokenMeta(token.id, { ativo: !token.ativo });
      carregarTokens();
    } catch (err) {
      setErro(err instanceof Error ? err.message : "Erro ao alterar status do token");
    }
  }

  async function excluir(token: MetaToken) {
    if (!window.confirm(`Deseja realmente excluir o token "${token.nome}"?`)) return;
    setErro(null);
    try {
      await api.excluirTokenMeta(token.id);
      if (abertoId === token.id) setAbertoId(null);
      carregarTokens();
    } catch (err) {
      setErro(err instanceof Error ? err.message : "Erro ao excluir token");
    }
  }

  async function testar(tokenId: string) {
    setTestes((t) => ({ ...t, [tokenId]: { ok: false, detalhe: "Testando...", carregando: true } }));
    try {
      const r = await api.testarTokenMeta(tokenId);
      setTestes((t) => ({ ...t, [tokenId]: r }));
    } catch (err) {
      const detalhe = err instanceof Error ? err.message : "Falha ao testar token";
      setTestes((t) => ({ ...t, [tokenId]: { ok: false, detalhe } }));
    }
  }

  function alternarSelecao(id: string) {
    setSelecionados((atual) => {
      const novo = new Set(atual);
      if (novo.has(id)) novo.delete(id);
      else novo.add(id);
      return novo;
    });
  }

  const tokenAberto = tokens.find((t) => t.id === abertoId);

  return (
    <div className="card">
      <div className="card-header">
        <div>
          <h3>Tokens da Meta</h3>
          <div className="card-subtitle">
            Cadastre o token de um usuário do sistema da Meta com a WABA que ele acessa; os números dessa WABA podem ser
            importados para o card Números de WhatsApp, logo abaixo.
          </div>
        </div>
      </div>

      {erro && (
        <div className="error-box" style={{ marginBottom: 16 }}>
          <IconAlert width={16} height={16} />
          <span>{erro}</span>
        </div>
      )}

      <form onSubmit={cadastrar} style={{ marginBottom: 24 }}>
        <div className="form-row">
          <div className="field">
            <label htmlFor="tok-nome">Nome do token</label>
            <input
              id="tok-nome"
              value={form.nome}
              onChange={(e) => setForm({ ...form, nome: e.target.value })}
              placeholder="ex. Token Cobrança"
              required
            />
          </div>
          <div className="field">
            <label htmlFor="tok-waba">WABA ID</label>
            <input
              id="tok-waba"
              inputMode="numeric"
              value={form.waba_id}
              onChange={(e) => setForm({ ...form, waba_id: e.target.value.replace(/\D/g, "") })}
              placeholder="ID da conta do WhatsApp Business"
              required
            />
          </div>
          <div className="field">
            <label htmlFor="tok-valor">Token de acesso</label>
            <input
              id="tok-valor"
              type="password"
              autoComplete="off"
              value={form.token}
              onChange={(e) => setForm({ ...form, token: e.target.value })}
              placeholder="EAA..."
              required
            />
          </div>
        </div>
        <div className="field-hint" style={{ marginBottom: 8 }}>
          Ao salvar, o sistema confere na Meta se o token acessa essa WABA e já lista os números dela para importar. O
          token fica cifrado e não é mostrado de novo.
        </div>
        <button type="submit" disabled={salvando}>
          {salvando ? "Conferindo na Meta..." : "Cadastrar token"}
        </button>
      </form>

      {tokens.length === 0 ? (
        <div className="empty-state">
          <div className="title">Nenhum token cadastrado</div>
          <p>Cadastre um token de usuário do sistema da Meta para enviar pelos seus números de WhatsApp.</p>
        </div>
      ) : (
        <div className="table-wrap">
          <table>
            <thead>
              <tr>
                <th scope="col">Nome</th>
                <th scope="col">WABA</th>
                <th scope="col">Final</th>
                <th scope="col">Ativo</th>
                <th scope="col">Números vinculados</th>
                <th scope="col">Ações</th>
              </tr>
            </thead>
            <tbody>
              {tokens.map((t) => {
                const teste = testes[t.id];
                return (
                  <tr key={t.id}>
                    <td className="cell-strong">{t.nome}</td>
                    <td className="text-muted">
                      {t.waba_id ?? (
                        <button type="button" className="secondary small" onClick={() => informarWaba(t)}>
                          Informar WABA
                        </button>
                      )}
                    </td>
                    <td className="text-muted">…{t.ultimos4}</td>
                    <td>
                      <span className={`status-pill ${t.ativo ? "on" : "off"}`}>{t.ativo ? "Sim" : "Não"}</span>
                    </td>
                    <td>{t.numeros_vinculados}</td>
                    <td>
                      <div style={{ display: "flex", gap: 6, alignItems: "center", flexWrap: "wrap" }}>
                        <button
                          type="button"
                          className="small"
                          onClick={() => abrirNumeros(t.id)}
                          disabled={!t.waba_id || (carregandoNumeros && abertoId === t.id)}
                          title={t.waba_id ? undefined : "Informe a WABA do token primeiro"}
                        >
                          Números da Meta
                        </button>
                        <button
                          type="button"
                          className="secondary small"
                          onClick={() => testar(t.id)}
                          disabled={teste?.carregando}
                        >
                          {teste?.carregando ? "Testando..." : "Testar"}
                        </button>
                        <button type="button" className="secondary small" onClick={() => alternarAtivo(t)}>
                          {t.ativo ? "Desativar" : "Ativar"}
                        </button>
                        <button type="button" className="danger small" onClick={() => excluir(t)}>
                          Excluir
                        </button>
                      </div>
                      {teste && !teste.carregando && (
                        <div
                          className={teste.ok ? "success-box" : "error-box"}
                          style={{ marginTop: 8, padding: "6px 10px", fontSize: 12, display: "flex", gap: 6 }}
                        >
                          {teste.ok ? <IconCheckCircle width={14} height={14} /> : <IconAlert width={14} height={14} />}
                          <span>{teste.detalhe}</span>
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

      {tokenAberto && (
        <div style={{ marginTop: 20 }}>
          <div className="card-header" style={{ padding: 0, marginBottom: 8 }}>
            <h3 style={{ fontSize: 15 }}>
              Números da WABA {tokenAberto.waba_id} — {tokenAberto.nome}
            </h3>
            <button type="button" className="secondary small" onClick={() => setAbertoId(null)}>
              Fechar
            </button>
          </div>

          {resultadoNumeros && (
            <div className={resultadoNumeros.ok ? "success-box" : "error-box"} style={{ marginBottom: 12 }}>
              {resultadoNumeros.ok ? <IconCheckCircle width={16} height={16} /> : <IconAlert width={16} height={16} />}
              <span>{resultadoNumeros.detalhe}</span>
            </div>
          )}
          {carregandoNumeros && <div className="loading-state">Consultando os números na Meta...</div>}

          {!carregandoNumeros && numeros.length === 0 && !resultadoNumeros && (
            <div className="empty-state">
              <p>A Meta não devolveu nenhum número para essa WABA.</p>
            </div>
          )}

          {!carregandoNumeros && numeros.length > 0 && (
            <>
              <div className="table-wrap">
                <table>
                  <thead>
                    <tr>
                      <th scope="col" aria-label="Selecionar" />
                      <th scope="col">Número</th>
                      <th scope="col">Nome verificado</th>
                      <th scope="col">Phone Number ID</th>
                      <th scope="col">Qualidade</th>
                      <th scope="col">Situação no portal</th>
                    </tr>
                  </thead>
                  <tbody>
                    {numeros.map((n) => (
                      <tr key={n.phone_number_id}>
                        <td>
                          <input
                            type="checkbox"
                            aria-label={`Importar ${n.display_phone_number}`}
                            checked={selecionados.has(n.phone_number_id)}
                            disabled={n.vinculado_a_este_token}
                            onChange={() => alternarSelecao(n.phone_number_id)}
                          />
                        </td>
                        <td className="cell-strong">{n.display_phone_number}</td>
                        <td>{n.verified_name ?? "—"}</td>
                        <td className="text-muted">{n.phone_number_id}</td>
                        <td>{n.quality_rating ?? "—"}</td>
                        <td>
                          {n.vinculado_a_este_token ? (
                            <span className="badge approved">Cadastrado com este token</span>
                          ) : n.cadastrado ? (
                            <span className="badge pending">Cadastrado com outro token</span>
                          ) : (
                            <span className="text-muted">Não cadastrado</span>
                          )}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
              <div className="actions-row" style={{ marginTop: 12 }}>
                <button type="button" onClick={importar} disabled={importando || selecionados.size === 0}>
                  {importando ? "Importando..." : `Importar selecionados (${selecionados.size})`}
                </button>
              </div>
            </>
          )}
        </div>
      )}
    </div>
  );
}
