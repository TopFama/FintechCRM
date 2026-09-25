import { useEffect, useRef, useState } from "react";

// Contador que avança sozinho a cada `intervaloMs` para a tela buscar os dados
// de novo, sem F5. Com a aba oculta não conta (ninguém está vendo, não gasta
// banco); ao voltar, avança na hora se o intervalo já passou.
export function useAtualizacaoAutomatica(intervaloMs: number): number {
  const [ciclo, setCiclo] = useState(0);
  const ultimo = useRef(Date.now());

  useEffect(() => {
    let timer: number | undefined;
    const agendar = () => {
      window.clearTimeout(timer);
      if (document.hidden) return;
      const falta = intervaloMs - (Date.now() - ultimo.current);
      timer = window.setTimeout(() => {
        ultimo.current = Date.now();
        setCiclo((c) => c + 1);
      }, Math.max(falta, 0));
    };
    agendar();
    document.addEventListener("visibilitychange", agendar);
    return () => {
      window.clearTimeout(timer);
      document.removeEventListener("visibilitychange", agendar);
    };
  }, [intervaloMs, ciclo]);

  return ciclo;
}

// Diz se a busca que vai rodar agora é só a atualização automática (mesmos
// filtros e ninguém clicou em "Atualizar agora"). Nesse caso a tela mantém os
// números atuais em vez de limpar e mostrar "Carregando", e o backend pode
// responder do cache compartilhado.
export function useEhAtualizacaoAutomatica(filtros: unknown, recarregar: number): () => { auto: boolean; trocouFiltro: boolean } {
  const anterior = useRef<{ filtros: string; recarregar: number } | null>(null);
  return () => {
    const chave = JSON.stringify(filtros);
    const ant = anterior.current;
    anterior.current = { filtros: chave, recarregar };
    const trocouFiltro = !ant || ant.filtros !== chave;
    return { auto: !trocouFiltro && ant.recarregar === recarregar, trocouFiltro };
  };
}
