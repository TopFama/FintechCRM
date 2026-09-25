import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { api } from "../../api";
import { IconAlert } from "../../icons";
import FiltroPeriodo, { Periodo } from "../FiltroPeriodo";
import MultiSelect from "../MultiSelect";
import { useAtualizacaoAutomatica } from "../useAtualizacaoAutomatica";
import { OpcoesCobranca } from "../useOpcoesCobranca";

export default function LeadsCard({ opcoes, recarregar }: { opcoes: OpcoesCobranca; recarregar: number }) {
  const [novos, setNovos] = useState<number | null>(null);
  const [enviados, setEnviados] = useState<number | null>(null);
  const [faixas, setFaixas] = useState<string[]>([]);
  const [exportando, setExportando] = useState(false);
  const [erro, setErro] = useState<string | null>(null);
  const [periodo, setPeriodo] = useState<Periodo>({});
  // Novos contam pela data em que viraram lead; enviados, pela data do envio.
  const filtroNovos = { criado_de: periodo.de, criado_ate: periodo.ate };
  const filtroEnviados = { enviado_de: periodo.de, enviado_ate: periodo.ate };
  const ciclo = useAtualizacaoAutomatica(60_000);

  useEffect(() => {
    if (Boolean(periodo.de) !== Boolean(periodo.ate)) return;
    let atual = true;
    // Novos = tudo que foi pra fila no período (todo lead gerado entra na fila), enviado ou não.
    Promise.all([api.contarLeads(undefined, filtroNovos), api.contarLeads("cobrado", filtroEnviados)])
      .then(([n, e]) => {
        if (!atual) return;
        setNovos(n);
        setEnviados(e);
        setErro(null);
      })
      .catch((e) => atual && setErro(e.message));
    return () => {
      atual = false;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [periodo, recarregar, ciclo]);

  async function exportar() {
    setExportando(true);
    setErro(null);
    try {
      // sem status: o backend exporta só os leads já enviados
      await api.exportarLeads({ faixa: faixas, ...filtroEnviados });
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
      </div>

      <FiltroPeriodo opcoes={["hoje", "personalizado"]} inicial={null} permiteLimpar onChange={setPeriodo} />

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
      <div className="field-hint">Planilha com Codigo, Nome, Celular e CPF dos leads com mensagem enviada.</div>

      {erro && (
        <div className="error-box">
          <IconAlert width={16} height={16} />
          <span>{erro}</span>
        </div>
      )}
    </div>
  );
}
