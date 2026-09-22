const brl = new Intl.NumberFormat("pt-BR", { style: "currency", currency: "BRL" });

export function formatBRL(v: string | number | null | undefined): string {
  if (v === null || v === undefined || v === "") return "—";
  const n = typeof v === "string" ? parseFloat(v) : v;
  if (isNaN(n)) return "—";
  return brl.format(n);
}

// Converte YYYY-MM-DD sem passar por new Date para não deslocar por fuso horário.
export function formatData(iso: string | null | undefined): string {
  if (!iso) return "—";
  const parts = iso.slice(0, 10).split("-");
  if (parts.length !== 3) return iso;
  const [a, m, d] = parts;
  return `${d}/${m}/${a}`;
}

export function formatDataHora(iso: string | null | undefined): string {
  if (!iso) return "—";
  // iso pode ser "2024-01-15T14:30:00", "2024-01-15 14:30:00" ou com timezone
  const [datePart, timePart] = iso.split(/[T ]/);
  const partes = datePart.split("-");
  if (partes.length !== 3) return iso;
  const [a, m, d] = partes;
  const hora = timePart ? timePart.slice(0, 5) : "";
  return hora ? `${d}/${m}/${a} ${hora}` : `${d}/${m}/${a}`;
}

export function formatCpf(digitos: string | null | undefined): string {
  if (!digitos) return "—";
  const s = digitos.replace(/\D/g, "");
  if (s.length === 11) {
    return s.replace(/(\d{3})(\d{3})(\d{3})(\d{2})/, "$1.$2.$3-$4");
  }
  if (s.length === 14) {
    return s.replace(/(\d{2})(\d{3})(\d{3})(\d{4})(\d{2})/, "$1.$2.$3/$4-$5");
  }
  return digitos;
}

// "5563991234567" → "+55 (63) 99123-4567"
export function formatCelular(cel: string | null | undefined): string {
  if (!cel) return "—";
  const s = cel.replace(/\D/g, "");
  if (s.length === 13) {
    // 55 + DD + 9XXXXXXXX
    const pais = s.slice(0, 2);
    const dd = s.slice(2, 4);
    const num = s.slice(4);
    const parte1 = num.slice(0, num.length - 4);
    const parte2 = num.slice(-4);
    return `+${pais} (${dd}) ${parte1}-${parte2}`;
  }
  return cel;
}

// Razão 0–1 (decimal em string vindo do backend) → "12,3%"
export function formatPercentual(razao: string | number | null | undefined): string {
  if (razao === null || razao === undefined || razao === "") return "—";
  return new Intl.NumberFormat("pt-BR", { style: "percent", minimumFractionDigits: 1, maximumFractionDigits: 1 }).format(
    Number(razao),
  );
}
