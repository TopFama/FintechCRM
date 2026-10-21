import { useEffect, useRef, useState } from "react";
import { FiltroColuna as Filtro, FiltrosColuna, ValoresColuna } from "../filtrosColuna";
import { IconFilter } from "../icons";
import { SortDirection } from "../sort";
import SortableTh from "./SortableTh";

export type TipoColuna = "texto" | "numero" | "data";

/** Controle de filtros das colunas de um relatório: o valor atual, como alterar e de onde vêm os valores. */
export interface ControleFiltros {
  filtros: FiltrosColuna;
  alterar: (coluna: string, filtro: Filtro | undefined) => void;
  valores: (coluna: string, busca: string) => Promise<ValoresColuna>;
}

/**
 * Filtro de uma coluna, estilo Excel: pesquisa, "Selecionar tudo" e valores
 * marcáveis (texto e valor); coluna de data e de valor também têm de, até.
 * Os valores vêm do servidor, já dentro dos demais filtros.
 */
function FiltroDaColuna({
  rotulo,
  tipo,
  filtro,
  rotuloVazio = "(Vazios)",
  formatar,
  controle,
  coluna,
}: {
  rotulo: string;
  tipo: TipoColuna;
  filtro: Filtro | undefined;
  rotuloVazio?: string;
  formatar?: (v: string) => string;
  controle: ControleFiltros;
  coluna: string;
}) {
  const [aberto, setAberto] = useState(false);
  const [posicao, setPosicao] = useState({ top: 0, left: 0 });
  const [busca, setBusca] = useState("");
  const [lista, setLista] = useState<ValoresColuna | null>(null);
  const [erro, setErro] = useState(false);
  // null = nenhuma restrição (todos marcados)
  const [marcados, setMarcados] = useState<Set<string> | null>(null);
  const [de, setDe] = useState("");
  const [ate, setAte] = useState("");
  const botao = useRef<HTMLButtonElement>(null);
  const caixa = useRef<HTMLDivElement>(null);
  const comLista = tipo !== "data";
  const comIntervalo = tipo !== "texto";
  const ativo = !!filtro;
  const nomeValor = (v: string) => (v === "" ? rotuloVazio : formatar ? formatar(v) : v);

  function abrir() {
    const r = botao.current?.getBoundingClientRect();
    if (r) setPosicao({ top: r.bottom + 4, left: Math.max(8, Math.min(r.left, window.innerWidth - 300)) });
    setMarcados(filtro?.valores ? new Set(filtro.valores) : null);
    setDe(filtro?.de ?? "");
    setAte(filtro?.ate ?? "");
    setBusca("");
    setAberto(true);
  }

  // Fecha ao clicar fora ou com Esc
  useEffect(() => {
    if (!aberto) return;
    const fora = (e: MouseEvent) => {
      if (!caixa.current?.contains(e.target as Node) && !botao.current?.contains(e.target as Node)) setAberto(false);
    };
    const esc = (e: KeyboardEvent) => e.key === "Escape" && setAberto(false);
    document.addEventListener("mousedown", fora);
    document.addEventListener("keydown", esc);
    return () => {
      document.removeEventListener("mousedown", fora);
      document.removeEventListener("keydown", esc);
    };
  }, [aberto]);

  // Valores do servidor, com a pesquisa
  useEffect(() => {
    if (!aberto || !comLista) return;
    let atual = true;
    setErro(false);
    const t = setTimeout(
      () =>
        controle
          .valores(coluna, busca)
          .then((r) => atual && setLista(r))
          .catch(() => atual && setErro(true)),
      busca ? 250 : 0
    );
    return () => {
      atual = false;
      clearTimeout(t);
    };
    // os valores dependem dos filtros das outras colunas
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [aberto, busca]);

  const visiveis = lista?.valores ?? [];
  const marcado = (v: string) => marcados === null || marcados.has(v);
  const todosMarcados = visiveis.length > 0 && visiveis.every(marcado);

  function trocar(valores: string[], marcar: boolean) {
    const base = new Set(marcados ?? lista?.valores ?? []);
    valores.forEach((v) => (marcar ? base.add(v) : base.delete(v)));
    // tudo marcado e sem pesquisa = sem restrição
    const completo = !busca && !lista?.truncado && (lista?.valores ?? []).every((v) => base.has(v));
    setMarcados(completo ? null : base);
  }

  const semIntervalo = !de && !ate;
  const vazio = (marcados === null || !comLista) && semIntervalo;
  const semSelecao = comLista && marcados !== null && marcados.size === 0;

  function aplicar() {
    setAberto(false);
    controle.alterar(coluna, vazio ? undefined : {
      ...(comLista && marcados !== null ? { valores: [...marcados] } : {}),
      ...(de ? { de } : {}),
      ...(ate ? { ate } : {}),
    });
  }

  return (
    <>
      <button
        ref={botao}
        type="button"
        className={`filtro-coluna-btn${ativo ? " ativo" : ""}`}
        aria-label={`Filtrar ${rotulo}`}
        aria-expanded={aberto}
        onClick={() => (aberto ? setAberto(false) : abrir())}
      >
        <IconFilter width={12} height={12} />
      </button>
      {aberto && (
        <div ref={caixa} className="filtro-coluna" style={{ top: posicao.top, left: posicao.left }} role="dialog" aria-label={`Filtro de ${rotulo}`}>
          {comIntervalo && (
            <div className="filtro-coluna-intervalo">
              <label>
                De
                <input
                  type={tipo === "data" ? "date" : "number"}
                  step={tipo === "numero" ? "0.01" : undefined}
                  value={de}
                  max={tipo === "data" ? ate || undefined : undefined}
                  onChange={(e) => setDe(e.target.value)}
                />
              </label>
              <label>
                Até
                <input
                  type={tipo === "data" ? "date" : "number"}
                  step={tipo === "numero" ? "0.01" : undefined}
                  value={ate}
                  min={tipo === "data" ? de || undefined : undefined}
                  onChange={(e) => setAte(e.target.value)}
                />
              </label>
            </div>
          )}
          {comLista && (
            <>
              <input
                type="search"
                className="filtro-coluna-busca"
                placeholder="Pesquisar"
                aria-label={`Pesquisar em ${rotulo}`}
                value={busca}
                onChange={(e) => setBusca(e.target.value)}
              />
              <div className="filtro-coluna-lista">
                {erro ? (
                  <div className="ms-empty">Não foi possível carregar</div>
                ) : !lista ? (
                  <div className="ms-empty">Carregando...</div>
                ) : visiveis.length === 0 ? (
                  <div className="ms-empty">Nada encontrado</div>
                ) : (
                  <>
                    <label className="ms-option">
                      <input type="checkbox" checked={todosMarcados} onChange={() => trocar(visiveis, !todosMarcados)} />
                      Selecionar tudo
                    </label>
                    {visiveis.map((v) => (
                      <label key={v} className="ms-option">
                        <input type="checkbox" checked={marcado(v)} onChange={() => trocar([v], !marcado(v))} />
                        {nomeValor(v)}
                      </label>
                    ))}
                    {lista.truncado && <div className="ms-empty">Pesquise para ver mais</div>}
                  </>
                )}
              </div>
            </>
          )}
          <div className="filtro-coluna-acoes">
            <button type="button" className="secondary small" onClick={() => { setAberto(false); controle.alterar(coluna, undefined); }}>
              Limpar
            </button>
            <button type="button" className="small" disabled={semSelecao} onClick={aplicar}>
              OK
            </button>
          </div>
        </div>
      )}
    </>
  );
}

/** Cabeçalho de coluna que ordena (clique no título, se `ordenacao`) e filtra (funil, se `controle`). */
export function ThFiltravel({
  coluna,
  rotulo,
  tipo = "texto",
  ordenacao,
  controle,
  rotuloVazio,
  formatar,
}: {
  coluna: string;
  rotulo: string;
  tipo?: TipoColuna;
  ordenacao?: { sortKey: string | null; sortDir: SortDirection; toggleSort: (c: any) => void };
  controle?: ControleFiltros;
  rotuloVazio?: string;
  formatar?: (v: string) => string;
}) {
  const filtro = controle && (
    <FiltroDaColuna
      coluna={coluna}
      rotulo={rotulo}
      tipo={tipo}
      filtro={controle.filtros[coluna]}
      controle={controle}
      rotuloVazio={rotuloVazio}
      formatar={formatar}
    />
  );
  if (!ordenacao) {
    return (
      <th scope="col">
        <span className="th-sortable-inner">
          {rotulo}
          {filtro}
        </span>
      </th>
    );
  }
  return (
    <SortableTh
      active={ordenacao.sortKey === coluna}
      dir={ordenacao.sortDir}
      onSort={() => ordenacao.toggleSort(coluna)}
      filtro={filtro}
    >
      {rotulo}
    </SortableTh>
  );
}
