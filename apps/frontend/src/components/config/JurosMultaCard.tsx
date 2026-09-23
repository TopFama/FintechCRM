import { useEffect, useState } from "react";
import { api } from "../../api";
import { IconAlert, IconCheckCircle } from "../../icons";

// Juros ao mês, multa e carência usados no cálculo do valor a cobrar
// (consulta da base de cobrança no SETA).
export default function JurosMultaCard() {
  const [juros, setJuros] = useState("");
  const [multa, setMulta] = useState("");
  const [carencia, setCarencia] = useState("");
  const [erro, setErro] = useState<string | null>(null);
  const [sucesso, setSucesso] = useState<string | null>(null);
  const [salvando, setSalvando] = useState(false);

  useEffect(() => {
    api
      .getConfigCobranca()
      .then((c) => {
        setJuros(String(c.parametros.juros_mes_percentual));
        setMulta(String(c.parametros.multa_percentual));
        setCarencia(String(c.parametros.dias_min_juros));
      })
      .catch((e) => setErro(e.message));
  }, []);

  async function salvar() {
    setErro(null);
    setSucesso(null);
    setSalvando(true);
    try {
      const c = await api.salvarParametrosCobranca({
        juros_mes_percentual: juros || "0",
        multa_percentual: multa || "0",
        dias_min_juros: Number(carencia) || 0,
      });
      setJuros(String(c.parametros.juros_mes_percentual));
      setMulta(String(c.parametros.multa_percentual));
      setCarencia(String(c.parametros.dias_min_juros));
      setSucesso("Juros e multa salvos");
    } catch (e) {
      setErro(e instanceof Error ? e.message : "Erro ao salvar juros e multa");
    } finally {
      setSalvando(false);
    }
  }

  return (
    <div className="card">
      <div className="card-header">
        <div>
          <h3>Juros e multa</h3>
          <div className="card-subtitle">
            Usados no cálculo do valor a cobrar de cada parcela em atraso.
          </div>
        </div>
      </div>

      {erro && (
        <div className="error-box" style={{ marginBottom: 16 }}>
          <IconAlert width={16} height={16} />
          <span>{erro}</span>
        </div>
      )}
      {sucesso && (
        <div className="success-box" style={{ marginBottom: 16 }}>
          <IconCheckCircle width={16} height={16} />
          <span>{sucesso}</span>
        </div>
      )}

      <div style={{ display: "flex", gap: 16, flexWrap: "wrap" }}>
        <div className="field" style={{ maxWidth: 180 }}>
          <label htmlFor="jm-juros">Juros ao mês (%)</label>
          <input id="jm-juros" type="number" min="0" step="0.01" value={juros} onChange={(e) => setJuros(e.target.value)} />
        </div>
        <div className="field" style={{ maxWidth: 180 }}>
          <label htmlFor="jm-multa">Multa (%)</label>
          <input id="jm-multa" type="number" min="0" max="100" step="0.01" value={multa} onChange={(e) => setMulta(e.target.value)} />
        </div>
        <div className="field" style={{ maxWidth: 220 }}>
          <label htmlFor="jm-carencia">Carência (dias de atraso)</label>
          <input id="jm-carencia" type="number" min="0" step="1" value={carencia} onChange={(e) => setCarencia(e.target.value)} />
        </div>
      </div>
      <div className="field-hint" style={{ marginTop: 8 }}>
        Juros e multa passam a contar a partir de {carencia || 0} dia(s) de atraso.
      </div>
      <div className="actions-row">
        <button type="button" onClick={salvar} disabled={salvando}>
          {salvando ? "Salvando..." : "Salvar juros e multa"}
        </button>
      </div>
    </div>
  );
}
