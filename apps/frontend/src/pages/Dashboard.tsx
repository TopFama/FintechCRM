import { useEffect, useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import { api, ApiError, DashboardSummary, PagosJanela } from "../api";
import EfetividadeCard from "../components/dashboard/EfetividadeCard";
import LeadsCard from "../components/dashboard/LeadsCard";
import MatrizCobrancaCard from "../components/dashboard/MatrizCobrancaCard";
import OrcamentoProgressaoCard from "../components/dashboard/OrcamentoProgressaoCard";
import FiltroPeriodo, { Periodo, periodoDe } from "../components/FiltroPeriodo";
import SortableTh from "../components/SortableTh";
import { formatBRL, formatDataHora } from "../format";
import { useOpcoesCobranca } from "../components/useOpcoesCobranca";
import { IconAlert, IconBolt, IconCheckCircle, IconClock, IconInbox, IconPhone } from "../icons";
import { ordemFaixaFn, ordenarPor, useSort } from "../sort";

export default function Dashboard() {
  const [summary, setSummary] = useState<DashboardSummary | null>(null);
  const [error, setError] = useState<string | null>(null);
  const opcoes = useOpcoesCobranca();
  const [periodo, setPeriodo] = useState<Periodo>(() => periodoDe("hoje"));

  // Aqui não há "sem filtro": período sem as duas datas é Personalizado incompleto
  const periodoIncompleto = !periodo.de || !periodo.ate;

  useEffect(() => {
    setError(null);
    // Não deixa na tela os números de outro período enquanto as datas não vêm
    setSummary(null);
    if (periodoIncompleto) return;
    let atual = true;
    api
      .dashboardSummary(periodo)
      .then((s) => atual && setSummary(s))
      .catch((e) => atual && setError(e.message));
    return () => {
      atual = false;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [periodo]);

  return (
    <div>
      <div className="page-header">
        <div>
          <h2>Dashboard</h2>
          <div className="subtitle">Fila de envio, base de cobrança, efetividade e leads</div>
        </div>
      </div>

      {error && (
        <div className="error-box">
          <IconAlert width={16} height={16} />
          <span>{error}</span>
        </div>
      )}
      <FiltroPeriodo opcoes={["hoje", "7dias", "mes", "personalizado"]} inicial="hoje" onChange={setPeriodo} />
      {periodoIncompleto && <div className="empty-state"><p>Escolha a data mínima e a máxima.</p></div>}
      {!periodoIncompleto && !summary && !error && <div className="loading-state">Carregando resumo da fila...</div>}
      {summary && <ResumoFila summary={summary} periodo={periodo} nomesFaixa={opcoes.regras?.faixas} />}

      <MatrizCobrancaCard opcoes={opcoes} />
      <EfetividadeCard opcoes={opcoes} />
      <LeadsCard opcoes={opcoes} />
      <OrcamentoProgressaoCard />
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
      <div className={`stat-icon ${tom}`}>{icone}</div>
      <div className="stat-corpo">
        <div className="value">{valor}</div>
        <div className="label">{rotulo}</div>
        {children}
        <div className="stat-detalhes" aria-hidden="true">
          Ver detalhes →
        </div>
      </div>
    </Link>
  );
}

// Carregado à parte do resumo: depende do SETA e não pode segurar os outros cards
function CardPagos7Dias({ periodo }: { periodo: Periodo }) {
  const [dados, setDados] = useState<PagosJanela | null>(null);
  const [erro, setErro] = useState<string | null>(null);

  useEffect(() => {
    setDados(null);
    setErro(null);
    let atual = true;
    api
      .pagos7Dias(periodo)
      .then((d) => atual && setDados(d))
      .catch((e) => atual && setErro(e instanceof ApiError && e.status === 503 ? "SETA indisponível" : e.message));
    return () => {
      atual = false;
    };
  }, [periodo.de, periodo.ate]);

  const rotulo = "Pagaram em até 7 dias";
  if (!dados) {
    return (
      <div className="stat" aria-busy={!erro}>
        <div className="stat-icon tone-success">
          <IconClock />
        </div>
        <div className="stat-corpo">
          <div className="value">{erro ? "—" : "…"}</div>
          <div className="label">{rotulo}</div>
          {erro && <div className="stat-extra texto-erro">{erro}</div>}
        </div>
      </div>
    );
  }
  const pct = Number(dados.percentual).toLocaleString("pt-BR", { minimumFractionDigits: 1, maximumFractionDigits: 1 });
  return (
    <StatLink
      to={linkRelatorio("pagamentos", periodo, { dias_janela: "7" })}
      valor={dados.qtd_pagaram}
      rotulo={rotulo}
      ariaLabel={`Ver ${dados.qtd_pagaram} clientes que pagaram em até 7 dias`}
      tom="tone-success"
      icone={<IconClock />}
    >
      <div className="stat-extra">
        {pct}% dos cobrados · {formatBRL(dados.valor_pago)}
      </div>
      {dados.qtd_em_maturacao > 0 && (
        <div className="stat-extra stat-aviso">
          {dados.qtd_em_maturacao} ainda dentro da janela de 7 dias
        </div>
      )}
    </StatLink>
  );
}

function ResumoFila({
  summary,
  periodo,
  nomesFaixa,
}: {
  summary: DashboardSummary;
  periodo: Periodo;
  nomesFaixa: string[] | undefined;
}) {
  const navigate = useNavigate();
  const ordemFaixa = ordemFaixaFn(nomesFaixa);
  const porFaixaSort = useSort<"faixa" | "pending" | "sent" | "error">("faixa");
  const porFaixaOrdenado = ordenarPor(
    summary.por_faixa,
    porFaixaSort.sortKey === "faixa"
      ? (row) => ordemFaixa(String(row.faixa))
      : porFaixaSort.sortKey
      ? (row) => Number(row[porFaixaSort.sortKey as "pending" | "sent" | "error"] ?? 0)
      : null,
    porFaixaSort.sortDir
  );

  const errosSort = useSort<"quando" | "mensagem">();
  const errosOrdenado = ordenarPor(
    summary.erros_recentes,
    errosSort.sortKey === "quando"
      ? (row) => String(row.created_at)
      : errosSort.sortKey === "mensagem"
      ? (row) => String(row.message)
      : null,
    errosSort.sortDir
  );

  return (
    <>
      <div className="stat-grid">
        <StatLink
          to={linkRelatorio("pendentes", periodo)}
          valor={summary.total_pendentes}
          rotulo="Pendentes na fila"
          ariaLabel={`Ver ${summary.total_pendentes} pendentes na fila`}
          tom="tone-primary"
          icone={<IconInbox />}
        />
        <StatLink
          to={linkRelatorio("envios", periodo)}
          valor={summary.total_enviados}
          rotulo="Cobrados (enviados)"
          ariaLabel={`Ver ${summary.total_enviados} cobranças enviadas`}
          tom="tone-success"
          icone={<IconCheckCircle />}
        />
        <StatLink
          to={linkRelatorio("erros", periodo)}
          valor={summary.total_erros}
          rotulo="Erros de envio"
          ariaLabel={`Ver ${summary.total_erros} erros de envio`}
          tom="tone-danger"
          icone={<IconAlert />}
        />
        <StatLink
          to={linkRelatorio("invalidos", periodo)}
          valor={summary.total_telefones_invalidos}
          rotulo="Telefones inválidos"
          ariaLabel={`Ver ${summary.total_telefones_invalidos} telefones inválidos`}
          tom="tone-warning"
          icone={<IconPhone />}
        />
        <CardPagos7Dias periodo={periodo} />
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
            <table>
              <thead>
                <tr>
                  <SortableTh
                    active={porFaixaSort.sortKey === "faixa"}
                    dir={porFaixaSort.sortDir}
                    onSort={() => porFaixaSort.toggleSort("faixa")}
                  >
                    Faixa
                  </SortableTh>
                  <SortableTh
                    active={porFaixaSort.sortKey === "pending"}
                    dir={porFaixaSort.sortDir}
                    onSort={() => porFaixaSort.toggleSort("pending")}
                  >
                    Pendente
                  </SortableTh>
                  <SortableTh
                    active={porFaixaSort.sortKey === "sent"}
                    dir={porFaixaSort.sortDir}
                    onSort={() => porFaixaSort.toggleSort("sent")}
                  >
                    Enviado
                  </SortableTh>
                  <SortableTh
                    active={porFaixaSort.sortKey === "error"}
                    dir={porFaixaSort.sortDir}
                    onSort={() => porFaixaSort.toggleSort("error")}
                  >
                    Erro
                  </SortableTh>
                </tr>
              </thead>
              <tbody>
                {porFaixaOrdenado.map((row) => {
                  const faixaId = String(row.faixa_id);
                  const link = (aba: string) => linkRelatorio(aba, periodo, { faixa_id: faixaId });
                  const celula = (aba: string, valor: unknown, rotulo: string) => (
                    <td>
                      <Link
                        to={link(aba)}
                        className="link-celula"
                        aria-label={`Ver ${String(valor ?? 0)} ${rotulo} da faixa ${String(row.faixa)}`}
                        onClick={(e) => e.stopPropagation()}
                      >
                        {String(valor ?? 0)}
                      </Link>
                    </td>
                  );
                  return (
                    // A linha inteira abre os envios da faixa; cada número abre o próprio relatório
                    <tr key={faixaId} className="linha-clicavel" onClick={() => navigate(link("envios"))}>
                      <td className="cell-strong">
                        <Link to={link("envios")} className="link-celula" onClick={(e) => e.stopPropagation()}>
                          {String(row.faixa)}
                        </Link>
                      </td>
                      {celula("pendentes", row.pending, "pendentes")}
                      {celula("envios", row.sent, "enviados")}
                      {celula("erros", row.error, "erros")}
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        )}
      </div>

      <div className="card">
        <div className="card-header">
          <h3>Erros recentes</h3>
        </div>
        {summary.erros_recentes.length === 0 ? (
          <div className="empty-state">
            <IconCheckCircle width={28} height={28} />
            <div className="title">Sem erros no período</div>
            <p>Tudo certo por aqui.</p>
          </div>
        ) : (
          <div className="table-wrap">
            <table>
              <thead>
                <tr>
                  <SortableTh
                    active={errosSort.sortKey === "quando"}
                    dir={errosSort.sortDir}
                    onSort={() => errosSort.toggleSort("quando")}
                  >
                    Quando
                  </SortableTh>
                  <th scope="col">Faixa</th>
                  <th scope="col">Cliente</th>
                  <SortableTh
                    active={errosSort.sortKey === "mensagem"}
                    dir={errosSort.sortDir}
                    onSort={() => errosSort.toggleSort("mensagem")}
                  >
                    Mensagem
                  </SortableTh>
                </tr>
              </thead>
              <tbody>
                {errosOrdenado.map((row, i) => (
                  <tr key={i}>
                    <td className="text-muted">{formatDataHora(String(row.created_at))}</td>
                    <td>{String(row.faixa ?? "—")}</td>
                    <td>{String(row.cliente ?? "—")}</td>
                    <td>{String(row.message)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>
    </>
  );
}
