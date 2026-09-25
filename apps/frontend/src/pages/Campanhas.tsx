import { useEffect, useState } from "react";
import { Link, useSearchParams } from "react-router-dom";
import { api, Campanha } from "../api";
import RemarketingCard from "../components/config/RemarketingCard";
import { formatData, formatDataHora } from "../format";
import { IconAlert, IconArrowRight, IconMegaphone, IconPause, IconPlay, IconPlus, IconStop } from "../icons";

type Aba = "campanhas" | "remarketing";

export function periodoCampanha(c: Pick<Campanha, "ativa" | "data_inicio" | "data_fim">): string {
  if (!c.ativa) return "Envio manual";
  if (!c.data_inicio) return "Envio automático sem data";
  if (c.data_fim === c.data_inicio) return `Envio automático em ${formatData(c.data_inicio)}`;
  return `Envio automático de ${formatData(c.data_inicio)} ${c.data_fim ? `a ${formatData(c.data_fim)}` : "em diante"}`;
}

/** Situação da campanha para o selo: parada, pausada, automática ou manual. */
export function situacaoCampanha(c: Pick<Campanha, "ativa" | "pausa" | "parada_em">): {
  rotulo: string;
  classe: string;
} {
  if (c.parada_em && !c.ativa) return { rotulo: "Parada", classe: "stopped" };
  if (c.pausa) return { rotulo: "Pausada", classe: "paused" };
  if (c.ativa) return { rotulo: "Automática", classe: "on" };
  return { rotulo: "Manual", classe: "off" };
}

/** Pausar, retomar e parar, na lista e dentro da campanha. Devolve a campanha atualizada. */
export function AcoesCampanha({
  campanha,
  onAlterada,
  onErro,
}: {
  campanha: Campanha;
  onAlterada: (c: Campanha, mensagem: string) => void;
  onErro: (mensagem: string) => void;
}) {
  const [ocupado, setOcupado] = useState(false);

  async function rodar(
    acao: () => Promise<Campanha & { cancelados?: number }>,
    mensagem: (c: Campanha & { cancelados?: number }) => string,
  ) {
    setOcupado(true);
    try {
      const c = await acao();
      onAlterada(c, mensagem(c));
    } catch (e) {
      onErro(e instanceof Error ? e.message : "Erro ao alterar a campanha");
    } finally {
      setOcupado(false);
    }
  }

  function pausar() {
    const motivo = window.prompt(
      `Pausar a campanha "${campanha.nome}"? Os pendentes ficam retidos e o envio automático para até você retomar. Motivo (opcional):`,
      "",
    );
    if (motivo === null) return;
    rodar(
      () => api.pausarCampanha(campanha.id, { motivo }),
      () => "Campanha pausada.",
    );
  }

  function parar() {
    if (
      !window.confirm(
        `Parar a campanha "${campanha.nome}"? Os ${campanha.pendentes} pendente(s) são cancelados (ficam no histórico) e o envio automático é desligado.`,
      )
    )
      return;
    rodar(
      () => api.pararCampanha(campanha.id),
      (c) => `Campanha parada: ${c.cancelados ?? 0} pendente(s) cancelado(s).`,
    );
  }

  // Sem envio automático e sem pendentes não há o que pausar ou parar.
  const parada = (Boolean(campanha.parada_em) && !campanha.ativa) || (!campanha.ativa && campanha.pendentes === 0);
  return (
    <div style={{ display: "flex", gap: 8 }} onClick={(e) => e.preventDefault()}>
      {campanha.pausa ? (
        <button
          type="button"
          className="secondary small"
          disabled={ocupado}
          onClick={() =>
            rodar(
              () => api.retomarCampanha(campanha.id),
              () => "Campanha retomada.",
            )
          }
        >
          <IconPlay width={14} height={14} /> Retomar
        </button>
      ) : (
        !parada && (
          <button type="button" className="secondary small" disabled={ocupado} onClick={pausar}>
            <IconPause width={14} height={14} /> Pausar
          </button>
        )
      )}
      {!parada && (
        <button type="button" className="danger small" disabled={ocupado} onClick={parar}>
          <IconStop width={14} height={14} /> Parar
        </button>
      )}
    </div>
  );
}

export default function Campanhas() {
  const [searchParams, setSearchParams] = useSearchParams();
  const aba: Aba = searchParams.get("aba") === "remarketing" ? "remarketing" : "campanhas";
  const [campanhas, setCampanhas] = useState<Campanha[] | null>(null);
  const [erro, setErro] = useState<string | null>(null);
  const [sucesso, setSucesso] = useState<string | null>(null);

  useEffect(() => {
    api
      .listarCampanhas()
      .then(setCampanhas)
      .catch((e) => setErro(e instanceof Error ? e.message : "Erro ao carregar as campanhas"));
  }, []);

  function irParaAba(nova: Aba) {
    const next = new URLSearchParams(searchParams);
    if (nova === "campanhas") next.delete("aba");
    else next.set("aba", nova);
    setSearchParams(next, { replace: true });
  }

  return (
    <div>
      <div className="page-header">
        <div>
          <h2>Campanhas</h2>
          <div className="subtitle">
            Cobranças com filtros e templates próprios, fora das faixas de atraso, e o remarketing de quem desistiu no
            Renegocie.
          </div>
        </div>
        {aba === "campanhas" && (
          <Link to="/campanhas/nova">
            <button type="button">
              <IconPlus width={16} height={16} /> Nova campanha
            </button>
          </Link>
        )}
      </div>

      <div className="tabs" style={{ display: "flex", gap: 8, marginBottom: 16 }}>
        <button
          type="button"
          className={aba === "campanhas" ? "small" : "secondary small"}
          onClick={() => irParaAba("campanhas")}
        >
          Campanhas
        </button>
        <button
          type="button"
          className={aba === "remarketing" ? "small" : "secondary small"}
          onClick={() => irParaAba("remarketing")}
        >
          Remarketing do Renegocie
        </button>
      </div>

      {aba === "remarketing" ? (
        <RemarketingCard />
      ) : (
        <div className="card">
          {erro && (
            <div className="error-box">
              <IconAlert width={16} height={16} />
              <span>{erro}</span>
            </div>
          )}
          {sucesso && <div className="success-box">{sucesso}</div>}
          {campanhas === null && !erro ? (
            <div className="loading-state">Carregando campanhas...</div>
          ) : campanhas && campanhas.length === 0 ? (
            <div className="empty-state">
              <IconMegaphone width={28} height={28} />
              <div className="title">Nenhuma campanha ainda</div>
              <p>
                Crie uma campanha, escolha os filtros (ou suba a planilha de clientes), atribua um template e defina o
                dia ou o período em que ela roda.
              </p>
            </div>
          ) : (
            <div className="faixa-list">
              {(campanhas ?? []).map((c) => (
                <Link
                  key={c.id}
                  to={`/campanhas/${c.id}`}
                  className="faixa-row"
                  style={{ textDecoration: "none", color: "inherit" }}
                >
                  <div className="faixa-row-main">
                    <div className="faixa-icon">
                      <IconMegaphone />
                    </div>
                    <div style={{ minWidth: 0 }}>
                      <div className="faixa-row-title">{c.nome}</div>
                      <div className="faixa-row-sub">
                        {periodoCampanha(c)}
                        {c.clientes_total > 0 && ` · planilha com ${c.clientes_total} cliente(s)`}
                        {" · "}
                        {c.templates.length ? c.templates.join(", ") : "sem template"}
                      </div>
                      <div className="faixa-row-sub">
                        {c.enviados} enviada(s) · {c.pendentes} pendente(s) · {c.erros} erro(s)
                        {c.ultima_execucao && ` · última busca ${formatDataHora(c.ultima_execucao)}`}
                      </div>
                    </div>
                  </div>
                  <div
                    style={{
                      display: "flex",
                      alignItems: "center",
                      gap: 14,
                      flexShrink: 0,
                      marginLeft: "auto",
                    }}
                  >
                    {c.envios_ativos === 0 && <span className="badge rejected">Atribuir template</span>}
                    <AcoesCampanha
                      campanha={c}
                      onAlterada={(nova, mensagem) => {
                        setErro(null);
                        setSucesso(mensagem);
                        setCampanhas((lista) => (lista ?? []).map((x) => (x.id === nova.id ? nova : x)));
                      }}
                      onErro={(m) => {
                        setSucesso(null);
                        setErro(m);
                      }}
                    />
                    <span className={`status-pill ${situacaoCampanha(c).classe}`}>{situacaoCampanha(c).rotulo}</span>
                    <IconArrowRight className="text-faint" />
                  </div>
                </Link>
              ))}
            </div>
          )}
        </div>
      )}
    </div>
  );
}
