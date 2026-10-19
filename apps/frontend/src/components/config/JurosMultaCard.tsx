import { useEffect, useState } from "react";
import { api } from "../../api";
import { IconAlert, IconCheckCircle } from "../../icons";

// Juros ao mês, multa e carência usados no cálculo do valor a cobrar
// (consulta da base de cobrança no SETA).
export default function JurosMultaCard() {
  const [juros, setJuros] = useState("");
  const [multa, setMulta] = useState("");
  const [carencia, setCarencia] = useState("");
  const [carenciaMulta, setCarenciaMulta] = useState("");
  const [mesma, setMesma] = useState(true);
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
        setCarenciaMulta(String(c.parametros.dias_min_multa));
        setMesma(c.parametros.mesma_carencia_multa_juros);
      })
      .catch((e) => setErro(e.message));
  }, []);

  async function salvar() {
    setErro(null);
    setSucesso(null);
    const vazio = [
      [juros, "Juros ao mês"],
      [multa, "Multa"],
      [carencia, mesma ? "Carência" : "Carência dos juros"],
      ...(mesma ? [] : [[carenciaMulta, "Carência da multa"]]),
    ].find(([valor]) => valor.trim() === "");
    if (vazio) {
      setErro(`Preencha o campo "${vazio[1]}" (use 0 para não aplicar).`);
      return;
    }
    setSalvando(true);
    try {
      const c = await api.salvarParametrosCobranca({
        juros_mes_percentual: juros,
        multa_percentual: multa,
        dias_min_juros: Number(carencia),
        mesma_carencia_multa_juros: mesma,
        ...(mesma ? {} : { dias_min_multa: Number(carenciaMulta) }),
      });
      setJuros(String(c.parametros.juros_mes_percentual));
      setMulta(String(c.parametros.multa_percentual));
      setCarencia(String(c.parametros.dias_min_juros));
      setCarenciaMulta(String(c.parametros.dias_min_multa));
      setMesma(c.parametros.mesma_carencia_multa_juros);
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
        {!mesma && (
          <div className="field" style={{ maxWidth: 220 }}>
            <label htmlFor="jm-carencia-multa">Carência da multa (dias)</label>
            <input id="jm-carencia-multa" type="number" min="0" step="1" value={carenciaMulta} onChange={(e) => setCarenciaMulta(e.target.value)} />
          </div>
        )}
        <div className="field" style={{ maxWidth: 220 }}>
          <label htmlFor="jm-carencia">{mesma ? "Carência (dias de atraso)" : "Carência dos juros (dias)"}</label>
          <input id="jm-carencia" type="number" min="0" step="1" value={carencia} onChange={(e) => setCarencia(e.target.value)} />
        </div>
      </div>
      <label className="checkbox-row" style={{ marginTop: 12 }}>
        <input type="checkbox" checked={mesma} onChange={(e) => setMesma(e.target.checked)} />
        Usar mesma carência para multa e juros
      </label>
      <div className="actions-row">
        <button type="button" onClick={salvar} disabled={salvando}>
          {salvando ? "Salvando..." : "Salvar juros e multa"}
        </button>
      </div>
    </div>
  );
}
