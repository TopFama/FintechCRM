import { useEffect, useRef, useState } from "react";

export interface MultiSelectOption {
  value: string;
  label: string;
}

interface MultiSelectProps {
  label: string;
  options: MultiSelectOption[];
  value: string[];
  onChange: (v: string[]) => void;
  disabled?: boolean;
  placeholder?: string;
  id?: string;
}

export default function MultiSelect({
  label,
  options,
  value,
  onChange,
  disabled,
  placeholder = "Todos",
  id,
}: MultiSelectProps) {
  const [aberto, setAberto] = useState(false);
  const ref = useRef<HTMLDivElement>(null);

  // Fecha ao clicar fora
  useEffect(() => {
    function onOutside(e: MouseEvent) {
      if (ref.current && !ref.current.contains(e.target as Node)) {
        setAberto(false);
      }
    }
    document.addEventListener("mousedown", onOutside);
    return () => document.removeEventListener("mousedown", onOutside);
  }, []);

  function toggle(v: string) {
    if (value.includes(v)) {
      onChange(value.filter((x) => x !== v));
    } else {
      onChange([...value, v]);
    }
  }

  function onKeyDown(e: React.KeyboardEvent) {
    if (e.key === "Escape") setAberto(false);
    if (e.key === "Enter" || e.key === " ") {
      e.preventDefault();
      setAberto((a) => !a);
    }
  }

  // Rótulo do botão
  let btnLabel: string;
  if (value.length === 0) {
    btnLabel = placeholder;
  } else if (value.length <= 2) {
    btnLabel = value
      .map((v) => options.find((o) => o.value === v)?.label ?? v)
      .join(", ");
  } else {
    btnLabel = `${value.length} selecionados`;
  }

  const inputId = id ?? `ms-${label.replace(/\s+/g, "-").toLowerCase()}`;

  return (
    <div className="field">
      <label htmlFor={inputId}>{label}</label>
      <div className="ms-wrap" ref={ref}>
        <button
          id={inputId}
          type="button"
          className="ms-btn secondary"
          aria-expanded={aberto}
          aria-haspopup="listbox"
          onClick={() => !disabled && setAberto((a) => !a)}
          onKeyDown={onKeyDown}
          disabled={disabled}
        >
          <span className="ms-btn-label">{btnLabel}</span>
          <span className="ms-chevron" aria-hidden="true">
            {aberto ? "▲" : "▼"}
          </span>
        </button>

        {aberto && (
          <div className="ms-dropdown" role="listbox" aria-multiselectable="true">
            {options.length === 0 ? (
              <div className="ms-empty">Nenhuma opção</div>
            ) : (
              options.map((opt) => {
                const checked = value.includes(opt.value);
                return (
                  <label
                    key={opt.value}
                    className={`ms-option${checked ? " checked" : ""}`}
                    role="option"
                    aria-selected={checked}
                  >
                    <input
                      type="checkbox"
                      checked={checked}
                      onChange={() => toggle(opt.value)}
                    />
                    {opt.label}
                  </label>
                );
              })
            )}
          </div>
        )}
      </div>
    </div>
  );
}
