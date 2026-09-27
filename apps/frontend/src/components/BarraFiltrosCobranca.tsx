import { api, FiltrosCobranca } from "../api";
import CamposLoja from "./CamposLoja";
import MultiSelect from "./MultiSelect";
import CampoValorMaximo from "./CampoValorMaximo";
import { OpcoesCobranca, opcoesCluster } from "./useOpcoesCobranca";

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
  valor_atraso_min: "",
  valor_atraso_max: "",
  valor_atraso_com_juros: false,
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
  // Sem onAplicar, não mostra a linha de Aplicar/Limpar (formulário da campanha).
  onAplicar?: () => void;
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
          options={opcoesCluster(opcoes.regras)}
          value={valor.cluster ?? []}
          onChange={(v) => set({ cluster: v })}
        />
        <MultiSelect
          label="Faixa de compra"
          options={paraOpcoes(opcoes.regras?.faixas_compra)}
          value={valor.faixa_compra ?? []}
          onChange={(v) => set({ faixa_compra: v })}
          // Faixa de compra vem da cópia local do SETA: ao abrir, relê as vendas do dia
          onOpen={() => void api.atualizarComprasSeta().catch(() => undefined)}
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

      <div className="form-row" style={{ flexWrap: "wrap", alignItems: "flex-start" }}>
        <div className="field" style={{ flex: "1 1 160px" }}>
          <label htmlFor={`${idPrefixo}-atraso-min`}>Valor em atraso de (R$)</label>
          <input
            id={`${idPrefixo}-atraso-min`}
            type="number"
            min={0}
            step="0.01"
            value={valor.valor_atraso_min ?? ""}
            onChange={(e) => set({ valor_atraso_min: e.target.value })}
          />
        </div>
        <div className="field" style={{ flex: "1 1 160px" }}>
          <CampoValorMaximo
            id={`${idPrefixo}-atraso-max`}
            label="Valor em atraso até (R$)"
            value={valor.valor_atraso_max ?? ""}
            onChange={(v) => set({ valor_atraso_max: v })}
          />
        </div>
        <div className="field" style={{ flex: "1 1 220px" }}>
          <label htmlFor={`${idPrefixo}-atraso-tipo`}>Valor considerado</label>
          <select
            id={`${idPrefixo}-atraso-tipo`}
            value={valor.valor_atraso_com_juros ? "juros" : "original"}
            onChange={(e) => set({ valor_atraso_com_juros: e.target.value === "juros" })}
          >
            <option value="original">Original das parcelas</option>
            <option value="juros">Corrigido com multa e juros</option>
          </select>
        </div>
      </div>
      <div className="field-hint" style={{ marginBottom: 8 }}>
        Valor em atraso é a soma das parcelas já vencidas do cliente.
      </div>

      {onAplicar && (
      <div className="actions-row">
        <button type="button" onClick={onAplicar}>
          Aplicar filtros
        </button>
        <button type="button" className="secondary" onClick={() => onChange(FILTROS_COBRANCA_PADRAO)}>
          Limpar
        </button>
        {acaoDireita && <div style={{ marginLeft: "auto" }}>{acaoDireita}</div>}
      </div>
      )}
    </>
  );
}
