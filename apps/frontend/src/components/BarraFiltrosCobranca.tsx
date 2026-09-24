import { FiltrosCobranca } from "../api";
import CamposLoja from "./CamposLoja";
import MultiSelect from "./MultiSelect";
import { OpcoesCobranca } from "./useOpcoesCobranca";

export const FILTROS_COBRANCA_PADRAO: FiltrosCobranca = {
  apenas_primeiro_dia: true,
  somente_regra_whatsapp: true,
  faixa: [],
  cluster: [],
  faixa_compra: [],
  loja: [],
  cobradora: [],
  status_cliente: [],
  restricao_spc: [],
  regional: [],
  estado: [],
  cluster_inad: [],
  cluster_populacao: [],
  vencimento_de: "",
  vencimento_ate: "",
};

const OPCOES_STATUS = [
  { value: "E", label: "Especial" },
  { value: "A", label: "Ativo" },
  { value: "B", label: "Bloqueado" },
];
const OPCOES_SPC = [
  { value: "sim", label: "Sim" },
  { value: "nao", label: "Não" },
  { value: "indeterminado", label: "Indeterminado" },
];

interface Props {
  valor: FiltrosCobranca;
  onChange: (valor: FiltrosCobranca) => void;
  onAplicar: () => void;
  acaoDireita?: React.ReactNode; // botão extra alinhado à direita, na linha de Aplicar
  opcoes: OpcoesCobranca;
  idPrefixo: string;
}

// Mesmos filtros de GET /cobranca/clientes, /cobranca/relatorio e /leads/gerar.
export default function BarraFiltrosCobranca({ valor, onChange, onAplicar, opcoes, idPrefixo, acaoDireita }: Props) {
  const paraOpcoes = (valores: string[] = []) => valores.map((v) => ({ value: v, label: v }));
  const set = (parcial: Partial<FiltrosCobranca>) => onChange({ ...valor, ...parcial });

  return (
    <>
      <div className="form-row" style={{ flexWrap: "wrap", gap: "18px 24px" }}>
        <label className="checkbox-row">
          <input
            type="checkbox"
            checked={!!valor.apenas_primeiro_dia}
            onChange={(e) => set({ apenas_primeiro_dia: e.target.checked })}
          />
          Somente o primeiro dia da faixa
        </label>
        <label className="checkbox-row">
          <input
            type="checkbox"
            checked={!!valor.somente_regra_whatsapp}
            onChange={(e) => set({ somente_regra_whatsapp: e.target.checked })}
          />
          Somente clientes da regra WhatsApp
        </label>
      </div>

      <div className="form-row" style={{ flexWrap: "wrap" }}>
        <MultiSelect
          label="Faixa de atraso"
          options={paraOpcoes(opcoes.regras?.faixas)}
          value={valor.faixa ?? []}
          onChange={(v) => set({ faixa: v })}
        />
        <MultiSelect
          label="Cluster"
          options={paraOpcoes(opcoes.regras?.clusters)}
          value={valor.cluster ?? []}
          onChange={(v) => set({ cluster: v })}
        />
        <MultiSelect
          label="Faixa de compra"
          options={paraOpcoes(opcoes.regras?.faixas_compra)}
          value={valor.faixa_compra ?? []}
          onChange={(v) => set({ faixa_compra: v })}
        />
      </div>

      <div className="form-row" style={{ flexWrap: "wrap" }}>
        <MultiSelect
          label="Status do cliente"
          options={OPCOES_STATUS}
          value={valor.status_cliente ?? []}
          onChange={(v) => set({ status_cliente: v })}
        />
        <MultiSelect
          label="Restrição SPC"
          options={OPCOES_SPC}
          value={valor.restricao_spc ?? []}
          onChange={(v) => set({ restricao_spc: v })}
        />
      </div>

      <CamposLoja valor={valor} onChange={(v) => set(v)} opcoes={opcoes} idPrefixo={idPrefixo} />

      <div className="form-row" style={{ flexWrap: "wrap" }}>
        <div className="field" style={{ flex: "1 1 160px" }}>
          <label htmlFor={`${idPrefixo}-venc-de`}>Vencimento de</label>
          <input
            id={`${idPrefixo}-venc-de`}
            type="date"
            value={valor.vencimento_de ?? ""}
            onChange={(e) => set({ vencimento_de: e.target.value })}
          />
        </div>
        <div className="field" style={{ flex: "1 1 160px" }}>
          <label htmlFor={`${idPrefixo}-venc-ate`}>Vencimento até</label>
          <input
            id={`${idPrefixo}-venc-ate`}
            type="date"
            value={valor.vencimento_ate ?? ""}
            onChange={(e) => set({ vencimento_ate: e.target.value })}
          />
        </div>
      </div>

      <div className="actions-row">
        <button type="button" onClick={onAplicar}>
          Aplicar filtros
        </button>
        <button type="button" className="secondary" onClick={() => onChange(FILTROS_COBRANCA_PADRAO)}>
          Limpar
        </button>
        {acaoDireita && <div style={{ marginLeft: "auto" }}>{acaoDireita}</div>}
      </div>
    </>
  );
}
