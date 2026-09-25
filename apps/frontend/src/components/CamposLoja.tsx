import { ChangeEvent, useRef, useState } from "react";
import { Link } from "react-router-dom";
import { api, ColunaPlanilha } from "../api";
import { IconUpload } from "../icons";
import MultiSelect from "./MultiSelect";
import { OpcoesCobranca } from "./useOpcoesCobranca";

export interface ValoresLoja {
  loja?: string[];
  regional?: string[];
  estado?: string[];
  cluster_inad?: string[];
  cluster_populacao?: string[];
  cobradora?: string[];
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
  const arquivoRef = useRef<HTMLInputElement>(null);
  const [lendo, setLendo] = useState(false);
  const [aviso, setAviso] = useState<{ tipo: "ok" | "erro"; texto: string } | null>(null);

  // Relatório .xlsx de lojas: o usuário escolhe qual coluna tem o código da loja
  // (sem adivinhar pelo cabeçalho) e todas são marcadas de uma vez.
  const [planilha, setPlanilha] = useState<{ arquivo: File; colunas: ColunaPlanilha[] } | null>(null);
  const [coluna, setColuna] = useState<string>("");

  async function escolherArquivo(e: ChangeEvent<HTMLInputElement>) {
    const arquivo = e.target.files?.[0];
    e.target.value = "";
    if (!arquivo) return;
    setLendo(true);
    setAviso(null);
    try {
      const colunas = await api.colunasPlanilhaLojas(arquivo);
      setPlanilha({ arquivo, colunas });
      setColuna("");
    } catch (err) {
      setAviso({ tipo: "erro", texto: err instanceof Error ? err.message : "Erro ao abrir a planilha de lojas" });
    } finally {
      setLendo(false);
    }
  }

  async function importarLojas() {
    if (!planilha || coluna === "") return;
    setLendo(true);
    setAviso(null);
    try {
      const r = await api.lerPlanilhaLojas(planilha.arquivo, Number(coluna));
      const juntas = Array.from(new Set([...(valor.loja ?? []), ...r.lojas]));
      onChange({ ...valor, loja: juntas });
      setPlanilha(null);
      setAviso({
        tipo: r.lojas.length ? "ok" : "erro",
        texto:
          `${r.lojas.length} loja(s) marcada(s).` +
          (r.nao_encontradas.length
            ? ` Não encontrei na base de lojas: ${r.nao_encontradas.slice(0, 10).join(", ")}${r.nao_encontradas.length > 10 ? "…" : ""}.`
            : ""),
      });
    } catch (err) {
      setAviso({ tipo: "erro", texto: err instanceof Error ? err.message : "Erro ao ler a planilha de lojas" });
    } finally {
      setLendo(false);
    }
  }
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
          label="Cobradora"
          options={opcoes.cobradoras}
          value={valor.cobradora ?? []}
          onChange={(v) => onChange({ ...valor, cobradora: v })}
          {...desligado}
        />
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
      <div style={{ display: "flex", alignItems: "center", gap: 10, flexWrap: "wrap", marginBottom: 8 }}>
        <input ref={arquivoRef} type="file" accept=".xlsx" hidden onChange={escolherArquivo} aria-label="Planilha de lojas" />
        <button type="button" className="secondary small" onClick={() => arquivoRef.current?.click()} disabled={lendo}>
          <IconUpload width={14} height={14} /> {lendo && !planilha ? "Lendo..." : "Importar lista de lojas (.xlsx)"}
        </button>
        {planilha && (
          <>
            <label htmlFor={`${idPrefixo}-coluna-loja`} className="sr-only">
              Coluna com o código da loja
            </label>
            <select
              id={`${idPrefixo}-coluna-loja`}
              value={coluna}
              onChange={(e) => setColuna(e.target.value)}
              style={{ maxWidth: 320 }}
            >
              <option value="">Qual coluna é a da loja?</option>
              {planilha.colunas.map((c) => (
                <option key={c.indice} value={c.indice}>
                  {c.nome}
                  {c.exemplos.length ? ` (ex.: ${c.exemplos.join(", ")})` : ""}
                </option>
              ))}
            </select>
            <button type="button" className="small" onClick={importarLojas} disabled={coluna === "" || lendo}>
              {lendo ? "Lendo..." : "Marcar lojas"}
            </button>
            <button type="button" className="secondary small" onClick={() => setPlanilha(null)}>
              Cancelar
            </button>
          </>
        )}
        {(valor.loja?.length ?? 0) > 0 && (
          <button type="button" className="secondary small" onClick={() => onChange({ ...valor, loja: [] })}>
            Desmarcar lojas
          </button>
        )}
        {aviso && (
          <span className={aviso.tipo === "ok" ? "field-hint" : "field-error"} role="status">
            {aviso.texto}
          </span>
        )}
        {!aviso && !planilha && (
          <span className="field-hint">Depois de escolher o arquivo, você indica qual coluna tem o código da loja.</span>
        )}
        {planilha && <span className="field-hint">{planilha.arquivo.name}</span>}
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
