import { ReactNode } from "react";
import { urlImagemTemplate } from "../api";

// *negrito*, _itálico_, ~tachado~ e `código`: como no WhatsApp, o marcador só
// formata com o par na mesma linha, colado ao texto e fora do meio de palavra
// (nome_do_cliente não vira itálico).
const INLINE = /(?<![\p{L}\p{N}])([*_~])(?!\s)([^\n]*?[^\s])\1(?![\p{L}\p{N}])|`([^`\n]+)`/gu;
const TAGS: Record<string, "strong" | "em" | "s"> = { "*": "strong", _: "em", "~": "s" };

function formatarLinha(texto: string, chave: string): ReactNode[] {
  const nos: ReactNode[] = [];
  let inicio = 0;
  for (const m of texto.matchAll(INLINE)) {
    if (m.index! > inicio) nos.push(texto.slice(inicio, m.index));
    const k = `${chave}-${m.index}`;
    if (m[3] !== undefined) {
      nos.push(<code key={k}>{m[3]}</code>);
    } else {
      const Tag = TAGS[m[1]];
      nos.push(<Tag key={k}>{formatarLinha(m[2], k)}</Tag>);
    }
    inicio = m.index! + m[0].length;
  }
  if (inicio < texto.length) nos.push(texto.slice(inicio));
  return nos;
}

type Bloco = { tipo: "linha" | "ul" | "ol" | "citacao"; linhas: string[] };

function tipoDaLinha(linha: string): Bloco["tipo"] {
  if (/^[*-] /.test(linha)) return "ul";
  if (/^\d+\. /.test(linha)) return "ol";
  if (/^> /.test(linha)) return "citacao";
  return "linha";
}

function formatarTrecho(texto: string, chave: string): ReactNode[] {
  const blocos: Bloco[] = [];
  for (const linha of texto.split("\n")) {
    const tipo = tipoDaLinha(linha);
    const ultimo = blocos[blocos.length - 1];
    if (tipo !== "linha" && ultimo?.tipo === tipo) ultimo.linhas.push(linha);
    else blocos.push({ tipo, linhas: [linha] });
  }
  return blocos.map((b, i) => {
    const k = `${chave}-${i}`;
    if (b.tipo === "linha") return <div key={k}>{b.linhas[0] ? formatarLinha(b.linhas[0], k) : <br />}</div>;
    if (b.tipo === "citacao")
      return <blockquote key={k}>{b.linhas.map((l, j) => <div key={j}>{formatarLinha(l.slice(2), `${k}-${j}`)}</div>)}</blockquote>;
    const Lista = b.tipo === "ul" ? "ul" : "ol";
    return (
      <Lista key={k}>
        {b.linhas.map((l, j) => <li key={j}>{formatarLinha(l.replace(/^([*-]|\d+\.) /, ""), `${k}-${j}`)}</li>)}
      </Lista>
    );
  });
}

// Texto do template com a formatação do WhatsApp; ```bloco``` vira monoespaçado.
export function formatarWhatsapp(texto: string): ReactNode[] {
  return texto.split(/```([\s\S]+?)```/).flatMap<ReactNode>((parte, i) =>
    i % 2 ? [<pre key={i}>{parte}</pre>] : formatarTrecho(parte.replace(/^\n|\n$/g, ""), String(i))
  );
}

// Balão da mensagem como chega no WhatsApp: imagem do cabeçalho em cima e o
// texto já com as variáveis trocadas por quem chama.
export default function PreviaWhatsapp({
  texto,
  cabecalhoImagem = false,
  imagemUrl,
}: {
  texto: string;
  cabecalhoImagem?: boolean;
  imagemUrl?: string | null;
}) {
  return (
    <div className="template-preview-bubble">
      {cabecalhoImagem &&
        (imagemUrl ? (
          <img src={urlImagemTemplate(imagemUrl)} alt="Cabeçalho do template" />
        ) : (
          <div className="template-preview-sem-imagem">Imagem do cabeçalho</div>
        ))}
      {formatarWhatsapp(texto)}
    </div>
  );
}
