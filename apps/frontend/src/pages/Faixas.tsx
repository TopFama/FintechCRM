import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { api, Faixa } from "../api";
import { IconAlert, IconArrowRight, IconLayers, IconPlus, IconRefresh, IconTrash } from "../icons";

export default function Faixas() {
  const [faixas, setFaixas] = useState<Faixa[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [excluindo, setExcluindo] = useState<string | null>(null);
  const [sincronizando, setSincronizando] = useState(false);
  const [sincronizacao, setSincronizacao] = useState<string | null>(null);

  function carregar() {
    return api
      .listFaixas()
      .then(setFaixas)
      .catch((e) => setError(e.message))
      .finally(() => setLoading(false));
  }

  useEffect(() => {
    carregar();
  }, []);

  async function handleSincronizar() {
    setError(null);
    setSincronizacao(null);
    setSincronizando(true);
    try {
      const resultado = await api.sincronizarFaixasAtraso();
      await carregar();
      setSincronizacao(
        resultado.criadas.length > 0
          ? `${resultado.criadas.length} faixa(s) criada(s): ${resultado.criadas.join(", ")}. Falta atribuir template e números em cada uma.`
          : "Todas as faixas de atraso já têm uma faixa de cobrança correspondente."
      );
    } catch (err) {
      setError(err instanceof Error ? err.message : "Erro ao sincronizar faixas de atraso");
    } finally {
      setSincronizando(false);
    }
  }

  async function handleExcluir(f: Faixa) {
    if (!window.confirm(`Excluir a faixa "${f.name}"? O histórico de envios já feitos é mantido.`)) {
      return;
    }
    setError(null);
    setExcluindo(f.id);
    try {
      await api.excluirFaixa(f.id);
      setFaixas((atual) => atual.filter((x) => x.id !== f.id));
    } catch (err) {
      setError(err instanceof Error ? err.message : "Erro ao excluir faixa");
    } finally {
      setExcluindo(null);
    }
  }

  return (
    <div>
      <div className="page-header">
        <div>
          <h2>Faixas de cobrança</h2>
          <div className="subtitle">Cada faixa liga um nome de cobrança a um template e a um ou mais números</div>
        </div>
        <div style={{ display: "flex", gap: 10 }}>
          <button type="button" className="secondary" onClick={handleSincronizar} disabled={sincronizando}>
            <IconRefresh width={16} height={16} />
            {sincronizando ? "Sincronizando..." : "Sincronizar com faixas de atraso"}
          </button>
          <Link to="/faixas/nova">
            <button>
              <IconPlus width={16} height={16} /> Nova faixa
            </button>
          </Link>
        </div>
      </div>

      {error && (
        <div className="error-box">
          <IconAlert width={16} height={16} />
          <span>{error}</span>
        </div>
      )}
      {sincronizacao && <div className="success-box">{sincronizacao}</div>}

      <div className="card">
        {loading ? (
          <div className="loading-state">Carregando faixas...</div>
        ) : faixas.length === 0 ? (
          <div className="empty-state">
            <IconLayers width={28} height={28} />
            <div className="title">Nenhuma faixa cadastrada</div>
            <p>Crie a primeira faixa para começar a cobrar via WhatsApp.</p>
            <Link to="/faixas/nova">
              <button style={{ marginTop: 12 }}>
                <IconPlus width={16} height={16} /> Nova faixa
              </button>
            </Link>
          </div>
        ) : (
          <div className="faixa-list">
            {faixas.map((f) => (
              <div className="faixa-row" key={f.id}>
                <Link to={`/faixas/${f.id}`} style={{ display: "flex", alignItems: "center", flex: 1, minWidth: 0, gap: 16, textDecoration: "none", color: "inherit" }}>
                  <div className="faixa-row-main">
                    <div className="faixa-icon">
                      <IconLayers />
                    </div>
                    <div style={{ minWidth: 0 }}>
                      <div className="faixa-row-title">{f.name}</div>
                      <div className="faixa-row-sub">Template: {f.template?.name || "—"}</div>
                    </div>
                  </div>
                  <div style={{ display: "flex", alignItems: "center", gap: 14, flexShrink: 0, marginLeft: "auto" }}>
                    {!f.template_id && <span className="badge rejected">Configurar template</span>}
                    <span className={`status-pill ${f.dispatch_config?.active ? "on" : "off"}`}>
                      {f.dispatch_config?.active ? "Agendado" : "Pausado"}
                    </span>
                    <IconArrowRight className="text-faint" />
                  </div>
                </Link>
                <button
                  type="button"
                  className="danger small"
                  style={{ flexShrink: 0 }}
                  disabled={excluindo === f.id}
                  onClick={() => handleExcluir(f)}
                  title="Excluir faixa"
                >
                  <IconTrash width={15} height={15} />
                </button>
              </div>
            ))}
          </div>
        )}
      </div>
    </div>
  );
}
