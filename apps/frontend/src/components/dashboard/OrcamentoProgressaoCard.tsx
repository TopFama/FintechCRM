import { useEffect, useState } from "react";
import { useAtualizacaoAutomatica, useEhAtualizacaoAutomatica } from "../useAtualizacaoAutomatica";
import { api, OrcamentoProgressao } from "../../api";
import { formatBRL, formatData, hojeBR } from "../../format";
import { IconAlert, IconDownload } from "../../icons";
import { ordenarPor, useSort } from "../../sort";
import SortableTh from "../SortableTh";
import TabelaAjustavel from "../TabelaAjustavel";

type ColunaNumero = "numero" | "gasto_brl" | "qtd_mensagens";

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
                <div className="value">{formatBRL(dados.valor_gasto_brl!)}</div>
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
          <GraficoGasto dados={dados} />
          {dados.gasto_por_numero.length > 0 && (
            <TabelaAjustavel id="orcamento-por-numero" rotulo="Gasto por número" style={{ marginTop: 16 }}>
              <table>
                <thead>
                  <tr>
                    {(
                      [
                        ["numero", "Número"],
                        ["gasto_brl", "Gasto no período"],
                        ["qtd_mensagens", "Qtd mensagens"],
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
                    ordenacao.sortKey === "gasto_brl"
                      ? (g) => Number(g.gasto_brl)
                      : ordenacao.sortKey
                      ? (g) => g[ordenacao.sortKey as "numero" | "qtd_mensagens"]
                      : null,
                    ordenacao.sortDir
                  ).map((g) => (
                    <tr key={g.numero}>
                      <td className="cell-strong">{g.numero}</td>
                      <td>{formatBRL(g.gasto_brl)}</td>
                      <td>{g.qtd_mensagens.toLocaleString("pt-BR")}</td>
                    </tr>
                  ))}
                  <tr className="linha-total">
                    <td className="cell-strong">Total</td>
                    <td>{formatBRL(dados.gasto_por_numero.reduce((t, g) => t + Number(g.gasto_brl), 0))}</td>
                    <td>{dados.gasto_por_numero.reduce((t, g) => t + g.qtd_mensagens, 0).toLocaleString("pt-BR")}</td>
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

const LARGURA = 720;
const ALTURA = 260;
const M = { topo: 16, dir: 16, base: 44, esq: 104 };

function dataCurta(iso: string): string {
  const [, mes, dia] = iso.split("-");
  return `${dia}/${mes}`;
}

// Linha do gasto acumulado dia a dia + linha tracejada do limite orçado,
// com eixos (R$ no Y, datas no X) e tooltip do dia sob o mouse.
function GraficoGasto({ dados }: { dados: OrcamentoProgressao }) {
  const [hover, setHover] = useState<number | null>(null);
  const dias = dados.dias;
  const orcado = Number(dados.valor_orcado);
  const valores = dias.map((d) => Number(d.gasto_acumulado_brl));
  const maximo = Math.max(orcado, ...valores, 1) * 1.1;
  const areaL = LARGURA - M.esq - M.dir;
  const areaA = ALTURA - M.topo - M.base;
  const x = (i: number) => M.esq + (dias.length <= 1 ? areaL / 2 : (i / (dias.length - 1)) * areaL);
  const y = (v: number) => M.topo + areaA - (v / maximo) * areaA;

  const ticksY = [0, 0.25, 0.5, 0.75, 1].map((f) => f * maximo);
  const passoX = Math.max(1, Math.ceil(dias.length / 8));
  const diario = (i: number) => valores[i] - (i > 0 ? valores[i - 1] : 0);

  function aoMover(e: React.MouseEvent<SVGRectElement>) {
    const caixa = e.currentTarget.getBoundingClientRect();
    const px = ((e.clientX - caixa.left) / caixa.width) * areaL;
    const i = dias.length <= 1 ? 0 : Math.round((px / areaL) * (dias.length - 1));
    setHover(Math.min(Math.max(i, 0), dias.length - 1));
  }

  const tipX = hover !== null ? Math.min(x(hover) + 10, LARGURA - M.dir - 170) : 0;

  return (
    <div className="orcamento-grafico">
      <svg viewBox={`0 0 ${LARGURA} ${ALTURA}`} width="100%" role="img" aria-label="Gasto acumulado por dia vs. orçado">
        {ticksY.map((v) => (
          <g key={v}>
            <line x1={M.esq} x2={LARGURA - M.dir} y1={y(v)} y2={y(v)} stroke="var(--color-border)" />
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

        <line x1={M.esq} x2={LARGURA - M.dir} y1={y(orcado)} y2={y(orcado)} stroke="var(--color-danger)" strokeDasharray="6 4" strokeWidth={1.5} />
        <text x={LARGURA - M.dir} y={y(orcado) - 6} textAnchor="end" fontSize="11" fill="var(--color-danger)">
          Limite orçado {formatBRL(orcado.toFixed(2))}
        </text>

        <polyline
          points={dias.map((_, i) => `${x(i)},${y(valores[i])}`).join(" ")}
          fill="none"
          stroke="var(--color-primary)"
          strokeWidth={2}
        />

        {hover !== null && (
          <g pointerEvents="none">
            <line x1={x(hover)} x2={x(hover)} y1={M.topo} y2={M.topo + areaA} stroke="var(--color-text-muted)" strokeDasharray="2 3" />
            <circle cx={x(hover)} cy={y(valores[hover])} r={4} fill="var(--color-primary)" />
            <rect x={tipX} y={M.topo} width={160} height={54} rx={6} fill="var(--color-surface)" stroke="var(--color-border)" />
            <text x={tipX + 10} y={M.topo + 17} fontSize="12" fontWeight="600" fill="var(--color-text)">
              {formatData(dias[hover].data)}
            </text>
            <text x={tipX + 10} y={M.topo + 33} fontSize="11" fill="var(--color-text)">
              No dia: {formatBRL(diario(hover).toFixed(2))}
            </text>
            <text x={tipX + 10} y={M.topo + 47} fontSize="11" fill="var(--color-text-muted)">
              Acumulado: {formatBRL(valores[hover].toFixed(2))}
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
