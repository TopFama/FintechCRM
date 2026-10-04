import { useEffect, useRef, useState } from "react";

// Lista única de janelas de pagamento (Efetividade, Quem pagou e config do
// Dashboard em Indicadores). "" = qualquer data após a cobrança (sem limite).
const JANELAS = [
  { value: "", label: "Qualquer data após a cobrança" },
  { value: "3", label: "Até 3 dias" },
  { value: "7", label: "Até 7 dias" },
  { value: "15", label: "Até 15 dias" },
  { value: "30", label: "Até 30 dias" },
];
const PREDEFINIDAS = new Set(JANELAS.map((j) => j.value));

function diasValidos(texto: string): boolean {
  return /^\d+$/.test(texto) && Number(texto) <= 365;
}

/** `valor`: "" (sem limite), dias em texto, ou null quando "Outro" está sem um número válido (0–365). */
export default function SelectJanelaPagamento({
  id,
  valor,
  onChange,
}: {
  id: string;
  valor: string | null;
  onChange: (dias: string | null) => void;
}) {
  const [outro, setOutro] = useState(valor === null || !PREDEFINIDAS.has(valor));
  const [texto, setTexto] = useState(valor !== null && !PREDEFINIDAS.has(valor) ? valor : "");
  const emitido = useRef(valor);

  function emitir(dias: string | null) {
    emitido.current = dias;
    onChange(dias);
  }

  // valor trocado por fora (Limpar, URL, config carregada); o que veio daqui
  // não mexe na tela (digitar "3" a caminho de "30" não pula para "Até 3 dias")
  useEffect(() => {
    if (valor === emitido.current) return;
    emitido.current = valor;
    if (valor === null) return;
    const predefinida = PREDEFINIDAS.has(valor);
    setOutro(!predefinida);
    if (!predefinida) setTexto(valor);
  }, [valor]);

  return (
    <>
      <div className="field" style={{ flex: "1 1 200px" }}>
        <label htmlFor={id}>Janela de pagamento</label>
        <select
          id={id}
          value={outro ? "outro" : valor ?? ""}
          onChange={(e) => {
            if (e.target.value === "outro") {
              setOutro(true);
              setTexto("");
              emitir(null);
            } else {
              setOutro(false);
              emitir(e.target.value);
            }
          }}
        >
          {JANELAS.map((j) => (
            <option key={j.value} value={j.value}>
              {j.label}
            </option>
          ))}
          <option value="outro">Outro (dias)</option>
        </select>
      </div>
      {outro && (
        <div className="field" style={{ flex: "0 1 120px" }}>
          <label htmlFor={`${id}-dias`}>Dias (0–365)</label>
          <input
            id={`${id}-dias`}
            type="number"
            min={0}
            max={365}
            value={texto}
            onChange={(e) => {
              setTexto(e.target.value);
              emitir(diasValidos(e.target.value) ? String(Number(e.target.value)) : null);
            }}
          />
          {!diasValidos(texto) && <div className="field-hint">Informe uma janela entre 0 e 365 dias.</div>}
        </div>
      )}
    </>
  );
}
