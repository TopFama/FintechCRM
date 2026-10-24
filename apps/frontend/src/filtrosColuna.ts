import { useEffect, useState } from "react";
import { api } from "./api";

/** Filtro de uma coluna de relatório: valores marcados (lista estilo Excel) e/ou intervalo de, até. */
export interface FiltroColuna {
  valores?: string[];
  de?: string;
  ate?: string;
}

export type FiltrosColuna = Record<string, FiltroColuna>;

export interface ValoresColuna {
  valores: string[];
  truncado: boolean;
}

/** Ordem dos indicadores nas listas do filtro: faixa pelo atraso e cluster do menor para o maior valor (regras da cobrança). */
export function useOrdemFiltros(): Record<string, string[]> {
  const [ordem, setOrdem] = useState<Record<string, string[]>>({});
  useEffect(() => {
    api.regrasCobranca().then((r) => setOrdem({ faixa: r.faixas, cluster: r.clusters })).catch(() => {});
  }, []);
  return ordem;
}

/** Valor do parâmetro `filtros` das rotas dos relatórios (undefined = sem filtro). */
export function serializarFiltros(filtros: FiltrosColuna): string | undefined {
  return Object.keys(filtros).length ? JSON.stringify(filtros) : undefined;
}

/** Valor(es) de cada coluna de um item (o que a célula mostra; data em AAAA-MM-DD); "" = vazio. */
export type CelulasColuna<T> = Record<string, (item: T) => string[]>;

/** Filtro das listas que já estão inteiras no navegador (sem servidor), com o mesmo contrato do servidor:
 * `valores` marcados e/ou intervalo de, até (número ou data). `ignorar` é a coluna cujos filtros não valem. */
export function passaFiltros<T>(item: T, celulas: CelulasColuna<T>, filtros: FiltrosColuna, ignorar?: string): boolean {
  return Object.entries(filtros).every(([coluna, f]) => {
    if (coluna === ignorar) return true;
    const valores = celulas[coluna](item);
    if (f.valores && !valores.some((v) => f.valores!.includes(v))) return false;
    if (!f.de && !f.ate) return true;
    const numero = !/^\d{4}-\d{2}-\d{2}$/.test(f.de || f.ate!);
    const comparavel = (v: string) => (numero ? Number(v) : v);
    return valores.some(
      (v) => v !== "" && (!f.de || comparavel(v) >= comparavel(f.de)) && (!f.ate || comparavel(v) <= comparavel(f.ate))
    );
  });
}

/** Lista do filtro de uma coluna, dentro dos filtros das outras colunas; vazio ("") primeiro. */
export async function valoresLocais<T>(
  itens: T[],
  celulas: CelulasColuna<T>,
  filtros: FiltrosColuna,
  coluna: string,
  busca: string
): Promise<ValoresColuna> {
  const achados = new Set(itens.filter((i) => passaFiltros(i, celulas, filtros, coluna)).flatMap(celulas[coluna]));
  const valores = [...achados]
    .filter((v) => v.toLowerCase().includes(busca.toLowerCase()))
    .sort((a, b) => (a === "" ? -1 : b === "" ? 1 : a.localeCompare(b, "pt-BR", { numeric: true })));
  return { valores, truncado: false };
}

// A seleção vale enquanto o usuário está na tela: sai da sessão ao deixá-la
const CHAVE = "relatorios:filtros";
type PorAba = Record<string, FiltrosColuna>;

function ler(chave: string): PorAba {
  try {
    return JSON.parse(sessionStorage.getItem(chave) || "{}");
  } catch {
    return {};
  }
}

/** Filtros por coluna de cada aba, guardados no sessionStorage (em `chave`) enquanto a tela estiver aberta. */
export function useFiltrosColuna(aba: string, chave = CHAVE) {
  const [porAba, setPorAba] = useState<PorAba>(() => ler(chave));

  useEffect(
    () => () => {
      try {
        sessionStorage.removeItem(chave);
      } catch {
        /* sem sessionStorage: os filtros só vivem na tela */
      }
    },
    []
  );

  function atualizar(proximo: PorAba) {
    setPorAba(proximo);
    try {
      sessionStorage.setItem(chave, JSON.stringify(proximo));
    } catch {
      /* idem */
    }
  }

  const filtros = porAba[aba] ?? {};

  function alterar(coluna: string, filtro: FiltroColuna | undefined) {
    const { [coluna]: _antigo, ...resto } = filtros;
    atualizar({ ...porAba, [aba]: filtro ? { ...resto, [coluna]: filtro } : resto });
  }

  return { filtros, alterar };
}
