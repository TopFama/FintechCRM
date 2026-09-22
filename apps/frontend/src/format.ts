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

const dataHoraBR = new Intl.DateTimeFormat("pt-BR", {
  timeZone: "America/Sao_Paulo",
  day: "2-digit",
  month: "2-digit",
  year: "numeric",
  hour: "2-digit",
  minute: "2-digit",
});

// O backend grava e serializa timestamps em UTC sem sufixo de fuso (ex:
// "2024-01-15T14:30:00") — sem isso, o navegador interpretaria a string como
// hora local dele, não UTC, e o horário exibido saía errado.
export function formatDataHora(iso: string | null | undefined): string {
  if (!iso) return "—";
  const normalizado = /[zZ]|[+-]\d{2}:?\d{2}$/.test(iso) ? iso : `${iso.replace(" ", "T")}Z`;
  const data = new Date(normalizado);
  if (isNaN(data.getTime())) return iso;
  return dataHoraBR.format(data).replace(",", "");
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
