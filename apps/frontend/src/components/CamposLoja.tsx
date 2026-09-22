import { Link } from "react-router-dom";
import MultiSelect from "./MultiSelect";
import { OpcoesCobranca } from "./useOpcoesCobranca";

export interface ValoresLoja {
  loja?: string[];
  regional?: string[];
  estado?: string[];
  cluster_inad?: string[];
  cluster_populacao?: string[];
}

interface Props {
  valor: ValoresLoja;
  onChange: (valor: ValoresLoja) => void;
  opcoes: OpcoesCobranca;
  // O relatório de efetividade não filtra por cluster de população
  semClusterPopulacao?: boolean;
  idPrefixo: string;
}

export default function CamposLoja({ valor, onChange, opcoes, semClusterPopulacao, idPrefixo }: Props) {
  const semGoogle = opcoes.googleIndisponivel;
  const desligado = { disabled: semGoogle, placeholder: semGoogle ? "—" : "Todos" };

  return (
    <>
      <div className="form-row" style={{ flexWrap: "wrap" }}>
        {semGoogle ? (
          <div className="field" style={{ flex: "1 1 200px" }}>
            <label htmlFor={`${idPrefixo}-loja-texto`}>Loja (códigos, sep. por vírgula/espaço)</label>
            <input
              id={`${idPrefixo}-loja-texto`}
              placeholder="ex. 42, C7"
              value={(valor.loja ?? []).join(", ")}
              onChange={(e) =>
                onChange({
                  ...valor,
                  loja: e.target.value
                    .split(/[,\s]+/)
                    .map((s) => s.trim())
                    .filter(Boolean),
                })
              }
            />
          </div>
        ) : (
          <MultiSelect
            label="Loja"
            options={opcoes.lojas}
            value={valor.loja ?? []}
            onChange={(v) => onChange({ ...valor, loja: v })}
          />
        )}
        <MultiSelect
          label="Regional"
          options={opcoes.regionais}
          value={valor.regional ?? []}
          onChange={(v) => onChange({ ...valor, regional: v })}
          {...desligado}
        />
        <MultiSelect
          label="Estado"
          options={opcoes.estados}
          value={valor.estado ?? []}
          onChange={(v) => onChange({ ...valor, estado: v })}
          {...desligado}
        />
        <MultiSelect
          label="Cluster INAD"
          options={opcoes.clustersInad}
          value={valor.cluster_inad ?? []}
          onChange={(v) => onChange({ ...valor, cluster_inad: v })}
          {...desligado}
        />
        {!semClusterPopulacao && (
          <MultiSelect
            label="Cluster de população"
            options={opcoes.clustersPopulacao}
            value={valor.cluster_populacao ?? []}
            onChange={(v) => onChange({ ...valor, cluster_populacao: v })}
            {...desligado}
          />
        )}
      </div>
      {semGoogle && (
        <div className="field-hint" style={{ marginBottom: 8 }}>
          Conecte o Google em <Link to="/configuracoes">Configurações</Link> para filtrar por regional, estado e
          clusters de loja.
        </div>
      )}
    </>
  );
}
