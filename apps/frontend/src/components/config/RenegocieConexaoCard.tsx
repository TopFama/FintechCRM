import { FormEvent, useEffect, useState } from "react";
import { api, ConexaoRenegocie } from "../../api";
import { IconAlert, IconRefresh } from "../../icons";

// Conexão com o portal TopFamaRenegocie, de onde vêm os clientes de remarketing.
export default function RenegocieConexaoCard() {
  const [conexao, setConexao] = useState<ConexaoRenegocie | null>(null);
  const [form, setForm] = useState({ base_url: "http://renegocie-api:8000", chave: "" });
  const [erro, setErro] = useState<string | null>(null);
  const [teste, setTeste] = useState<{ ok: boolean; detalhe: string } | null>(null);
  const [salvando, setSalvando] = useState(false);
  const [testando, setTestando] = useState(false);

  useEffect(() => {
    api
      .conexaoRenegocie()
      .then((c) => {
        setConexao(c);
        if (c.base_url) setForm((f) => ({ ...f, base_url: c.base_url || f.base_url }));
      })
      .catch((e) => setErro(e instanceof Error ? e.message : "Erro ao consultar a conexão"));
  }, []);

  async function salvar(e: FormEvent) {
    e.preventDefault();
    setErro(null);
    setTeste(null);
    setSalvando(true);
    try {
      const c = await api.salvarConexaoRenegocie({ base_url: form.base_url, chave: form.chave || null });
      setConexao(c);
      setForm((f) => ({ ...f, chave: "" }));
    } catch (err) {
      setErro(err instanceof Error ? err.message : "Erro ao salvar a conexão");
    } finally {
      setSalvando(false);
    }
  }

  async function testar() {
    setTeste(null);
    setTestando(true);
    try {
      setTeste(await api.testarConexaoRenegocie());
    } catch (err) {
      setTeste({ ok: false, detalhe: err instanceof Error ? err.message : "Erro ao testar" });
    } finally {
      setTestando(false);
    }
  }

  return (
    <div className="card">
      <div className="card-header">
        <h3>Renegocie</h3>
        {conexao?.configurado && (
          <span className="status-pill on" style={{ fontSize: 14 }}>
            Configurado
          </span>
        )}
      </div>
      <p className="card-subtitle">
        Portal de renegociação de onde vêm os clientes de remarketing. A chave é gerada no admin do Renegocie, aba
        Contato (só super admin).
      </p>
      {erro && (
        <div className="error-box">
          <IconAlert width={16} height={16} />
          <span>{erro}</span>
        </div>
      )}
      {teste && (
        <div className={teste.ok ? "success-box" : "error-box"}>
          {!teste.ok && <IconAlert width={16} height={16} />}
          <span>{teste.detalhe}</span>
        </div>
      )}
      <form onSubmit={salvar}>
        <div className="form-row">
          <div className="field">
            <label htmlFor="renegocie-url">Endereço do Renegocie</label>
            <input
              id="renegocie-url"
              value={form.base_url}
              onChange={(e) => setForm({ ...form, base_url: e.target.value })}
              required
            />
            <span className="field-hint">Na VPS, os dois sistemas se falam por http://renegocie-api:8000.</span>
          </div>
          <div className="field">
            <label htmlFor="renegocie-chave">Chave de integração</label>
            <input
              id="renegocie-chave"
              type="password"
              autoComplete="off"
              placeholder={conexao?.configurado ? "•••••••• (deixe em branco pra manter a atual)" : "rmk_..."}
              value={form.chave}
              onChange={(e) => setForm({ ...form, chave: e.target.value })}
              required={!conexao?.configurado}
            />
          </div>
        </div>
        <div style={{ display: "flex", gap: 10 }}>
          <button type="submit" disabled={salvando}>
            {salvando ? "Salvando..." : "Salvar"}
          </button>
          {conexao?.configurado && (
            <button type="button" className="secondary" onClick={testar} disabled={testando}>
              <IconRefresh width={16} height={16} />
              {testando ? "Testando..." : "Testar conexão"}
            </button>
          )}
        </div>
      </form>
    </div>
  );
}
