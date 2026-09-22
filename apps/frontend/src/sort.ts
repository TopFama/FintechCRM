import { useState } from "react";

export type SortDirection = "asc" | "desc";

/** Estado de ordenação de uma tabela: qual coluna e em que direção. Cada
 * página decide o valor de cada coluna (string, número, data já convertida
 * etc.) — este hook só guarda qual coluna está ativa. */
export function useSort<K extends string>(chaveInicial: K | null = null) {
  const [sortKey, setSortKey] = useState<K | null>(chaveInicial);
  const [sortDir, setSortDir] = useState<SortDirection>("asc");

  function toggleSort(chave: K) {
    if (sortKey === chave) {
      setSortDir((d) => (d === "asc" ? "desc" : "asc"));
    } else {
      setSortKey(chave);
      setSortDir("asc");
    }
  }

  return { sortKey, sortDir, toggleSort };
}

/** Ordena uma cópia da lista pelo valor que `valorFn` extrai de cada item
 * (string ou número; null/undefined sempre vão para o fim). `valorFn` nulo
 * = sem ordenação ativa, devolve a lista como veio. */
export function ordenarPor<T>(
  itens: T[],
  valorFn: ((item: T) => string | number | null | undefined) | null,
  dir: SortDirection
): T[] {
  if (!valorFn) return itens;
  const copia = [...itens];
  copia.sort((a, b) => {
    const va = valorFn(a);
    const vb = valorFn(b);
    if (va == null && vb == null) return 0;
    if (va == null) return 1;
    if (vb == null) return -1;
    if (va < vb) return -1;
    if (va > vb) return 1;
    return 0;
  });
  if (dir === "desc") copia.reverse();
  return copia;
}

/** Índice de cada faixa na "ordem de atraso" (a mesma ordem de
 * `RegrasCobranca.faixas`, que já vem por dia_min crescente) — usado para
 * ordenar colunas de faixa de atraso pela progressão do atraso, não em
 * ordem alfabética. */
export function ordemFaixaFn(nomesFaixa: string[] | undefined): (nome: string | null | undefined) => number {
  const indice = new Map((nomesFaixa || []).map((nome, i) => [nome, i]));
  return (nome) => (nome != null && indice.has(nome) ? (indice.get(nome) as number) : Infinity);
}
