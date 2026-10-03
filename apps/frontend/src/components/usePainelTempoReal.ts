import { useEffect, useState } from "react";
import { api, PainelTempoReal, WS_SEM_RECONEXAO } from "../api";

// Números dos cards da fila empurrados pelo backend a cada mudança. Sem conexão
// (ainda conectando, caiu, período sem tempo real) devolve null e a tela fica
// com o polling. Com a aba oculta fecha, como a atualização automática.
export function usePainelTempoReal(de?: string, ate?: string): PainelTempoReal | null {
  const [numeros, setNumeros] = useState<PainelTempoReal | null>(null);

  useEffect(() => {
    setNumeros(null);
    if (!de || !ate) return;
    let ws: WebSocket | null = null;
    let timer: number | undefined;
    let espera = 2_000;

    const fechar = () => {
      const atual = ws;
      ws = null;
      atual?.close();
      setNumeros(null);
    };
    const conectar = () => {
      window.clearTimeout(timer);
      if (document.hidden || ws) return;
      const atual = api.painelTempoReal({ de, ate }, (n) => {
        espera = 2_000;
        setNumeros(n);
      });
      ws = atual;
      atual.onclose = (e) => {
        if (ws !== atual) return; // fechado por aqui
        ws = null;
        setNumeros(null);
        if (WS_SEM_RECONEXAO.includes(e.code)) return;
        timer = window.setTimeout(conectar, espera);
        espera = Math.min(espera * 2, 60_000);
      };
    };
    const aoMudarVisibilidade = () => (document.hidden ? fechar() : conectar());

    conectar();
    document.addEventListener("visibilitychange", aoMudarVisibilidade);
    return () => {
      window.clearTimeout(timer);
      document.removeEventListener("visibilitychange", aoMudarVisibilidade);
      fechar();
    };
  }, [de, ate]);

  return numeros;
}
