const brl = new Intl.NumberFormat("pt-BR", { style: "currency", currency: "BRL" });

const numeroBR = new Intl.NumberFormat("pt-BR");

// Contagens com separador de milhar: 12345 → "12.345"
export function formatNumero(v: string | number | null | undefined): string {
  if (v === null || v === undefined || v === "") return "—";
  const n = typeof v === "string" ? parseFloat(v) : v;
  if (isNaN(n)) return "—";
  return numeroBR.format(n);
}

// Valor da fila é texto: número do SETA ("435.58") ou da planilha ("1.234,56")
// sai em reais; qualquer outro formato aparece como veio.
export function formatValorFila(v: string | null | undefined): string {
  if (!v) return "—";
  const t = v.trim().replace(/^R\$\s*/, "");
  if (/^-?\d+(\.\d+)?$/.test(t)) return formatBRL(t);
  if (/^-?\d{1,3}(\.\d{3})*(,\d+)?$|^-?\d+,\d+$/.test(t)) return formatBRL(t.replace(/\./g, "").replace(",", "."));
  return v;
}

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

const horaBR = new Intl.DateTimeFormat("pt-BR", { timeZone: "America/Sao_Paulo", hour: "2-digit", minute: "2-digit" });

const diaBR = new Intl.DateTimeFormat("en-CA", { timeZone: "America/Sao_Paulo", year: "numeric", month: "2-digit", day: "2-digit" });

// "Hoje" no calendário de Brasília (GMT-3), como o backend decide o dia,
// mesmo que o computador de quem abre esteja em outro fuso. Volta um Date
// local à meia-noite desse dia, para somar/subtrair dias com setDate.
export function hojeBR(): Date {
  const [a, m, d] = diaBR.format(new Date()).split("-").map(Number);
  return new Date(a, m - 1, d);
}

export function formatHora(d: Date): string {
  return horaBR.format(d);
}

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

// ROAS (quanto voltou para cada R$ 1 gasto) → "4,25x"; sem custo vira "—"
export function formatRoas(v: string | number | null | undefined): string {
  if (v === null || v === undefined || v === "") return "—";
  return `${formatDecimal(Number(v), 2)}x`;
}

// Número com casas fixas (ex.: frequência 1,8); vazio vira "—"
export function formatDecimal(v: number | null | undefined, casas = 1): string {
  if (v === null || v === undefined || isNaN(v)) return "—";
  return v.toLocaleString("pt-BR", { minimumFractionDigits: casas, maximumFractionDigits: casas });
}
