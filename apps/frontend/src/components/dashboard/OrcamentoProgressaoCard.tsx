import { useEffect, useState } from "react";
import { api, OrcamentoProgressao } from "../../api";
import { formatBRL, formatData } from "../../format";
import { IconAlert } from "../../icons";

const NOMES_MES = [
  "janeiro", "fevereiro", "março", "abril", "maio", "junho",
  "julho", "agosto", "setembro", "outubro", "novembro", "dezembro",
];

// Últimos 12 meses no formato "ano-mes" para a lista suspensa.
function mesesRecentes(): { valor: string; rotulo: string }[] {
  const hoje = new Date();
  return Array.from({ length: 12 }, (_, i) => {
    const d = new Date(hoje.getFullYear(), hoje.getMonth() - i, 1);
    return { valor: `${d.getFullYear()}-${d.getMonth() + 1}`, rotulo: `${NOMES_MES[d.getMonth()]}/${d.getFullYear()}` };
  });
}

// Gasto real com WhatsApp (Meta, em BRL) acumulado dia a dia vs. orçamento
// cadastrado em Configurações > Indicadores. Filtro próprio: um mês ou um
// período personalizado.
export default function OrcamentoProgressaoCard() {
  const meses = mesesRecentes();
  const [selecao, setSelecao] = useState(meses[0].valor);
  const [de, setDe] = useState("");
  const [ate, setAte] = useState("");
  const [dados, setDados] = useState<OrcamentoProgressao | null>(null);
  const [erro, setErro] = useState<string | null>(null);

  useEffect(() => {
    let filtro: { ano?: number; mes?: number; de?: string; ate?: string };
    if (selecao === "personalizado") {
      if (!de || !ate) return;
      filtro = { de, ate };
    } else {
      const [ano, mes] = selecao.split("-").map(Number);
      filtro = { ano, mes };
    }
    setErro(null);
    setDados(null);
    api.getOrcamentoProgressao(filtro).then(setDados).catch((e) => setErro(e.message));
  }, [selecao, de, ate]);

  const filtros = (
    <div className="form-row">
      <div className="field">
        <label>Mês/ano</label>
        <select value={selecao} onChange={(e) => setSelecao(e.target.value)}>
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
            <label>Data mínima</label>
            <input type="date" value={de} max={ate || undefined} onChange={(e) => setDe(e.target.value)} />
          </div>
          <div className="field">
            <label>Data máxima</label>
            <input type="date" value={ate} min={de || undefined} onChange={(e) => setAte(e.target.value)} />
          </div>
        </>
      )}
    </div>
  );

  const cabecalho = (
    <div className="card-header">
      <div>
        <h3>Orçamento</h3>
        {dados && (
          <div className="card-subtitle">
            Gasto real com WhatsApp de {formatData(dados.de)} a {formatData(dados.ate)} vs. orçado (
            {formatBRL(dados.valor_orcado)})
          </div>
        )}
      </div>
    </div>
  );

  if (erro || !dados) {
    return (
      <div className="card">
        {cabecalho}
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
      {cabecalho}
      {filtros}

      {!gastoInfo ? (
        <div className="empty-state">
          <p>Sem custo do WhatsApp para o período. Motivo: {dados.motivo_sem_gasto || "não informado pela Meta"}</p>
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
          <svg viewBox={`0 0 ${largura} ${altura}`} width="100%" height={altura} role="img" aria-label="Progressão de gasto no período">
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
