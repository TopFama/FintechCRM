import { useEffect, useState } from "react";
import { api, OpcaoCampanha } from "../api";

/** Filtro "Campanha" dos relatórios: todas, só a régua (faixas de atraso) ou uma campanha. */
export default function SelectCampanha({
  id,
  value,
  onChange,
}: {
  id: string;
  value: string;
  onChange: (valor: string) => void;
}) {
  const [campanhas, setCampanhas] = useState<OpcaoCampanha[]>([]);

  useEffect(() => {
    api
      .opcoesCampanhas()
      .then(setCampanhas)
      .catch(() => setCampanhas([]));
  }, []);

  return (
    <div className="field" style={{ flex: "1 1 200px" }}>
      <label htmlFor={id}>Campanha</label>
      <select id={id} value={value} onChange={(e) => onChange(e.target.value)}>
        <option value="">Todas (régua e campanhas)</option>
        <option value="regua">Só a régua (faixas de atraso)</option>
        {campanhas.map((c) => (
          <option key={c.id} value={c.id}>
            {c.arquivada ? `${c.nome.replace(/ \(arquivada \w+\)$/, "")} (excluída)` : c.nome}
          </option>
        ))}
      </select>
    </div>
  );
}
