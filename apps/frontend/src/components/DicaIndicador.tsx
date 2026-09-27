import { useEffect, useId, useLayoutEffect, useRef, useState } from "react";
import { createPortal } from "react-dom";
import { IconInfo } from "../icons";

const LARGURA = 260;
const MARGEM = 8;
const DISTANCIA = 6;

type Posicao = { top: number; left: number; largura: number; acima?: boolean };

// Uma dica aberta por vez: abrir outra fecha a anterior
let aberta: { dono: object; fechar: () => void } | null = null;

/** Ícone 🛈 ao lado do nome do indicador: passando o mouse, focando ou
 * tocando, mostra o que ele significa e a fórmula. O balão vai num portal no
 * <body> com `fixed`: fora do cabeçalho (não entra no nome da coluna para o
 * leitor de tela) e fora do .table-wrap, cujo overflow o cortaria. */
export default function DicaIndicador({ titulo, texto, formula }: { titulo: string; texto: string; formula: string }) {
  const id = useId();
  const botaoRef = useRef<HTMLButtonElement>(null);
  const balaoRef = useRef<HTMLSpanElement>(null);
  const [pos, setPos] = useState<Posicao | null>(null);
  // Aberta por clique/toque/foco: não fecha quando o mouse sai do ícone. No
  // Safari o clique não dá foco ao botão, então não dá para depender do foco.
  const fixaRef = useRef(false);
  // Se já estava fixa antes deste toque/clique: aí o clique no ícone fecha
  const estavaFixaRef = useRef(false);
  // Sair do ícone espera um pouco: dá tempo de levar o mouse até o balão
  const saidaRef = useRef<number | undefined>(undefined);
  const dono = useRef({}).current;

  function calcular(): Posicao | null {
    const r = botaoRef.current?.getBoundingClientRect();
    if (!r) return null;
    const largura = Math.min(LARGURA, window.innerWidth - 2 * MARGEM);
    const left = Math.max(MARGEM, Math.min(r.left + r.width / 2 - largura / 2, window.innerWidth - largura - MARGEM));
    return { top: r.bottom + DISTANCIA, left, largura };
  }

  function abrir() {
    window.clearTimeout(saidaRef.current);
    if (aberta && aberta.dono !== dono) aberta.fechar();
    aberta = { dono, fechar };
    setPos(calcular());
  }

  // Rolagem/redimensionamento só movem a dica que ainda está aberta
  function reposicionar() {
    if (aberta?.dono === dono) setPos(calcular());
  }

  function fechar() {
    window.clearTimeout(saidaRef.current);
    fixaRef.current = false;
    setPos(null);
    if (aberta?.dono === dono) aberta = null;
  }

  // Depois de desenhado, com a altura real: sem espaço embaixo (cabeçalho
  // perto do fim da tela), abre para cima
  useLayoutEffect(() => {
    const balao = balaoRef.current?.getBoundingClientRect();
    const botao = botaoRef.current?.getBoundingClientRect();
    // Vira uma vez só por posição calculada (acima): sem isso, com o ícone
    // fora da tela, o efeito viraria de novo a cada render, sem parar
    if (!pos || pos.acima || !balao || !botao) return;
    if (balao.bottom > window.innerHeight - MARGEM && botao.top - DISTANCIA - balao.height >= MARGEM) {
      setPos({ ...pos, top: botao.top - DISTANCIA - balao.height, acima: true });
    }
  }, [pos]);

  function sairDoMouse() {
    if (fixaRef.current) return;
    window.clearTimeout(saidaRef.current);
    saidaRef.current = window.setTimeout(fechar, 150);
  }

  // Desmontou aberta (tabela recarregou): não deixa a referência para trás
  useEffect(
    () => () => {
      window.clearTimeout(saidaRef.current);
      if (aberta?.dono === dono) aberta = null;
    },
    [dono]
  );

  const estaAberta = pos !== null;
  useEffect(() => {
    if (!estaAberta) return;
    const tecla = (e: KeyboardEvent) => e.key === "Escape" && fechar();
    // Toque/clique fora do ícone e do balão fecha (no Safari não há blur)
    const fora = (e: PointerEvent) => {
      const alvo = e.target as Node;
      if (!botaoRef.current?.contains(alvo) && !balaoRef.current?.contains(alvo)) fechar();
    };
    // Rolar a página ou a tabela acompanha o ícone em vez de fechar
    window.addEventListener("scroll", reposicionar, true);
    window.addEventListener("resize", reposicionar);
    window.addEventListener("keydown", tecla);
    document.addEventListener("pointerdown", fora, true);
    return () => {
      window.removeEventListener("scroll", reposicionar, true);
      window.removeEventListener("resize", reposicionar);
      window.removeEventListener("keydown", tecla);
      document.removeEventListener("pointerdown", fora, true);
    };
  }, [estaAberta]);

  return (
    <>
      <button
        ref={botaoRef}
        type="button"
        className="dica-botao"
        aria-label={`O que é ${titulo}`}
        aria-describedby={id}
        onMouseEnter={() => (pos ? window.clearTimeout(saidaRef.current) : abrir())}
        onMouseLeave={sairDoMouse}
        onPointerDown={() => {
          estavaFixaRef.current = fixaRef.current && pos !== null;
        }}
        onFocus={() => {
          fixaRef.current = true;
          abrir();
        }}
        onBlur={fechar}
        // Dentro de cabeçalho ordenável: o clique no 🛈 não reordena a tabela.
        // Clique/toque abre e fixa; de novo, fecha. Pelo teclado (detail 0)
        // o foco já abriu, então Enter/Espaço alterna.
        onClick={(e) => {
          e.stopPropagation();
          const fecharAgora = e.detail === 0 ? fixaRef.current && pos !== null : estavaFixaRef.current;
          estavaFixaRef.current = false;
          if (fecharAgora) return fechar();
          fixaRef.current = true;
          if (!pos) abrir();
        }}
      >
        <IconInfo width={14} height={14} />
      </button>
      {createPortal(
        // Sempre no DOM (escondido quando fechado) para o aria-describedby já
        // valer quando o foco chega no ícone
        <span
          ref={balaoRef}
          id={id}
          role="tooltip"
          className="dica-balao"
          hidden={!pos}
          style={pos ? { top: pos.top, left: pos.left, width: pos.largura } : undefined}
          // Sem isso o toque tira o foco do 🛈 e o balão some antes do clique
          onMouseDown={(e) => e.preventDefault()}
          onMouseEnter={() => window.clearTimeout(saidaRef.current)}
          onMouseLeave={sairDoMouse}
          // O portal ainda propaga eventos pela árvore do React até o cabeçalho
          // e a linha: tocar no balão só fecha, sem reordenar nem navegar
          onClick={(e) => {
            e.stopPropagation();
            fechar();
          }}
        >
          <span className="dica-texto">{texto}</span>
          <span className="dica-formula">{formula}</span>
        </span>,
        document.body
      )}
    </>
  );
}
