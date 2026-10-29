import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { api, ApiError, DashboardSummary, PagosJanela, foiCancelada } from "../api";
import AvisosCategoria from "../components/AvisosCategoria";
import EfetividadeCard from "../components/dashboard/EfetividadeCard";
import LeadsCard from "../components/dashboard/LeadsCard";
import MatrizCobrancaCard from "../components/dashboard/MatrizCobrancaCard";
import OrcamentoProgressaoCard from "../components/dashboard/OrcamentoProgressaoCard";
import { linkRelatorio } from "../components/dashboard/linkRelatorio";
import PainelMensagensCard from "../components/dashboard/PainelMensagensCard";
import FiltroPeriodo, { OpcaoPeriodo, Periodo, periodoDe } from "../components/FiltroPeriodo";
import { formatBRL, formatHora, formatNumero } from "../format";
import { useOpcoesCobranca } from "../components/useOpcoesCobranca";
import { useAtualizacaoAutomatica, useEhAtualizacaoAutomatica } from "../components/useAtualizacaoAutomatica";
import { usePainelTempoReal } from "../components/usePainelTempoReal";
import { IconAlert, IconCheckCircle, IconClock, IconInbox, IconPhone, IconRefresh } from "../icons";

export default function Dashboard() {
  const [summary, setSummary] = useState<DashboardSummary | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [avisosCategoria, setAvisosCategoria] = useState<string[]>([]);
  const opcoes = useOpcoesCobranca();
  const [opcaoPeriodo, setOpcaoPeriodo] = useState<OpcaoPeriodo | null>("hoje");
  const [periodo, setPeriodo] = useState<Periodo>(() => periodoDe("hoje"));
  // "Atualizar agora": recarrega todos os cards, inclusive os que não se atualizam sozinhos
  const [recarregar, setRecarregar] = useState(0);
  const [atualizadoEm, setAtualizadoEm] = useState<Date | null>(null);
  // Desabilita "Atualizar agora" enquanto a consulta manual não volta (clique repetido)
  const [atualizando, setAtualizando] = useState(false);
  const ciclo = useAtualizacaoAutomatica(30_000);
  const tipoDeBusca = useEhAtualizacaoAutomatica(periodo, recarregar);
  // Cards da fila na hora em que mudam; o polling segue para o resto e como reserva
  const tempoReal = usePainelTempoReal(periodo.de, periodo.ate);

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
    // Período trocado ou tela fechada cancela a consulta em andamento
    const controle = new AbortController();
    setAtualizando(!auto);
    api
      .dashboardSummary(periodo, auto, controle.signal)
      .then((s) => {
        setSummary(s);
        setError(null);
        setAtualizadoEm(new Date());
      })
      .catch((e) => !foiCancelada(e) && setError(e.message))
      .finally(() => !controle.signal.aborted && setAtualizando(false));
    return () => controle.abort();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [periodo, recarregar, ciclo]);

  // Filas que sobem sozinhas usam template recategorizado pela Meta sem Ciente
  useEffect(() => {
    api.avisosCategoria().then(setAvisosCategoria).catch(() => undefined);
  }, [recarregar]);

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
          <button type="button" className="secondary small" onClick={() => setRecarregar((n) => n + 1)} disabled={atualizando}>
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
      <AvisosCategoria avisos={avisosCategoria} />
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
        <ResumoFila summary={tempoReal ? { ...summary, ...tempoReal } : summary} periodo={periodo} recarregar={recarregar} />
      )}

      <PainelMensagensCard recarregar={recarregar} />
      <MatrizCobrancaCard opcoes={opcoes} />
      <EfetividadeCard opcoes={opcoes} />
      <LeadsCard opcoes={opcoes} recarregar={recarregar} />
      <OrcamentoProgressaoCard recarregar={recarregar} />
    </div>
  );
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

function rotuloJanela(dias: number | null): string {
  if (dias === null) return "Pagaram após a cobrança";
  return `Pagaram em até ${dias} ${dias === 1 ? "dia" : "dias"}`;
}

// Carregado à parte do resumo: depende do SETA e não pode segurar os outros cards.
// Não se atualiza sozinho (poupa o SETA): só ao abrir, trocar o período ou em "Atualizar agora".
function CardJanelaPagamento({ periodo, recarregar }: { periodo: Periodo; recarregar: number }) {
  const [dados, setDados] = useState<PagosJanela | null>(null);
  const [erro, setErro] = useState<string | null>(null);
  const tipoDeBusca = useEhAtualizacaoAutomatica(periodo, 0);

  useEffect(() => {
    // "Atualizar agora" mantém o número atual até o novo chegar
    if (tipoDeBusca().trocouFiltro) setDados(null);
    setErro(null);
    const controle = new AbortController();
    api
      .janelaPagamento(periodo, controle.signal)
      .then(setDados)
      .catch((e) => {
        if (foiCancelada(e)) return;
        setDados(null);
        setErro(e instanceof ApiError && e.codigo === "seta_indisponivel" ? "SETA indisponível" : e.message);
      });
    return () => controle.abort();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [periodo.de, periodo.ate, recarregar]);

  // a janela vem da config de Indicadores, então só se sabe com a resposta
  const rotulo = dados ? rotuloJanela(dados.dias_janela) : "Pagaram";
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
      to={linkRelatorio("pagamentos", periodo, dados.dias_janela === null ? {} : { dias_janela: String(dados.dias_janela) })}
      valor={formatNumero(dados.qtd_pagaram)}
      rotulo={rotulo}
      ariaLabel={`Ver ${formatNumero(dados.qtd_pagaram)} clientes: ${rotulo}`}
      tom="tone-success"
      icone={<IconClock />}
    >
      <div className="stat-extra">
        {pct}% dos cobrados · {formatBRL(dados.valor_pago)}
      </div>
      {dados.qtd_em_maturacao > 0 && (
        <div className="stat-extra stat-aviso">
          {formatNumero(dados.qtd_em_maturacao)} ainda dentro da janela de {dados.dias_janela} {dados.dias_janela === 1 ? "dia" : "dias"}
        </div>
      )}
    </StatLink>
  );
}

function ResumoFila({ summary, periodo, recarregar }: { summary: DashboardSummary; periodo: Periodo; recarregar: number }) {
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
        <CardJanelaPagamento periodo={periodo} recarregar={recarregar} />
      </div>
    </>
  );
}
