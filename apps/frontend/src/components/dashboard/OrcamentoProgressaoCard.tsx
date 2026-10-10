import { useEffect, useRef, useState } from "react";
import { useAtualizacaoAutomatica, useEhAtualizacaoAutomatica } from "../useAtualizacaoAutomatica";
import { api, CategoriaGasto, OrcamentoProgressao } from "../../api";
import { formatBRL, formatData, formatNumero, hojeBR } from "../../format";
import { IconAlert, IconDownload } from "../../icons";
import { ordenarPor, useSort } from "../../sort";
import MultiSelect from "../MultiSelect";
import SortableTh from "../SortableTh";
import TabelaAjustavel from "../TabelaAjustavel";

// Categorias da Meta separadas no card; autenticação e outras só entram no gasto total
const CATEGORIAS: [CategoriaGasto, string][] = [
  ["utilitario", "Utilitário"],
  ["marketing", "Marketing"],
  ["servico", "Serviço"],
];

type ColunaNumero = "numero" | "gasto_brl" | `gasto_${CategoriaGasto}` | `qtd_${CategoriaGasto}`;

// Refaz o acumulado (gráfico, Realizado e tooltip) só com as categorias marcadas;
// nenhuma marcada = gasto total da Meta, como vem da API.
function somenteCategorias(dados: OrcamentoProgressao, categorias: string[]): OrcamentoProgressao {
  if (categorias.length === 0) return dados;
  let gasto = 0;
  let msgs = 0;
  const dias = dados.dias.map((d) => {
    if (d.gasto_acumulado_brl === null) return d;
    for (const c of categorias) {
      const v = d.por_categoria[c as CategoriaGasto];
      gasto += Number(v?.gasto_brl ?? 0);
      msgs += v?.qtd_mensagens ?? 0;
    }
    return { ...d, gasto_acumulado_brl: gasto.toFixed(2), mensagens_acumuladas: msgs };
  });
  return { ...dados, dias, valor_gasto_brl: gasto.toFixed(2) };
}

const NOMES_MES = [
  "janeiro", "fevereiro", "março", "abril", "maio", "junho",
  "julho", "agosto", "setembro", "outubro", "novembro", "dezembro",
];

// Últimos 12 meses no formato "ano-mes" para a lista suspensa.
function mesesRecentes(): { valor: string; rotulo: string }[] {
  const hoje = hojeBR();
  return Array.from({ length: 12 }, (_, i) => {
    const d = new Date(hoje.getFullYear(), hoje.getMonth() - i, 1);
    return { valor: `${d.getFullYear()}-${d.getMonth() + 1}`, rotulo: `${NOMES_MES[d.getMonth()]}/${d.getFullYear()}` };
  });
}

// Gasto real com WhatsApp (Meta, em BRL) acumulado dia a dia vs. orçamento
// cadastrado em Configurações > Indicadores. Filtro próprio: um mês ou um
// período personalizado.
export default function OrcamentoProgressaoCard({ recarregar }: { recarregar: number }) {
  const meses = mesesRecentes();
  const [selecao, setSelecao] = useState(meses[0].valor);
  const [de, setDe] = useState("");
  const [ate, setAte] = useState("");
  const [categorias, setCategorias] = useState<string[]>([]);
  const [dados, setDados] = useState<OrcamentoProgressao | null>(null);
  const [erro, setErro] = useState<string | null>(null);
  const [exportando, setExportando] = useState(false);
  const [erroExportar, setErroExportar] = useState<string | null>(null);
  // a lista por número vem inteira (sem paginação), então ordenar no navegador cobre o resultado todo
  const ordenacao = useSort<ColunaNumero>(null);
  // Gasto vem da API da Meta: atualiza devagar, e o backend guarda em cache
  const ciclo = useAtualizacaoAutomatica(15 * 60_000);
  const tipoDeBusca = useEhAtualizacaoAutomatica({ selecao, de, ate }, recarregar);

  useEffect(() => {
    const { auto, trocouFiltro } = tipoDeBusca();
    // Limpa antes de tudo: Personalizado sem datas não pode mostrar o mês anterior
    if (trocouFiltro) {
      setErro(null);
      setDados(null);
    }
    const filtro = filtroAtual();
    if (!filtro) return;
    let atual = true;
    api
      .getOrcamentoProgressao(filtro, auto)
      .then((d) => {
        if (!atual) return;
        setDados(d);
        setErro(null);
      })
      .catch((e) => atual && setErro(e.message));
    return () => {
      atual = false;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [selecao, de, ate, recarregar, ciclo]);

  function filtroAtual(): { ano?: number; mes?: number; de?: string; ate?: string } | null {
    if (selecao === "personalizado") return de && ate ? { de, ate } : null;
    const [ano, mes] = selecao.split("-").map(Number);
    return { ano, mes };
  }

  async function exportarPorDia() {
    const filtro = filtroAtual();
    if (!filtro) return;
    setExportando(true);
    setErroExportar(null);
    try {
      await api.exportarOrcamentoPorDia(filtro);
    } catch (e) {
      setErroExportar(e instanceof Error ? e.message : "Erro ao exportar");
    } finally {
      setExportando(false);
    }
  }

  const filtros = (
    <div className="form-row">
      <div className="field">
        <label htmlFor="orcamento-mes-ano">Mês/ano</label>
        <select id="orcamento-mes-ano" value={selecao} onChange={(e) => setSelecao(e.target.value)}>
          {meses.map((m) => (
            <option key={m.valor} value={m.valor}>
              {m.rotulo}
            </option>
          ))}
          <option value="personalizado">Personalizado</option>
        </select>
      </div>
      {selecao === "personalizado" && (
        <>
          <div className="field">
            <label htmlFor="orcamento-data-minima">Data mínima</label>
            <input id="orcamento-data-minima" type="date" value={de} max={ate || undefined} onChange={(e) => setDe(e.target.value)} />
          </div>
          <div className="field">
            <label htmlFor="orcamento-data-maxima">Data máxima</label>
            <input id="orcamento-data-maxima" type="date" value={ate} min={de || undefined} onChange={(e) => setAte(e.target.value)} />
          </div>
        </>
      )}
      <MultiSelect
        id="orcamento-categorias"
        label="Categorias no gráfico"
        options={CATEGORIAS.map(([value, label]) => ({ value, label }))}
        value={categorias}
        onChange={setCategorias}
        placeholder="Todas"
      />
    </div>
  );

  const cabecalho = (
    <div className="card-header">
      <div>
        <h3 style={{ marginBottom: 4 }}>Orçamento</h3>
        {dados && (
          <div className="card-subtitle">
            Gasto real com WhatsApp de {formatData(dados.de)} a {formatData(dados.ate)} vs. orçado (
            {formatBRL(dados.valor_orcado)})
          </div>
        )}
      </div>
      <button type="button" className="excel small" onClick={exportarPorDia} disabled={exportando || !filtroAtual()}>
        <IconDownload width={14} height={14} /> {exportando ? "Exportando..." : "Exportar por dia"}
      </button>
    </div>
  );

  const avisoExportar = erroExportar && (
    <div className="error-box">
      <IconAlert width={16} height={16} />
      <span>{erroExportar}</span>
    </div>
  );

  if (erro || !dados) {
    return (
      <div className="card">
        {cabecalho}
        {avisoExportar}
        {filtros}
        {erro ? (
          <div className="error-box">
            <IconAlert width={16} height={16} />
            <span>{erro}</span>
          </div>
        ) : selecao === "personalizado" && (!de || !ate) ? (
          <div className="empty-state">
            <p>Escolha a data mínima e a máxima.</p>
          </div>
        ) : (
          <div className="loading-state">Carregando orçamento...</div>
        )}
      </div>
    );
  }

  const gastoInfo = dados.valor_gasto_brl !== null;
  const grafico = somenteCategorias(dados, categorias);

  return (
    <div className="card">
      {cabecalho}
      {avisoExportar}
      {filtros}

      {gastoInfo && dados.avisos.length > 0 && (
        <div className="error-box" style={{ alignItems: "flex-start" }}>
          <IconAlert width={16} height={16} />
          <div>
            <strong>Custo incompleto: {dados.avisos.length} WABA(s) não puderam ser lidas e ficaram fora do total.</strong>
            <ul style={{ margin: "6px 0 0", paddingLeft: 18 }}>
              {dados.avisos.map((a) => (
                <li key={a.waba_id}>
                  WABA {a.waba_id}
                  {a.numeros.length > 0 ? ` (números ${a.numeros.join(", ")})` : " (sem número importado)"}: {a.motivo}
                </li>
              ))}
            </ul>
          </div>
        </div>
      )}

      {!gastoInfo ? (
        <div className="empty-state">
          <p>Sem custo do WhatsApp para o período. Motivo: {dados.motivo_sem_gasto || "não informado pela Meta"}</p>
        </div>
      ) : (
        <>
          <div className="orcamento-totais">
            <div className="stat">
              <div>
                <div className="value">{formatBRL(grafico.valor_gasto_brl!)}</div>
                <div className="label">Realizado (gasto acumulado)</div>
              </div>
            </div>
            <div className="stat">
              <div>
                <div className="value">{formatBRL(dados.valor_orcado)}</div>
                <div className="label">Orçado</div>
              </div>
            </div>
          </div>
          <GraficoGasto dados={grafico} />
          {dados.gasto_por_numero.length > 0 && (
            <TabelaAjustavel id="orcamento-por-numero" rotulo="Gasto por número" style={{ marginTop: 16 }}>
              <table>
                <thead>
                  <tr>
                    {(
                      [
                        ["numero", "Número"],
                        ...CATEGORIAS.map(([c, nome]) => [`gasto_${c}`, `${nome} (R$)`]),
                        ["gasto_brl", "Gasto no período"],
                        ...CATEGORIAS.map(([c, nome]) => [`qtd_${c}`, `${nome} (qtd)`]),
                      ] as [ColunaNumero, string][]
                    ).map(([coluna, rotulo]) => (
                      <SortableTh
                        key={coluna}
                        active={ordenacao.sortKey === coluna}
                        dir={ordenacao.sortDir}
                        onSort={() => ordenacao.toggleSort(coluna)}
                      >
                        {rotulo}
                      </SortableTh>
                    ))}
                  </tr>
                </thead>
                <tbody>
                  {ordenarPor(
                    dados.gasto_por_numero,
                    valorColuna(ordenacao.sortKey),
                    ordenacao.sortDir
                  ).map((g) => (
                    <tr key={g.numero}>
                      <td className="cell-strong">{g.numero}</td>
                      {CATEGORIAS.map(([c]) => (
                        <td key={c}>{formatBRL(g.por_categoria[c]?.gasto_brl ?? 0)}</td>
                      ))}
                      <td>{formatBRL(g.gasto_brl)}</td>
                      {CATEGORIAS.map(([c]) => (
                        <td key={c}>{formatNumero(g.por_categoria[c]?.qtd_mensagens ?? 0)}</td>
                      ))}
                    </tr>
                  ))}
                  <tr className="linha-total">
                    <td className="cell-strong">Total</td>
                    {CATEGORIAS.map(([c]) => (
                      <td key={c}>{formatBRL(somar(dados, (g) => Number(g.por_categoria[c]?.gasto_brl ?? 0)))}</td>
                    ))}
                    <td>{formatBRL(somar(dados, (g) => Number(g.gasto_brl)))}</td>
                    {CATEGORIAS.map(([c]) => (
                      <td key={c}>{formatNumero(somar(dados, (g) => g.por_categoria[c]?.qtd_mensagens ?? 0))}</td>
                    ))}
                  </tr>
                </tbody>
              </table>
            </TabelaAjustavel>
          )}
        </>
      )}
    </div>
  );
}

type GastoNumero = OrcamentoProgressao["gasto_por_numero"][number];

function somar(dados: OrcamentoProgressao, valor: (g: GastoNumero) => number): number {
  return dados.gasto_por_numero.reduce((t, g) => t + valor(g), 0);
}

// Valor da coluna para ordenar a tabela por número
function valorColuna(coluna: ColunaNumero | null): ((g: GastoNumero) => string | number) | null {
  if (!coluna) return null;
  if (coluna === "numero") return (g) => g.numero;
  if (coluna === "gasto_brl") return (g) => Number(g.gasto_brl);
  const [tipo, c] = coluna.split("_") as ["gasto" | "qtd", CategoriaGasto];
  return tipo === "gasto"
    ? (g) => Number(g.por_categoria[c]?.gasto_brl ?? 0)
    : (g) => g.por_categoria[c]?.qtd_mensagens ?? 0;
}

// Largura mínima do desenho: no celular o gráfico rola na horizontal em vez de espremer.
const LARGURA_MIN = 560;
const ALTURA = 260;
const M = { topo: 16, dir: 16, base: 44, esq: 104 };

function dataCurta(iso: string): string {
  const [, mes, dia] = iso.split("-");
  return `${dia}/${mes}`;
}

// Linha do gasto acumulado dia a dia + linha tracejada do limite orçado,
// com eixos (R$ no Y, datas no X) e tooltip do dia sob o mouse. A linha vai
// só até hoje; com o período em andamento, uma bolinha marca onde ela termina.
function GraficoGasto({ dados }: { dados: OrcamentoProgressao }) {
  const [hover, setHover] = useState<number | null>(null);
  // Desenha na largura real do card (1 unidade do SVG = 1 px), para o texto não crescer com o card.
  const caixaRef = useRef<HTMLDivElement>(null);
  const [largura, setLargura] = useState(720);
  useEffect(() => {
    const caixa = caixaRef.current;
    if (!caixa) return;
    const obs = new ResizeObserver(([e]) => setLargura(Math.max(LARGURA_MIN, Math.floor(e.contentRect.width))));
    obs.observe(caixa);
    return () => obs.disconnect();
  }, []);
  const dias = dados.dias;
  const orcado = Number(dados.valor_orcado);
  // dias sem valor (ainda não aconteceram) são sempre o fim da lista: o índice é o mesmo de `dias`
  const valores = dias.filter((d) => d.gasto_acumulado_brl !== null).map((d) => Number(d.gasto_acumulado_brl));
  const ultimo = valores.length - 1;
  // período ainda acompanhado: já começou (tem dia com valor) e não terminou antes de hoje
  const emAndamento = ultimo >= 0 && new Date(`${dados.ate}T00:00`) >= hojeBR();
  const maximo = Math.max(orcado, ...valores, 1) * 1.1;
  const areaL = largura - M.esq - M.dir;
  const areaA = ALTURA - M.topo - M.base;
  const x = (i: number) => M.esq + (dias.length <= 1 ? areaL / 2 : (i / (dias.length - 1)) * areaL);
  const y = (v: number) => M.topo + areaA - (v / maximo) * areaA;

  const ticksY = [0, 0.25, 0.5, 0.75, 1].map((f) => f * maximo);
  const passoX = Math.max(1, Math.ceil(dias.length / 8));
  const diario = (i: number) => valores[i] - (i > 0 ? valores[i - 1] : 0);
  const msgs = (i: number) => dias[i].mensagens_acumuladas ?? 0;
  const msgsDia = (i: number) => msgs(i) - (i > 0 ? msgs(i - 1) : 0);

  function aoMover(e: React.MouseEvent<SVGRectElement>) {
    if (ultimo < 0) return;
    const caixa = e.currentTarget.getBoundingClientRect();
    const px = ((e.clientX - caixa.left) / caixa.width) * areaL;
    const i = dias.length <= 1 ? 0 : Math.round((px / areaL) * (dias.length - 1));
    setHover(Math.min(Math.max(i, 0), ultimo));
  }

  const tipX = hover !== null ? Math.min(x(hover) + 10, largura - M.dir - 190) : 0;

  return (
    <div className="orcamento-grafico" ref={caixaRef}>
      <svg viewBox={`0 0 ${largura} ${ALTURA}`} width={largura} height={ALTURA} role="img" aria-label="Gasto acumulado por dia vs. orçado">
        {ticksY.map((v) => (
          <g key={v}>
            <line x1={M.esq} x2={largura - M.dir} y1={y(v)} y2={y(v)} stroke="var(--color-border)" />
            <text x={M.esq - 8} y={y(v) + 4} textAnchor="end" fontSize="11" fill="var(--color-text-muted)">
              {formatBRL(v.toFixed(2))}
            </text>
          </g>
        ))}
        {dias.map((d, i) =>
          i % passoX === 0 || (i === dias.length - 1 && i % passoX >= passoX / 2) ? (
            <text key={d.data} x={x(i)} y={ALTURA - M.base + 16} textAnchor="middle" fontSize="11" fill="var(--color-text-muted)">
              {dataCurta(d.data)}
            </text>
          ) : null
        )}
        <text x={M.esq + areaL / 2} y={ALTURA - 6} textAnchor="middle" fontSize="12" fill="var(--color-text-muted)">
          Data
        </text>
        <text
          x={14}
          y={M.topo + areaA / 2}
          textAnchor="middle"
          fontSize="12"
          fill="var(--color-text-muted)"
          transform={`rotate(-90 14 ${M.topo + areaA / 2})`}
        >
          Gasto acumulado (R$)
        </text>

        <line x1={M.esq} x2={largura - M.dir} y1={y(orcado)} y2={y(orcado)} stroke="var(--color-danger)" strokeDasharray="6 4" strokeWidth={1.5} />
        <text x={largura - M.dir} y={y(orcado) - 6} textAnchor="end" fontSize="11" fill="var(--color-danger)">
          Limite orçado {formatBRL(orcado.toFixed(2))}
        </text>

        <polyline
          points={valores.map((v, i) => `${x(i)},${y(v)}`).join(" ")}
          fill="none"
          stroke="var(--color-primary)"
          strokeWidth={2}
        />
        {emAndamento && (
          <circle className="fim-realizado" cx={x(ultimo)} cy={y(valores[ultimo])} r={4} fill="var(--color-primary)" />
        )}

        {hover !== null && (
          <g pointerEvents="none">
            <line x1={x(hover)} x2={x(hover)} y1={M.topo} y2={M.topo + areaA} stroke="var(--color-text-muted)" strokeDasharray="2 3" />
            <circle cx={x(hover)} cy={y(valores[hover])} r={4} fill="var(--color-primary)" />
            <rect x={tipX} y={M.topo} width={180} height={84} rx={6} fill="var(--color-surface)" stroke="var(--color-border)" />
            <text x={tipX + 10} y={M.topo + 17} fontSize="12" fontWeight="600" fill="var(--color-text)">
              {formatData(dias[hover].data)}
            </text>
            <text x={tipX + 10} y={M.topo + 33} fontSize="11" fill="var(--color-text)">
              No dia: {formatBRL(diario(hover).toFixed(2))}
            </text>
            <text x={tipX + 10} y={M.topo + 47} fontSize="11" fill="var(--color-text)">
              Qtd mensagens: {formatNumero(msgsDia(hover))}
            </text>
            <text x={tipX + 10} y={M.topo + 61} fontSize="11" fill="var(--color-text-muted)">
              Acumulado: {formatBRL(valores[hover].toFixed(2))}
            </text>
            <text x={tipX + 10} y={M.topo + 75} fontSize="11" fill="var(--color-text-muted)">
              Envios acumulados: {formatNumero(msgs(hover))}
            </text>
          </g>
        )}

        <rect
          x={M.esq}
          y={M.topo}
          width={areaL}
          height={areaA}
          fill="transparent"
          onMouseMove={aoMover}
          onMouseLeave={() => setHover(null)}
        />
      </svg>
      <div className="orcamento-legenda">
        <span><i style={{ background: "var(--color-primary)" }} /> Gasto acumulado</span>
        <span><i className="tracejado" /> Limite orçado</span>
      </div>
    </div>
  );
}
