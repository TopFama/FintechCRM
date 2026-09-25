import { useEffect, useState } from "react";
import { api, OpcaoCampanha } from "../api";

/**
 * Filtro "Campanha" dos relatórios: todas, só a régua (faixas de atraso) ou uma campanha.
 * Com `enviadoDe`/`enviadoAte`, a lista traz só as campanhas com envio nesse período e
 * acompanha as datas conforme elas mudam (antes de aplicar o filtro).
 */
export default function SelectCampanha({
  id,
  value,
  onChange,
  enviadoDe,
  enviadoAte,
  compacto = false,
}: {
  id: string;
  value: string;
  onChange: (valor: string) => void;
  enviadoDe?: string;
  enviadoAte?: string;
  /** Só o select (rótulo acessível), pra barras de filtro em linha como a dos Relatórios. */
  compacto?: boolean;
}) {
  const [campanhas, setCampanhas] = useState<OpcaoCampanha[] | null>(null);

  useEffect(() => {
    let ativo = true;
    api
      .opcoesCampanhas({ enviado_de: enviadoDe, enviado_ate: enviadoAte })
      .then((lista) => {
        if (ativo) setCampanhas(lista);
      })
      .catch(() => undefined);
    return () => {
      ativo = false;
    };
  }, [enviadoDe, enviadoAte]);

  // a campanha escolhida saiu da lista (sem envio no novo período): volta pra "Todas"
  useEffect(() => {
    if (campanhas && value && value !== "regua" && !campanhas.some((c) => c.id === value)) onChange("");
  }, [campanhas]); // eslint-disable-line react-hooks/exhaustive-deps

  const select = (
    <select
      id={id}
      aria-label={compacto ? "Campanha" : undefined}
      value={value}
      onChange={(e) => onChange(e.target.value)}
      style={compacto ? { minWidth: 180 } : undefined}
    >
      <option value="">Todas (régua e campanhas)</option>
      <option value="regua">Só a régua (faixas de atraso)</option>
      {(campanhas ?? []).some((c) => c.fixa) && (
        <optgroup label="Remarketing do Renegocie (campanhas fixas)">
          {(campanhas ?? [])
            .filter((c) => c.fixa)
            .map((c) => (
              <option key={c.id} value={c.id}>
                {c.nome}
              </option>
            ))}
        </optgroup>
      )}
      {(campanhas ?? []).some((c) => !c.fixa) && (
        <optgroup label="Campanhas">
          {(campanhas ?? [])
            .filter((c) => !c.fixa)
            .map((c) => (
              <option key={c.id} value={c.id}>
                {c.arquivada ? `${c.nome.replace(/ \(arquivada \w+\)$/, "")} (excluída)` : c.nome}
              </option>
            ))}
        </optgroup>
      )}
    </select>
  );
  if (compacto) return select;
  return (
    <div className="field" style={{ flex: "1 1 200px" }}>
      <label htmlFor={id}>Campanha</label>
      {select}
    </div>
  );
}
