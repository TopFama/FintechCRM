import { FormEvent, useState } from "react";
import { api, ColunaEmBranco } from "../api";

interface Props {
  campanhaId: string;
  colunasEmBranco: ColunaEmBranco[];
  onClose: () => void;
  onSalvo: () => void;
}

const OPCOES_CAMPOS = [
  { valor: "nome", rotulo: "Nome completo" },
  { valor: "primeiro_nome", rotulo: "Primeiro nome" },
  { valor: "codigo", rotulo: "Código SETA" },
  { valor: "codigo_primeiro_nome", rotulo: "Código - Primeiro nome" },
  { valor: "cpf", rotulo: "CPF" },
  { valor: "celular", rotulo: "Celular" },
  { valor: "cluster", rotulo: "Cluster" },
  { valor: "faixa", rotulo: "Faixa de atraso" },
  { valor: "dias_atraso", rotulo: "Dias de atraso" },
  { valor: "qtd_parcelas", rotulo: "Parcelas em atraso" },
  { valor: "valor_em_aberto", rotulo: "Valor em aberto" },
  { valor: "vencimento", rotulo: "Vencimento da parcela mais antiga" },
  { valor: "valor_parcela_amanha", rotulo: "Valor da parcela que vence amanhã" },
  { valor: "valor_proxima_parcela", rotulo: "Valor da próxima parcela" },
  { valor: "valor_atraso", rotulo: "Valor em atraso" },
];

export default function ModalDecisaoVariaveis({ campanhaId, colunasEmBranco, onClose, onSalvo }: Props) {
  const [decisoes, setDecisoes] = useState<Record<string, string>>(() => {
    const iniciais: Record<string, string> = {};
    colunasEmBranco.forEach((c) => {
      iniciais[c.variavel_id] = c.sugestao_campo || "";
    });
    return iniciais;
  });
  const [salvando, setSalvando] = useState(false);
  const [erro, setErro] = useState<string | null>(null);

  const pronto = colunasEmBranco.every((c) => !!decisoes[c.variavel_id]);

  async function salvar(e: FormEvent) {
    e.preventDefault();
    setErro(null);
    setSalvando(true);
    try {
      const payload = Object.entries(decisoes).map(([template_variable_id, reserva]) => ({
        template_variable_id,
        reserva,
      }));
      const restantes = await api.salvarReservaVazioCampanha(campanhaId, payload);
      if (restantes && restantes.length > 0) {
        setErro("Ainda há colunas com valores em branco sem decisão.");
      } else {
        onSalvo();
      }
    } catch (err) {
      setErro(err instanceof Error ? err.message : "Erro ao salvar decisões");
    } finally {
      setSalvando(false);
    }
  }

  return (
    <div className="modal-backdrop">
      <div className="modal-content" style={{ maxWidth: 600 }}>
        <h2>Variáveis com valores em branco</h2>
        <p className="card-subtitle">
          Alguns clientes possuem células vazias na planilha para colunas usadas no template da campanha. 
          Escolha o que o sistema deve fazer em cada caso.
        </p>

        {erro && (
          <div className="error-box" style={{ marginBottom: 16 }}>
            <span>{erro}</span>
          </div>
        )}

        <form onSubmit={salvar}>
          {colunasEmBranco.map((c) => (
            <div key={c.variavel_id} className="field" style={{ marginBottom: 16 }}>
              <label>
                Coluna <strong>{c.coluna_nome}</strong> ({c.qtd_afetados} cliente(s) afetado(s))
              </label>
              <select
                value={decisoes[c.variavel_id] || ""}
                onChange={(e) => setDecisoes({ ...decisoes, [c.variavel_id]: e.target.value })}
              >
                <option value="" disabled>-- Selecione uma ação --</option>
                <optgroup label="Usar um valor do sistema">
                  {OPCOES_CAMPOS.map((op) => (
                    <option key={op.valor} value={op.valor}>
                      {op.rotulo}
                    </option>
                  ))}
                </optgroup>
                <optgroup label="Ação">
                  <option value="fora">Fora da campanha (não enviar)</option>
                </optgroup>
              </select>
            </div>
          ))}

          <div className="actions-row">
            <button type="button" className="secondary" onClick={onClose} disabled={salvando}>
              Cancelar
            </button>
            <button type="submit" disabled={!pronto || salvando}>
              {salvando ? "Salvando..." : "Salvar decisões"}
            </button>
          </div>
        </form>
      </div>
    </div>
  );
}
