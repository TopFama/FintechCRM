import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { api } from "../../api";
import { IconAlert } from "../../icons";
import MultiSelect from "../MultiSelect";
import { OpcoesCobranca } from "../useOpcoesCobranca";

export default function LeadsCard({ opcoes }: { opcoes: OpcoesCobranca }) {
  const [novos, setNovos] = useState<number | null>(null);
  const [enviados, setEnviados] = useState<number | null>(null);
  const [faixas, setFaixas] = useState<string[]>([]);
  const [exportando, setExportando] = useState(false);
  const [erro, setErro] = useState<string | null>(null);

  useEffect(() => {
    api.contarLeads("novo").then(setNovos).catch((e) => setErro(e.message));
    api.contarLeads("cobrado").then(setEnviados).catch((e) => setErro(e.message));
  }, []);

  async function exportar() {
    setExportando(true);
    setErro(null);
    try {
      // sem status: o backend exporta só os leads já enviados
      await api.exportarLeads({ faixa: faixas });
    } catch (e) {
      setErro(e instanceof Error ? e.message : "Erro ao exportar");
    } finally {
      setExportando(false);
    }
  }

  return (
    <div className="card">
      <div className="card-header">
        <h3>Leads</h3>
        <Link to="/leads">Ver leads →</Link>
      </div>

      <div className="stat-grid">
        <div className="stat">
          <div>
            <div className="value">{novos === null ? "…" : novos.toLocaleString("pt-BR")}</div>
            <div className="label">Leads novos</div>
          </div>
        </div>
        <div className="stat">
          <div>
            <div className="value">{enviados === null ? "…" : enviados.toLocaleString("pt-BR")}</div>
            <div className="label">Leads enviados</div>
          </div>
        </div>
      </div>

      <div className="form-row" style={{ flexWrap: "wrap", alignItems: "flex-end" }}>
        <MultiSelect
          label="Faixas a exportar"
          options={(opcoes.regras?.faixas ?? []).map((f) => ({ value: f, label: f }))}
          value={faixas}
          onChange={setFaixas}
          placeholder="Todas"
        />
        <div className="field">
          <label aria-hidden="true" style={{ visibility: "hidden" }}>
            Exportar
          </label>
          <button type="button" onClick={exportar} disabled={exportando}>
            {exportando ? "Exportando..." : "Exportar leads enviados (.xlsx)"}
          </button>
        </div>
      </div>
      <div className="field-hint">Planilha com Codigo, Nome, CPF e Celular dos leads com mensagem enviada.</div>

      {erro && (
        <div className="error-box">
          <IconAlert width={16} height={16} />
          <span>{erro}</span>
        </div>
      )}
    </div>
  );
}
