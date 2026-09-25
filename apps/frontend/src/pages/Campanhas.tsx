import { useEffect, useState } from "react";
import { Link, useSearchParams } from "react-router-dom";
import { api, Campanha } from "../api";
import RemarketingCard from "../components/config/RemarketingCard";
import { formatData, formatDataHora } from "../format";
import { IconAlert, IconArrowRight, IconMegaphone, IconPlus } from "../icons";

type Aba = "campanhas" | "remarketing";

export function periodoCampanha(c: Pick<Campanha, "modo" | "data_inicio" | "data_fim">): string {
  if (!c.data_inicio) return "Sem data";
  if (c.modo === "unica") return `Só em ${formatData(c.data_inicio)}`;
  return `Todo dia de ${formatData(c.data_inicio)} ${c.data_fim ? `a ${formatData(c.data_fim)}` : "em diante"}`;
}

export default function Campanhas() {
  const [searchParams, setSearchParams] = useSearchParams();
  const aba: Aba = searchParams.get("aba") === "remarketing" ? "remarketing" : "campanhas";
  const [campanhas, setCampanhas] = useState<Campanha[] | null>(null);
  const [erro, setErro] = useState<string | null>(null);

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
                  <div style={{ display: "flex", alignItems: "center", gap: 14, flexShrink: 0, marginLeft: "auto" }}>
                    {c.envios_ativos === 0 && <span className="badge rejected">Atribuir template</span>}
                    <span className={`status-pill ${c.ativa ? "on" : "off"}`}>{c.ativa ? "Ligada" : "Desligada"}</span>
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
