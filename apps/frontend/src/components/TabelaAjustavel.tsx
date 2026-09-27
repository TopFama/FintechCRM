import { CSSProperties, KeyboardEvent, PointerEvent, ReactNode, useEffect, useRef, useState } from "react";

const MINIMO = 120;
const PASSO = 40;
const chave = (id: string) => `altura-tabela:${id}`;

function lerAltura(id: string): number | null {
  try {
    const v = Number(localStorage.getItem(chave(id)));
    return v >= MINIMO ? v : null;
  } catch {
    return null;
  }
}

function gravarAltura(id: string, altura: number | null) {
  try {
    if (altura === null) localStorage.removeItem(chave(id));
    else localStorage.setItem(chave(id), String(altura));
  } catch {
    // Sem armazenamento (aba anônima, bloqueado): a altura só vale nesta visita
  }
}

/** Tabela do Dashboard com altura ajustável: arrastar a barra de baixo (mouse
 * ou dedo) ou usar ↑/↓ nela aumenta ou diminui a área visível, e duplo clique
 * volta ao padrão. Cabeçalho, linha de total e primeira coluna ficam fixos na
 * rolagem (CSS em .tabela-ajustavel). A altura fica guardada no navegador,
 * uma por tabela. */
export default function TabelaAjustavel({
  id,
  rotulo,
  style,
  children,
}: {
  id: string;
  rotulo: string;
  style?: CSSProperties;
  children: ReactNode;
}) {
  const wrapRef = useRef<HTMLDivElement>(null);
  // max-height, não height: tabela menor que a altura escolhida não sobra espaço em branco
  const [altura, setAltura] = useState<number | null>(() => lerAltura(id));
  const arrasto = useRef<{ y: number; h: number } | null>(null);

  useEffect(() => gravarAltura(id, altura), [id, altura]);

  // Não cresce além da tabela inteira (mais a barra de rolagem lateral, se houver)
  function ajustar(h: number) {
    const w = wrapRef.current;
    if (!w) return;
    const tabela = w.querySelector("table");
    const max = Math.max(MINIMO, (tabela?.offsetHeight ?? w.scrollHeight) + (w.offsetHeight - w.clientHeight));
    setAltura(Math.round(Math.min(Math.max(h, MINIMO), max)));
  }

  const alturaAtual = () => wrapRef.current?.offsetHeight ?? MINIMO;

  function iniciar(e: PointerEvent<HTMLDivElement>) {
    e.currentTarget.setPointerCapture(e.pointerId);
    arrasto.current = { y: e.clientY, h: alturaAtual() };
  }

  function mover(e: PointerEvent<HTMLDivElement>) {
    if (arrasto.current) ajustar(arrasto.current.h + e.clientY - arrasto.current.y);
  }

  function tecla(e: KeyboardEvent<HTMLDivElement>) {
    const passos: Record<string, number> = { ArrowUp: -PASSO, ArrowDown: PASSO, Home: -Infinity, End: Infinity };
    if (!(e.key in passos)) return;
    e.preventDefault();
    ajustar(alturaAtual() + passos[e.key]);
  }

  return (
    <>
      <div
        ref={wrapRef}
        className="table-wrap tabela-ajustavel"
        style={{ ...style, ...(altura !== null ? { maxHeight: altura } : {}) }}
      >
        {children}
      </div>
      <div
        role="separator"
        aria-orientation="horizontal"
        aria-label={`Ajustar altura da tabela ${rotulo}`}
        aria-valuemin={MINIMO}
        aria-valuenow={altura ?? undefined}
        tabIndex={0}
        className="alca-altura"
        title="Arraste para ajustar a altura; duplo clique volta ao padrão"
        onPointerDown={iniciar}
        onPointerMove={mover}
        onPointerUp={() => (arrasto.current = null)}
        onPointerCancel={() => (arrasto.current = null)}
        onDoubleClick={() => setAltura(null)}
        onKeyDown={tecla}
      />
    </>
  );
}
