import { useEffect, useRef } from "react";

// Uma consulta por vez: `nova()` cancela a anterior (a requisição e o polling de
// verdade, não só ignora a resposta) e devolve o sinal da nova. Ao desmontar,
// cancela a que ainda estiver pendente. Quem consulta confere `signal.aborted`
// no then/finally e ignora o erro de `foiCancelada`.
export function useRequisicaoUnica(): () => AbortSignal {
  const atual = useRef<AbortController | null>(null);
  useEffect(() => () => atual.current?.abort(), []);
  return () => {
    atual.current?.abort();
    atual.current = new AbortController();
    return atual.current.signal;
  };
}
