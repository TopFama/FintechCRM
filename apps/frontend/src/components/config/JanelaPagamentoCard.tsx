import { useEffect, useState } from "react";
import { api } from "../../api";
import { IconAlert, IconCheckCircle } from "../../icons";
import SelectJanelaPagamento from "../SelectJanelaPagamento";

// Janela do card de pagamentos do Dashboard ("Pagaram em até N dias").
export default function JanelaPagamentoCard() {
  // undefined = carregando; null = "Outro" sem número válido
  const [janela, setJanela] = useState<string | null | undefined>(undefined);
  const [erro, setErro] = useState<string | null>(null);
  const [sucesso, setSucesso] = useState<string | null>(null);
  const [salvando, setSalvando] = useState(false);

  function aplicar(dias: number | null) {
    setJanela(dias === null ? "" : String(dias));
  }

  useEffect(() => {
    api
      .getConfigCobranca()
      .then((c) => aplicar(c.parametros.dias_janela_dashboard))
      .catch((e) => setErro(e.message));
  }, []);

  async function salvar() {
    if (janela == null) return;
    setErro(null);
    setSucesso(null);
    setSalvando(true);
    try {
      const c = await api.salvarParametrosCobranca({ dias_janela_dashboard: janela === "" ? null : Number(janela) });
      aplicar(c.parametros.dias_janela_dashboard);
      setSucesso("Janela de pagamento salva");
    } catch (e) {
      setErro(e instanceof Error ? e.message : "Erro ao salvar a janela de pagamento");
    } finally {
      setSalvando(false);
    }
  }

  return (
    <div className="card">
      <div className="card-header">
        <h3>Dashboard</h3>
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

      {janela !== undefined && (
        <div style={{ display: "flex", gap: 16, flexWrap: "wrap", maxWidth: 480 }}>
          <SelectJanelaPagamento id="ind-janela-pagamento" valor={janela} onChange={setJanela} />
        </div>
      )}
      <div className="actions-row">
        <button type="button" onClick={salvar} disabled={salvando || janela == null}>
          {salvando ? "Salvando..." : "Salvar janela"}
        </button>
      </div>
    </div>
  );
}
