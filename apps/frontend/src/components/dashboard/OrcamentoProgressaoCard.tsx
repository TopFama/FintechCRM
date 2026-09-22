import { useEffect, useState } from "react";
import { api, OrcamentoProgressao } from "../../api";
import { formatBRL } from "../../format";
import { IconAlert } from "../../icons";

const NOMES_MES = [
  "janeiro", "fevereiro", "março", "abril", "maio", "junho",
  "julho", "agosto", "setembro", "outubro", "novembro", "dezembro",
];

// Linha de progressão do mês: gasto real acumulado (Meta, convertido em BRL)
// dia a dia comparado ao orçamento cadastrado em Configurações > Indicadores.
export default function OrcamentoProgressaoCard() {
  const hoje = new Date();
  const [dados, setDados] = useState<OrcamentoProgressao | null>(null);
  const [erro, setErro] = useState<string | null>(null);

  useEffect(() => {
    api
      .getOrcamentoProgressao(hoje.getFullYear(), hoje.getMonth() + 1)
      .then(setDados)
      .catch((e) => setErro(e.message));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  if (erro) {
    return (
      <div className="card">
        <div className="error-box">
          <IconAlert width={16} height={16} />
          <span>{erro}</span>
        </div>
      </div>
    );
  }

  if (!dados) {
    return (
      <div className="card">
        <div className="loading-state">Carregando orçamento do mês...</div>
      </div>
    );
  }

  const orcado = Number(dados.valor_orcado);
  const gastoInfo = dados.valor_gasto_brl !== null;
  const maiorValor = Math.max(orcado, ...dados.dias.map((d) => Number(d.gasto_acumulado_brl)), 1);

  const largura = 640;
  const altura = 180;
  const margem = 28;
  const pontos = dados.dias.map((d, i) => {
    const x = margem + (i / Math.max(dados.dias.length - 1, 1)) * (largura - margem * 2);
    const y = altura - margem - (Number(d.gasto_acumulado_brl) / maiorValor) * (altura - margem * 2);
    return `${x},${y}`;
  });
  const yOrcado = altura - margem - (orcado / maiorValor) * (altura - margem * 2);

  return (
    <div className="card">
      <div className="card-header">
        <div>
          <h3>Orçamento do mês</h3>
          <div className="card-subtitle">
            Gasto real com WhatsApp em {NOMES_MES[dados.mes - 1]} vs. orçado ({formatBRL(dados.valor_orcado)})
          </div>
        </div>
      </div>

      {!gastoInfo ? (
        <div className="empty-state">
          <p>
            Sem custo do WhatsApp disponível para o período (nenhuma WABA configurada, ou a Meta/câmbio estão
            indisponíveis no momento).
          </p>
        </div>
      ) : (
        <>
          <div className="form-row" style={{ marginBottom: 8 }}>
            <div className="stat">
              <div className="stat-label">Gasto acumulado</div>
              <div className="stat-value">{formatBRL(dados.valor_gasto_brl!)}</div>
            </div>
            <div className="stat">
              <div className="stat-label">Orçado</div>
              <div className="stat-value">{formatBRL(dados.valor_orcado)}</div>
            </div>
          </div>
          <svg viewBox={`0 0 ${largura} ${altura}`} width="100%" height={altura} role="img" aria-label="Progressão de gasto no mês">
            <line
              x1={margem}
              y1={yOrcado}
              x2={largura - margem}
              y2={yOrcado}
              stroke="var(--danger, #d9534f)"
              strokeDasharray="4 4"
              strokeWidth={1.5}
            />
            <polyline points={pontos.join(" ")} fill="none" stroke="var(--primary, #003090)" strokeWidth={2} />
            <line x1={margem} y1={altura - margem} x2={largura - margem} y2={altura - margem} stroke="#ccc" />
          </svg>
        </>
      )}
    </div>
  );
}
