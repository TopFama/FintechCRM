import { useEffect, useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import { api, ApiError, DashboardPorFaixa, DashboardSummary, PagosJanela } from "../api";
import EfetividadeCard from "../components/dashboard/EfetividadeCard";
import LeadsCard from "../components/dashboard/LeadsCard";
import MatrizCobrancaCard from "../components/dashboard/MatrizCobrancaCard";
import OrcamentoProgressaoCard from "../components/dashboard/OrcamentoProgressaoCard";
import FiltroPeriodo, { OpcaoPeriodo, Periodo, periodoDe } from "../components/FiltroPeriodo";
import DicaIndicador from "../components/DicaIndicador";
import SortableTh from "../components/SortableTh";
import { formatBRL, formatDecimal, formatHora, formatNumero, formatPercentual } from "../format";
import { useOpcoesCobranca } from "../components/useOpcoesCobranca";
import { useAtualizacaoAutomatica, useEhAtualizacaoAutomatica } from "../components/useAtualizacaoAutomatica";
import { IconAlert, IconBolt, IconCheckCircle, IconClock, IconInbox, IconPhone, IconRefresh } from "../icons";
import { ordemFaixaFn, ordenarPor, useSort } from "../sort";

export default function Dashboard() {
  const [summary, setSummary] = useState<DashboardSummary | null>(null);
  const [error, setError] = useState<string | null>(null);
  const opcoes = useOpcoesCobranca();
  const [opcaoPeriodo, setOpcaoPeriodo] = useState<OpcaoPeriodo | null>("hoje");
  const [periodo, setPeriodo] = useState<Periodo>(() => periodoDe("hoje"));
  // "Atualizar agora": recarrega todos os cards, inclusive os que não se atualizam sozinhos
  const [recarregar, setRecarregar] = useState(0);
  const [atualizadoEm, setAtualizadoEm] = useState<Date | null>(null);
  const ciclo = useAtualizacaoAutomatica(30_000);
  const tipoDeBusca = useEhAtualizacaoAutomatica(periodo, recarregar);

  // Aqui não há "sem filtro": período sem as duas datas é Personalizado incompleto
  const periodoIncompleto = !periodo.de || !periodo.ate;

  // Tela aberta de um dia para o outro: "Hoje", "7 dias" e "Este mês" andam junto com a data
  useEffect(() => {
    if (!opcaoPeriodo || opcaoPeriodo === "personalizado") return;
    const novo = periodoDe(opcaoPeriodo);
    if (novo.de !== periodo.de || novo.ate !== periodo.ate) setPeriodo(novo);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [ciclo]);

  useEffect(() => {
    const { auto, trocouFiltro } = tipoDeBusca();
    if (trocouFiltro) {
      setError(null);
      // Não deixa na tela os números de outro período enquanto as datas não vêm
      setSummary(null);
      setAtualizadoEm(null);
    }
    if (periodoIncompleto) return;
    let atual = true;
    api
      .dashboardSummary(periodo, auto)
      .then((s) => {
        if (!atual) return;
        setSummary(s);
        setError(null);
        setAtualizadoEm(new Date());
      })
      .catch((e) => atual && setError(e.message));
    return () => {
      atual = false;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [periodo, recarregar, ciclo]);

  return (
    <div>
      <div className="page-header">
        <div>
          <h2>Dashboard</h2>
          <div className="subtitle">Fila de envio, base de cobrança, efetividade e leads</div>
        </div>
        <div className="atualizacao-auto">
          <span className="text-muted">
            {atualizadoEm ? `Atualiza sozinho · atualizado às ${formatHora(atualizadoEm)}` : "Atualiza sozinho"}
          </span>
          <button type="button" className="secondary small" onClick={() => setRecarregar((n) => n + 1)}>
            <IconRefresh width={14} height={14} /> Atualizar agora
          </button>
        </div>
      </div>

      {error && (
        <div className="error-box">
          <IconAlert width={16} height={16} />
          <span>{error}</span>
        </div>
      )}
      <FiltroPeriodo
        opcoes={["hoje", "7dias", "mes", "personalizado"]}
        inicial="hoje"
        onChange={(p, opcao) => {
          setPeriodo(p);
          setOpcaoPeriodo(opcao);
        }}
      />
      {periodoIncompleto && <div className="empty-state"><p>Escolha a data mínima e a máxima.</p></div>}
      {!periodoIncompleto && !summary && !error && <div className="loading-state">Carregando resumo da fila...</div>}
      {summary && (
        <ResumoFila summary={summary} periodo={periodo} nomesFaixa={opcoes.regras?.faixas} recarregar={recarregar} />
      )}

      <MatrizCobrancaCard opcoes={opcoes} />
      <EfetividadeCard opcoes={opcoes} />
      <LeadsCard opcoes={opcoes} recarregar={recarregar} />
      <OrcamentoProgressaoCard recarregar={recarregar} />
    </div>
  );
}

// Link pro relatório do card com o mesmo período do Dashboard (a contagem bate)
function linkRelatorio(aba: string, periodo: Periodo, extra: Record<string, string> = {}) {
  const q = new URLSearchParams({ aba, ...(periodo.de ? { de: periodo.de } : {}), ...(periodo.ate ? { ate: periodo.ate } : {}), ...extra });
  return `/relatorios?${q.toString()}`;
}

function StatLink({
  to,
  valor,
  rotulo,
  ariaLabel,
  tom,
  icone,
  children,
}: {
  to: string;
  valor: React.ReactNode;
  rotulo: string;
  ariaLabel: string;
  tom: string;
  icone: React.ReactNode;
  children?: React.ReactNode;
}) {
  return (
    <Link to={to} className="stat stat-link" aria-label={ariaLabel}>
      <div className="stat-corpo">
        <div className="stat-topo">
          <div className="label">{rotulo}</div>
          <div className={`stat-icon ${tom}`}>{icone}</div>
        </div>
        <div className="stat-linha-valor">
          <div className="value">{valor}</div>
          <div className="stat-detalhes" aria-hidden="true">
            Ver detalhes →
          </div>
        </div>
        {children}
      </div>
    </Link>
  );
}

// Carregado à parte do resumo: depende do SETA e não pode segurar os outros cards.
// Não se atualiza sozinho (poupa o SETA): só ao abrir, trocar o período ou em "Atualizar agora".
function CardPagos7Dias({ periodo, recarregar }: { periodo: Periodo; recarregar: number }) {
  const [dados, setDados] = useState<PagosJanela | null>(null);
  const [erro, setErro] = useState<string | null>(null);
  const tipoDeBusca = useEhAtualizacaoAutomatica(periodo, 0);

  useEffect(() => {
    // "Atualizar agora" mantém o número atual até o novo chegar
    if (tipoDeBusca().trocouFiltro) setDados(null);
    setErro(null);
    let atual = true;
    api
      .pagos7Dias(periodo)
      .then((d) => atual && setDados(d))
      .catch((e) => {
        if (!atual) return;
        setDados(null);
        setErro(e instanceof ApiError && e.status === 503 ? "SETA indisponível" : e.message);
      });
    return () => {
      atual = false;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [periodo.de, periodo.ate, recarregar]);

  const rotulo = "Pagaram em até 7 dias";
  if (!dados) {
    return (
      <div className="stat" aria-busy={!erro}>
        <div className="stat-corpo">
          <div className="stat-topo">
            <div className="label">{rotulo}</div>
            <div className="stat-icon tone-success">
              <IconClock />
            </div>
          </div>
          <div className="stat-linha-valor">
            <div className="value">{erro ? "—" : "…"}</div>
          </div>
          {erro && <div className="stat-extra texto-erro">{erro}</div>}
        </div>
      </div>
    );
  }
  const pct = Number(dados.percentual).toLocaleString("pt-BR", { minimumFractionDigits: 1, maximumFractionDigits: 1 });
  return (
    <StatLink
      to={linkRelatorio("pagamentos", periodo, { dias_janela: "7" })}
      valor={formatNumero(dados.qtd_pagaram)}
      rotulo={rotulo}
      ariaLabel={`Ver ${formatNumero(dados.qtd_pagaram)} clientes que pagaram em até 7 dias`}
      tom="tone-success"
      icone={<IconClock />}
    >
      <div className="stat-extra">
        {pct}% dos cobrados · {formatBRL(dados.valor_pago)}
      </div>
      {dados.qtd_em_maturacao > 0 && (
        <div className="stat-extra stat-aviso">
          {formatNumero(dados.qtd_em_maturacao)} ainda dentro da janela de 7 dias
        </div>
      )}
    </StatLink>
  );
}

function ResumoFila({
  summary,
  periodo,
  nomesFaixa,
  recarregar,
}: {
  summary: DashboardSummary;
  periodo: Periodo;
  nomesFaixa: string[] | undefined;
  recarregar: number;
}) {
  const navigate = useNavigate();
  const ordemFaixa = ordemFaixaFn(nomesFaixa);
  const linhas = linhasPorFaixa(summary.por_faixa);
  const total = totalPorFaixa(linhas);
  const porFaixaSort = useSort<"faixa" | ColunaPorFaixa>("faixa");
  const porFaixaOrdenado = ordenarPor(
    linhas,
    porFaixaSort.sortKey === "faixa"
      ? (row) => ordemFaixa(row.faixa)
      : porFaixaSort.sortKey
      ? (row) => row[porFaixaSort.sortKey as ColunaPorFaixa]
      : null,
    porFaixaSort.sortDir
  );
  const th = (chave: "faixa" | ColunaPorFaixa, rotulo: string, dica?: Dica) => (
    <SortableTh
      key={chave}
      active={porFaixaSort.sortKey === chave}
      dir={porFaixaSort.sortDir}
      onSort={() => porFaixaSort.toggleSort(chave)}
    >
      {rotulo}
      {dica && <DicaIndicador titulo={rotulo} texto={dica.texto} formula={dica.formula} />}
    </SortableTh>
  );

  return (
    <>
      <div className="stat-grid">
        <StatLink
          to={linkRelatorio("pendentes", periodo)}
          valor={formatNumero(summary.total_pendentes)}
          rotulo="Pendentes na fila"
          ariaLabel={`Ver ${formatNumero(summary.total_pendentes)} pendentes na fila, ${formatNumero(summary.total_pausados)} pausados`}
          tom="tone-primary"
          icone={<IconInbox />}
        >
          <div className={`stat-extra${summary.total_pausados > 0 ? " stat-aviso" : ""}`}>
            {formatNumero(summary.total_pendentes)} pendentes · {formatNumero(summary.total_pausados)} pausados
          </div>
        </StatLink>
        <StatLink
          to={linkRelatorio("envios", periodo)}
          valor={formatNumero(summary.total_enviados)}
          rotulo="Cobranças"
          ariaLabel={`Ver ${formatNumero(summary.total_enviados)} cobranças enviadas`}
          tom="tone-success"
          icone={<IconCheckCircle />}
        />
        <StatLink
          to={linkRelatorio("erros", periodo)}
          valor={formatNumero(summary.total_erros)}
          rotulo="Erros de envio"
          ariaLabel={`Ver ${formatNumero(summary.total_erros)} erros de envio`}
          tom="tone-danger"
          icone={<IconAlert />}
        />
        <StatLink
          to={linkRelatorio("invalidos", periodo)}
          valor={formatNumero(summary.total_telefones_invalidos)}
          rotulo="Telefones inválidos"
          ariaLabel={`Ver ${formatNumero(summary.total_telefones_invalidos)} telefones inválidos`}
          tom="tone-warning"
          icone={<IconPhone />}
        />
        <CardPagos7Dias periodo={periodo} recarregar={recarregar} />
      </div>

      <div className="card">
        <div className="card-header">
          <h3>Por faixa</h3>
        </div>
        {summary.por_faixa.length === 0 ? (
          <div className="empty-state">
            <IconBolt width={28} height={28} />
            <div className="title">Nenhuma faixa com movimento ainda</div>
            <p>Nenhum cliente entrou na fila de nenhuma faixa neste período.</p>
          </div>
        ) : (
          <div className="table-wrap">
            <table className="tabela-por-faixa">
              <thead>
                <tr>
                  {th("faixa", "Faixa")}
                  {th("pending", "Pendente")}
                  {th("error", "Erro")}
                  {th("sent", "Enviado")}
                  {th("clientes_cobrados", "Clientes cobrados", DICAS.clientes_cobrados)}
                  {th("frequencia", "Frequência", DICAS.frequencia)}
                  {th("pagaram", "Pagaram após cobrança")}
                  {th("conversao", "%\u00a0Conv.", DICAS.conversao)}
                  {th("representatividade", "%\u00a0Rep.", DICAS.representatividade)}
                  {th("valor_pago", "Valor pago")}
                </tr>
              </thead>
              <tbody>
                {porFaixaOrdenado.map((row) => {
                  const link = (aba: string) => linkRelatorio(aba, periodo, { faixa_id: row.faixa_id });
                  const celula = (aba: string, valor: number, rotulo: string) => (
                    <td>
                      <Link
                        to={link(aba)}
                        className="link-celula"
                        aria-label={`Ver ${formatNumero(valor)} ${rotulo} da faixa ${row.faixa}`}
                        onClick={(e) => e.stopPropagation()}
                      >
                        {formatNumero(valor)}
                      </Link>
                    </td>
                  );
                  return (
                    // A linha inteira abre os envios da faixa; cada número abre o próprio relatório
                    <tr key={row.faixa} className="linha-clicavel" onClick={() => navigate(link("envios"))}>
                      <td className="cell-strong">
                        <Link to={link("envios")} className="link-celula" onClick={(e) => e.stopPropagation()}>
                          {row.faixa}
                        </Link>
                      </td>
                      {celula("pendentes", row.pending, "pendentes")}
                      {celula("erros", row.error, "erros")}
                      {celula("envios", row.sent, "enviados")}
                      <td>{formatNumero(row.clientes_cobrados)}</td>
                      <td>{formatDecimal(row.frequencia)}</td>
                      {celula("pagamentos", row.pagaram, "clientes que pagaram")}
                      <td>{formatPercentual(row.conversao)}</td>
                      <td>{formatPercentual(row.representatividade)}</td>
                      <td>{formatBRL(row.valor_pago)}</td>
                    </tr>
                  );
                })}
              </tbody>
              <tfoot>
                <tr className="linha-total">
                  <td className="cell-strong">Total</td>
                  <td>{formatNumero(total.pending)}</td>
                  <td>{formatNumero(total.error)}</td>
                  <td>{formatNumero(total.sent)}</td>
                  <td>{formatNumero(total.clientes_cobrados)}</td>
                  <td>{formatDecimal(total.frequencia)}</td>
                  <td>{formatNumero(total.pagaram)}</td>
                  <td>{formatPercentual(total.conversao)}</td>
                  {/* Sempre 100%: não traz nada */}
                  <td />
                  <td>{formatBRL(total.valor_pago)}</td>
                </tr>
              </tfoot>
            </table>
          </div>
        )}
      </div>

    </>
  );
}

type Dica = { texto: string; formula: string };

const DICAS: Record<"clientes_cobrados" | "frequencia" | "conversao" | "representatividade", Dica> = {
  clientes_cobrados: {
    texto:
      "Clientes distintos que receberam cobrança nesta faixa no período. No total, soma das faixas: quem foi cobrado em mais de uma faixa conta em cada uma.",
    formula: "Contagem de clientes distintos cobrados na faixa",
  },
  frequencia: {
    texto: "Média de mensagens enviadas no período por cliente cobrado que recebeu mensagem.",
    formula: "Mensagens enviadas no período aos clientes cobrados ÷ Clientes cobrados que receberam mensagem",
  },
  conversao: {
    texto: "Dos clientes cobrados na faixa, quantos pagaram depois da cobrança.",
    formula: "Pagaram após cobrança ÷ Clientes cobrados × 100",
  },
  representatividade: {
    texto: "Quanto esta faixa representa do total de clientes que pagaram após cobrança.",
    formula: "Pagaram após cobrança da faixa ÷ Σ Pagaram após cobrança de todas as faixas × 100",
  },
};

// Colunas numéricas que vêm do backend e somam na linha de total
const CAMPOS_SOMAVEIS = [
  "pending",
  "error",
  "sent",
  "clientes_cobrados",
  "enviados_cobrados",
  "clientes_com_envio",
  "pagaram",
  "valor_pago",
] as const;
type CampoSomavel = (typeof CAMPOS_SOMAVEIS)[number];

type LinhaPorFaixa = Pick<DashboardPorFaixa, "faixa" | "faixa_id"> &
  Record<CampoSomavel, number> & {
    frequencia: number | null;
    conversao: number | null;
    representatividade: number | null;
  };
type ColunaPorFaixa = Exclude<keyof LinhaPorFaixa, "faixa" | "faixa_id" | "enviados_cobrados" | "clientes_com_envio">;

// Divisão por zero (faixa sem cliente cobrado) vira "—", não 0
const razao = (a: number, b: number) => (b ? a / b : null);

function linhasPorFaixa(porFaixa: DashboardPorFaixa[]): LinhaPorFaixa[] {
  const base = porFaixa.map((row) => ({
    faixa: row.faixa,
    faixa_id: row.faixa_id,
    ...(Object.fromEntries(CAMPOS_SOMAVEIS.map((c) => [c, Number(row[c] ?? 0)])) as Record<CampoSomavel, number>),
  }));
  // % Rep. sobre a soma das faixas (não clientes distintos), para fechar 100%
  const somaPagaram = base.reduce((s, r) => s + r.pagaram, 0);
  return base.map((r) => ({
    ...r,
    // Frequência só entre quem recebeu mensagem; % Conv. sobre todos os cobrados
    frequencia: razao(r.enviados_cobrados, r.clientes_com_envio),
    conversao: razao(r.pagaram, r.clientes_cobrados),
    representatividade: razao(r.pagaram, somaPagaram),
  }));
}

function totalPorFaixa(linhas: LinhaPorFaixa[]) {
  const t = Object.fromEntries(
    CAMPOS_SOMAVEIS.map((c) => [c, linhas.reduce((s, r) => s + r[c], 0)])
  ) as Record<CampoSomavel, number>;
  return { ...t, frequencia: razao(t.enviados_cobrados, t.clientes_com_envio), conversao: razao(t.pagaram, t.clientes_cobrados) };
}

