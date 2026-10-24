import { useEffect, useState } from "react";

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

/** Valor do parâmetro `filtros` das rotas dos relatórios (undefined = sem filtro). */
export function serializarFiltros(filtros: FiltrosColuna): string | undefined {
  return Object.keys(filtros).length ? JSON.stringify(filtros) : undefined;
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
