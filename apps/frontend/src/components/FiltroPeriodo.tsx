import { useState } from "react";

export type OpcaoPeriodo = "hoje" | "7dias" | "mes" | "personalizado";
export type Periodo = { de?: string; ate?: string };

const ROTULOS: Record<OpcaoPeriodo, string> = {
  hoje: "Hoje",
  "7dias": "Últimos 7 dias",
  mes: "Este mês",
  personalizado: "Personalizado",
};

// Data local (GMT-3 do navegador) em yyyy-mm-dd, sem passar por UTC.
export function isoLocal(d: Date): string {
  const p = (n: number) => String(n).padStart(2, "0");
  return `${d.getFullYear()}-${p(d.getMonth() + 1)}-${p(d.getDate())}`;
}

export function periodoDe(opcao: OpcaoPeriodo, de = "", ate = ""): Periodo {
  const hoje = new Date();
  if (opcao === "hoje") return { de: isoLocal(hoje), ate: isoLocal(hoje) };
  if (opcao === "7dias") {
    const inicio = new Date(hoje);
    inicio.setDate(hoje.getDate() - 6);
    return { de: isoLocal(inicio), ate: isoLocal(hoje) };
  }
  if (opcao === "mes") return { de: isoLocal(new Date(hoje.getFullYear(), hoje.getMonth(), 1)), ate: isoLocal(hoje) };
  return { de: de || undefined, ate: ate || undefined };
}

// Cards clicáveis de período. `opcoes` define quais aparecem; `permiteLimpar`
// deixa clicar de novo no card ativo para voltar a "sem filtro".
export default function FiltroPeriodo({
  opcoes,
  inicial,
  permiteLimpar = false,
  onChange,
}: {
  opcoes: OpcaoPeriodo[];
  inicial: OpcaoPeriodo | null;
  permiteLimpar?: boolean;
  onChange: (p: Periodo) => void;
}) {
  const [ativo, setAtivo] = useState<OpcaoPeriodo | null>(inicial);
  const [de, setDe] = useState("");
  const [ate, setAte] = useState("");

  function escolher(o: OpcaoPeriodo) {
    const proximo = permiteLimpar && ativo === o ? null : o;
    setAtivo(proximo);
    onChange(proximo ? periodoDe(proximo, de, ate) : {});
  }

  function mudarData(novoDe: string, novoAte: string) {
    setDe(novoDe);
    setAte(novoAte);
    onChange(periodoDe("personalizado", novoDe, novoAte));
  }

  return (
    <div className="periodo-filtro">
      <div className="periodo-cards">
        {opcoes.map((o) => (
          <button
            key={o}
            type="button"
            className={`periodo-card${ativo === o ? " ativo" : ""}`}
            aria-pressed={ativo === o}
            onClick={() => escolher(o)}
          >
            {ROTULOS[o]}
          </button>
        ))}
      </div>
      {ativo === "personalizado" && (
        <div className="form-row">
          <div className="field">
            <label>Data mínima</label>
            <input type="date" value={de} max={ate || undefined} onChange={(e) => mudarData(e.target.value, ate)} />
          </div>
          <div className="field">
            <label>Data máxima</label>
            <input type="date" value={ate} min={de || undefined} onChange={(e) => mudarData(de, e.target.value)} />
          </div>
        </div>
      )}
    </div>
  );
}
