import { useState } from "react";

// Campo de valor máximo com "Sem limite máximo": marcado, limpa e bloqueia o campo.
export default function CampoValorMaximo({
  id,
  label,
  value,
  onChange,
}: {
  id: string;
  label: string;
  value: string;
  onChange: (valor: string) => void;
}) {
  const [semLimite, setSemLimite] = useState(false);
  return (
    <>
      <label htmlFor={id}>{label}</label>
      <input
        id={id}
        type="number"
        min={0}
        step="0.01"
        value={semLimite ? "" : value}
        disabled={semLimite}
        onChange={(e) => onChange(e.target.value)}
      />
      <label className="checkbox-row sem-limite">
        <input
          type="checkbox"
          checked={semLimite}
          onChange={(e) => {
            setSemLimite(e.target.checked);
            if (e.target.checked) onChange("");
          }}
        />
        Sem limite máximo
      </label>
    </>
  );
}
