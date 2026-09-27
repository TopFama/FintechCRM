import { useEffect, useId, useRef, useState } from "react";
import { IconInfo } from "../icons";

const LARGURA = 260;

/** Ícone 🛈 ao lado do nome do indicador: passando o mouse ou focando,
 * mostra o que ele significa e a fórmula. O balão é `fixed` porque a tabela
 * fica num .table-wrap com overflow, que cortaria um balão absoluto. */
export default function DicaIndicador({ titulo, texto, formula }: { titulo: string; texto: string; formula: string }) {
  const id = useId();
  const botaoRef = useRef<HTMLButtonElement>(null);
  const [pos, setPos] = useState<{ top: number; left: number } | null>(null);

  function abrir() {
    const r = botaoRef.current?.getBoundingClientRect();
    if (!r) return;
    const left = Math.min(Math.max(r.left + r.width / 2 - LARGURA / 2, 8), window.innerWidth - LARGURA - 8);
    setPos({ top: r.bottom + 6, left });
  }

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
        onMouseLeave={() => setPos(null)}
        onFocus={abrir}
        onBlur={() => setPos(null)}
        // Dentro de cabeçalho ordenável: o clique no (?) não reordena a tabela
        onClick={(e) => {
          e.stopPropagation();
          if (pos) setPos(null);
          else abrir();
        }}
      >
        <IconInfo width={14} height={14} />
      </button>
      {pos && (
        <span id={id} role="tooltip" className="dica-balao" style={{ top: pos.top, left: pos.left, width: LARGURA }}>
          <span className="dica-texto">{texto}</span>
          <span className="dica-formula">{formula}</span>
        </span>
      )}
    </>
  );
}
