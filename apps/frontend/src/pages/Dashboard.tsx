import { useEffect, useState } from "react";
import { api, DashboardSummary } from "../api";
import EfetividadeCard from "../components/dashboard/EfetividadeCard";
import LeadsCard from "../components/dashboard/LeadsCard";
import MatrizCobrancaCard from "../components/dashboard/MatrizCobrancaCard";
import OrcamentoProgressaoCard from "../components/dashboard/OrcamentoProgressaoCard";
import FiltroPeriodo, { Periodo, periodoDe } from "../components/FiltroPeriodo";
import SortableTh from "../components/SortableTh";
import { formatDataHora } from "../format";
import { useOpcoesCobranca } from "../components/useOpcoesCobranca";
import { IconAlert, IconBolt, IconCheckCircle, IconInbox, IconPhone } from "../icons";
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
      {summary && <ResumoFila summary={summary} nomesFaixa={opcoes.regras?.faixas} />}

      <MatrizCobrancaCard opcoes={opcoes} />
      <EfetividadeCard opcoes={opcoes} />
      <LeadsCard opcoes={opcoes} />
      <OrcamentoProgressaoCard />
    </div>
  );
}

function ResumoFila({ summary, nomesFaixa }: { summary: DashboardSummary; nomesFaixa: string[] | undefined }) {
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
        <div className="stat">
          <div className="stat-icon tone-primary">
            <IconInbox />
          </div>
          <div>
            <div className="value">{summary.total_pendentes}</div>
            <div className="label">Pendentes na fila</div>
          </div>
        </div>
        <div className="stat">
          <div className="stat-icon tone-success">
            <IconCheckCircle />
          </div>
          <div>
            <div className="value">{summary.total_enviados}</div>
            <div className="label">Cobrados (enviados)</div>
          </div>
        </div>
        <div className="stat">
          <div className="stat-icon tone-danger">
            <IconAlert />
          </div>
          <div>
            <div className="value">{summary.total_erros}</div>
            <div className="label">Erros de envio</div>
          </div>
        </div>
        <div className="stat">
          <div className="stat-icon tone-warning">
            <IconPhone />
          </div>
          <div>
            <div className="value">{summary.total_telefones_invalidos}</div>
            <div className="label">Telefones inválidos</div>
          </div>
        </div>
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
                {porFaixaOrdenado.map((row, i) => (
                  <tr key={i}>
                    <td className="cell-strong">{String(row.faixa)}</td>
                    <td>{String(row.pending ?? 0)}</td>
                    <td>{String(row.sent ?? 0)}</td>
                    <td>{String(row.error ?? 0)}</td>
                  </tr>
                ))}
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
