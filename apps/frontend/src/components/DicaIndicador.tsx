import { useEffect, useId, useLayoutEffect, useRef, useState } from "react";
import { IconInfo } from "../icons";

const LARGURA = 260;
const MARGEM = 8;
const DISTANCIA = 6;

type Posicao = { top: number; left: number; largura: number };

/** Ícone 🛈 ao lado do nome do indicador: passando o mouse ou focando,
 * mostra o que ele significa e a fórmula. O balão é `fixed` porque a tabela
 * fica num .table-wrap com overflow, que cortaria um balão absoluto. */
export default function DicaIndicador({ titulo, texto, formula }: { titulo: string; texto: string; formula: string }) {
  const id = useId();
  const botaoRef = useRef<HTMLButtonElement>(null);
  const balaoRef = useRef<HTMLSpanElement>(null);
  const [pos, setPos] = useState<Posicao | null>(null);

  function abrir() {
    const r = botaoRef.current?.getBoundingClientRect();
    if (!r) return;
    const largura = Math.min(LARGURA, window.innerWidth - 2 * MARGEM);
    const left = Math.max(MARGEM, Math.min(r.left + r.width / 2 - largura / 2, window.innerWidth - largura - MARGEM));
    setPos({ top: r.bottom + DISTANCIA, left, largura });
  }

  // Depois de desenhado, com a altura real: sem espaço embaixo (cabeçalho
  // perto do fim da tela), abre para cima
  useLayoutEffect(() => {
    const balao = balaoRef.current?.getBoundingClientRect();
    const botao = botaoRef.current?.getBoundingClientRect();
    if (!pos || !balao || !botao) return;
    if (balao.bottom > window.innerHeight - MARGEM && botao.top - DISTANCIA - balao.height >= MARGEM) {
      setPos({ ...pos, top: botao.top - DISTANCIA - balao.height });
    }
  }, [pos]);

  useEffect(() => {
    if (!pos) return;
    const fechar = () => setPos(null);
    const tecla = (e: KeyboardEvent) => e.key === "Escape" && fechar();
    window.addEventListener("scroll", fechar, true);
    window.addEventListener("resize", fechar);
    window.addEventListener("keydown", tecla);
    return () => {
      window.removeEventListener("scroll", fechar, true);
      window.removeEventListener("resize", fechar);
      window.removeEventListener("keydown", tecla);
    };
  }, [pos]);

  return (
    <>
      <button
        ref={botaoRef}
        type="button"
        className="dica-botao"
        aria-label={`O que é ${titulo}`}
        aria-describedby={pos ? id : undefined}
        onMouseEnter={abrir}
        // Aberta pelo foco (teclado ou clique) continua até o blur
        onMouseLeave={(e) => document.activeElement !== e.currentTarget && setPos(null)}
        onFocus={abrir}
        onBlur={() => setPos(null)}
        // Dentro de cabeçalho ordenável: o clique no 🛈 não reordena a tabela.
        // Só abre (toque no celular, Enter no teclado); fecha no blur, ao sair
        // o mouse, com Esc ou ao rolar a tela.
        onClick={(e) => {
          e.stopPropagation();
          if (!pos) abrir();
        }}
      >
        <IconInfo width={14} height={14} />
      </button>
      {pos && (
        <span
          ref={balaoRef}
          id={id}
          role="tooltip"
          className="dica-balao"
          style={{ top: pos.top, left: pos.left, width: pos.largura }}
          // Sem isso o toque tira o foco do 🛈, o balão some antes do clique e o
          // clique cai no cabeçalho (reordena) ou na linha de baixo (navega)
          onMouseDown={(e) => e.preventDefault()}
          // O balão fica dentro do cabeçalho e por cima das linhas: tocar nele só fecha
          onClick={(e) => {
            e.stopPropagation();
            setPos(null);
          }}
        >
          <span className="dica-texto">{texto}</span>
          <span className="dica-formula">{formula}</span>
        </span>
      )}
    </>
  );
}
