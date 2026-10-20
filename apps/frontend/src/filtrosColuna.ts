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

// A seleção vale enquanto o usuário está em Relatórios: sai da sessão ao deixar a tela
const CHAVE = "relatorios:filtros";
type PorAba = Record<string, FiltrosColuna>;

function ler(): PorAba {
  try {
    return JSON.parse(sessionStorage.getItem(CHAVE) || "{}");
  } catch {
    return {};
  }
}

/** Filtros por coluna de cada aba, guardados no sessionStorage enquanto a tela de Relatórios estiver aberta. */
export function useFiltrosColuna(aba: string) {
  const [porAba, setPorAba] = useState<PorAba>(ler);

  useEffect(
    () => () => {
      try {
        sessionStorage.removeItem(CHAVE);
      } catch {
        /* sem sessionStorage: os filtros só vivem na tela */
      }
    },
    []
  );

  function atualizar(proximo: PorAba) {
    setPorAba(proximo);
    try {
      sessionStorage.setItem(CHAVE, JSON.stringify(proximo));
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
