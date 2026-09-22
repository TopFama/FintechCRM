interface MatrizTableProps {
  clusters: string[];
  faixas: string[];
  matriz: {
    celulas: Record<string, Record<string, number | string>>;
    total_por_cluster: Record<string, number | string>;
    total_por_faixa: Record<string, number | string>;
    total: number | string;
  };
  formato: (v: number | string) => string;
  elegivel?: (cluster: string, faixa: string) => boolean;
  onCelulaClick?: (cluster: string, faixa: string) => void;
}

export default function MatrizTable({
  clusters,
  faixas,
  matriz,
  formato,
  elegivel,
  onCelulaClick,
}: MatrizTableProps) {
  function valor(cluster: string, faixa: string): number | string {
    return matriz.celulas[cluster]?.[faixa] ?? 0;
  }

  function formatVal(v: number | string): string {
    if (v === 0 || v === "0" || v === "0.00") return "–";
    return formato(v);
  }

  return (
    <div className="table-wrap">
      <table className="matriz-table">
        <thead>
          <tr>
            <th scope="col">Cluster \ Faixa</th>
            {faixas.map((f) => (
              <th scope="col" key={f}>
                {f}
              </th>
            ))}
            <th scope="col">Total</th>
          </tr>
        </thead>
        <tbody>
          {clusters.map((cl) => (
            <tr key={cl}>
              <td className="cell-strong">{cl}</td>
              {faixas.map((f) => {
                const v = valor(cl, f);
                const eleg = elegivel ? elegivel(cl, f) : true;
                const clicavel = !!onCelulaClick;
                return (
                  <td
                    key={f}
                    className={[
                      !eleg ? "matriz-cell-inelegivel" : "",
                      v === 0 || v === "0" || v === "0.00"
                        ? "matriz-cell-zero"
                        : "",
                      clicavel ? "matriz-cell-click" : "",
                    ]
                      .filter(Boolean)
                      .join(" ")}
                    onClick={
                      clicavel
                        ? () => onCelulaClick!(cl, f)
                        : undefined
                    }
                    title={
                      !eleg
                        ? "Não elegível para WhatsApp nesta combinação"
                        : undefined
                    }
                  >
                    {formatVal(v)}
                  </td>
                );
              })}
              <td className="cell-strong">
                {formatVal(matriz.total_por_cluster[cl] ?? 0)}
              </td>
            </tr>
          ))}
          <tr className="matriz-row-total">
            <td className="cell-strong">Total</td>
            {faixas.map((f) => (
              <td key={f} className="cell-strong">
                {formatVal(matriz.total_por_faixa[f] ?? 0)}
              </td>
            ))}
            <td className="cell-strong">{formatVal(matriz.total)}</td>
          </tr>
        </tbody>
      </table>
    </div>
  );
}
