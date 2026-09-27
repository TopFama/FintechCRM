import { useEffect, useRef, useState } from "react";
import { api, OrcamentoMes } from "../../api";
import { formatBRL, hojeBR } from "../../format";
import { IconAlert, IconCheckCircle } from "../../icons";

const NOMES_MES = [
  "Janeiro", "Fevereiro", "Março", "Abril", "Maio", "Junho",
  "Julho", "Agosto", "Setembro", "Outubro", "Novembro", "Dezembro",
];

// Orçamento mensal (BRL) de gasto com disparo de WhatsApp — comparado no
// Dashboard com o custo real das conversas cobradas pela Meta no período.
export default function OrcamentoCard() {
  const anoAtual = hojeBR().getFullYear();
  const [ano, setAno] = useState(anoAtual);
  const [meses, setMeses] = useState<OrcamentoMes[]>([]);
  const [erro, setErro] = useState<string | null>(null);
  const [sucesso, setSucesso] = useState<string | null>(null);
  const [salvando, setSalvando] = useState(false);

  // Trocar o ano limpa a tabela e ignora a resposta de um ano já trocado: sem
  // isso, Salvar gravava no ano novo os valores do anterior
  const reqRef = useRef(0);
  function carregar(a: number) {
    setErro(null);
    setMeses([]);
    const seq = ++reqRef.current;
    api
      .getOrcamento(a)
      .then((m) => seq === reqRef.current && setMeses(m))
      .catch((e) => seq === reqRef.current && setErro(e.message));
  }

  useEffect(() => carregar(ano), [ano]);

  function atualizarValor(mes: number, valor: string) {
    setMeses((atual) => atual.map((m) => (m.mes === mes ? { ...m, valor_orcado: valor } : m)));
  }

  async function salvar() {
    setErro(null);
    setSucesso(null);
    setSalvando(true);
    try {
      const atualizado = await api.salvarOrcamento(
        ano,
        meses.map((m) => ({ mes: m.mes, valor_orcado: m.valor_orcado || "0" }))
      );
      setMeses(atualizado);
      setSucesso("Orçamento salvo");
    } catch (e) {
      setErro(e instanceof Error ? e.message : "Erro ao salvar orçamento");
    } finally {
      setSalvando(false);
    }
  }

  return (
    <div className="card">
      <div className="card-header">
        <div>
          <h3>Orçamento</h3>
          <div className="card-subtitle">
            Valor orçado por mês (BRL) para o gasto com disparo de WhatsApp — comparado no Dashboard com o custo real
            das conversas cobradas pela Meta.
          </div>
        </div>
        <div className="field" style={{ maxWidth: 120 }}>
          <label htmlFor="orc-ano">Ano</label>
          <input
            id="orc-ano"
            type="number"
            value={ano}
            onChange={(e) => setAno(Number(e.target.value) || anoAtual)}
          />
        </div>
      </div>

      {erro && (
        <div className="error-box" style={{ marginBottom: 16 }}>
          <IconAlert width={16} height={16} />
          <span>{erro}</span>
        </div>
      )}
      {sucesso && (
        <div className="success-box" style={{ marginBottom: 16 }}>
          <IconCheckCircle width={16} height={16} />
          <span>{sucesso}</span>
        </div>
      )}

      <div className="table-wrap">
        <table>
          <thead>
            <tr>
              <th scope="col">Mês</th>
              <th scope="col">Valor orçado (R$)</th>
            </tr>
          </thead>
          <tbody>
            {meses.map((m) => (
              <tr key={m.mes}>
                <td className="cell-strong">{NOMES_MES[m.mes - 1]}</td>
                <td>
                  <input
                    aria-label={`Valor orçado para ${NOMES_MES[m.mes - 1]}`}
                    type="number"
                    min="0"
                    step="0.01"
                    value={m.valor_orcado}
                    onChange={(e) => atualizarValor(m.mes, e.target.value)}
                    style={{ width: 140 }}
                  />
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <div className="actions-row">
        <button type="button" onClick={salvar} disabled={salvando || meses.length === 0}>
          {salvando ? "Salvando..." : "Salvar orçamento"}
        </button>
      </div>
      {meses.length > 0 && (
        <div className="field-hint" style={{ marginTop: 8 }}>
          Total do ano: {formatBRL(meses.reduce((soma, m) => soma + Number(m.valor_orcado || 0), 0).toFixed(2))}
        </div>
      )}
    </div>
  );
}
