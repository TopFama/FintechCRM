import { useEffect, useState } from "react";
import {
  api,
  CelulaMatriz,
  ClusterConfig,
  ClusterConfigIn,
  ConfigCobrancaOut,
  FaixaAtrasoConfig,
  FaixaAtrasoConfigIn,
} from "../../api";
import { IconAlert, IconCheckCircle, IconPlus, IconTrash } from "../../icons";

// Regras de cobrança usadas nos filtros da Cobrança/Leads e na fila de disparo:
// clusters (por valor pago), faixas de atraso (por dias) e a matriz de quem
// entra na cobrança por WhatsApp. Tudo isso já é lido pelo backend a partir
// destas mesmas tabelas (config/cobranca) — aqui só editamos.
export default function RegrasCobrancaCard() {
  const [config, setConfig] = useState<ConfigCobrancaOut | null>(null);
  const [erro, setErro] = useState<string | null>(null);
  const [sucesso, setSucesso] = useState<string | null>(null);

  const [clusters, setClusters] = useState<ClusterConfigIn[]>([]);
  const [faixas, setFaixas] = useState<FaixaAtrasoConfigIn[]>([]);
  const [matriz, setMatriz] = useState<Set<string>>(new Set());

  const [salvandoClusters, setSalvandoClusters] = useState(false);
  const [salvandoFaixas, setSalvandoFaixas] = useState(false);
  const [salvandoMatriz, setSalvandoMatriz] = useState(false);

  function chave(clusterId: string, faixaId: string): string {
    return `${clusterId}::${faixaId}`;
  }

  // Ao salvar um bloco só ele é recarregado do servidor, para não apagar o
  // que foi editado e ainda não salvo nos outros blocos.
  function aplicarConfig(c: ConfigCobrancaOut, bloco: "clusters" | "faixas" | "matriz" | "tudo" = "tudo") {
    setConfig(c);
    if (bloco === "clusters" || bloco === "tudo")
      setClusters(c.clusters.map((x: ClusterConfig) => ({ id: x.id, nome: x.nome, valor_min: x.valor_min })));
    if (bloco === "faixas" || bloco === "tudo")
      setFaixas(c.faixas.map((x: FaixaAtrasoConfig) => ({ id: x.id, nome: x.nome, dia_min: x.dia_min, dia_max: x.dia_max })));
    if (bloco === "matriz" || bloco === "tudo")
      setMatriz(new Set(c.matriz.map((m: CelulaMatriz) => chave(m.cluster_id, m.faixa_id))));
  }

  function carregar() {
    setErro(null);
    api.getConfigCobranca().then(aplicarConfig).catch((e) => setErro(e.message));
  }

  useEffect(carregar, []);

  async function salvarClusters() {
    setErro(null);
    setSucesso(null);
    setSalvandoClusters(true);
    try {
      const c = await api.salvarClustersCobranca(clusters);
      aplicarConfig(c, "clusters");
      setSucesso("Clusters salvos");
    } catch (e) {
      setErro(e instanceof Error ? e.message : "Erro ao salvar clusters");
    } finally {
      setSalvandoClusters(false);
    }
  }

  async function salvarFaixas() {
    setErro(null);
    setSucesso(null);
    setSalvandoFaixas(true);
    try {
      const c = await api.salvarFaixasCobranca(faixas);
      aplicarConfig(c, "faixas");
      setSucesso("Faixas de atraso salvas");
    } catch (e) {
      setErro(e instanceof Error ? e.message : "Erro ao salvar faixas de atraso");
    } finally {
      setSalvandoFaixas(false);
    }
  }

  async function salvarMatriz() {
    if (!config) return;
    setErro(null);
    setSucesso(null);
    setSalvandoMatriz(true);
    try {
      const celulas: CelulaMatriz[] = [];
      for (const cl of config.clusters) {
        for (const f of config.faixas) {
          if (matriz.has(chave(cl.id, f.id))) {
            celulas.push({ cluster_id: cl.id, faixa_id: f.id });
          }
        }
      }
      const c = await api.salvarMatrizCobranca(celulas);
      aplicarConfig(c, "matriz");
      setSucesso("Regra do WhatsApp salva");
    } catch (e) {
      setErro(e instanceof Error ? e.message : "Erro ao salvar a matriz do WhatsApp");
    } finally {
      setSalvandoMatriz(false);
    }
  }

  function toggleCelula(clusterId: string, faixaId: string) {
    setMatriz((atual) => {
      const proximo = new Set(atual);
      const k = chave(clusterId, faixaId);
      if (proximo.has(k)) proximo.delete(k);
      else proximo.add(k);
      return proximo;
    });
  }

  if (!config) {
    return (
      <div className="card">
        <div className="card-header">
          <h3>Regras de cobrança</h3>
        </div>
        {erro ? (
          <div className="error-box">
            <IconAlert width={16} height={16} />
            <span>{erro}</span>
          </div>
        ) : (
          <div className="loading-state">Carregando regras...</div>
        )}
      </div>
    );
  }

  return (
    <div className="card">
      <div className="card-header">
        <div>
          <h3>Regras de cobrança</h3>
          <div className="card-subtitle">
            Clusters (por valor pago), faixas de atraso (por dias) e quem entra na cobrança de WhatsApp — usados nos
            filtros de Cobrança/Leads e na fila de disparo.
          </div>
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

      <h4>Clusters</h4>
      <p className="card-subtitle" style={{ marginTop: 0 }}>
        Segmento do cliente pela soma paga em vendas. Vale do "valor mínimo" (inclusive) até o mínimo do próximo
        cluster; o primeiro precisa começar em R$ 0,00.
      </p>
      <div className="table-wrap">
        <table>
          <thead>
            <tr>
              <th scope="col">Nome</th>
              <th scope="col">Valor mínimo (R$)</th>
              <th scope="col"></th>
            </tr>
          </thead>
          <tbody>
            {clusters.map((c, i) => (
              <tr key={c.id ?? `novo-${i}`}>
                <td>
                  <input
                    aria-label="Nome do cluster"
                    value={c.nome}
                    onChange={(e) =>
                      setClusters((atual) => atual.map((x, j) => (j === i ? { ...x, nome: e.target.value } : x)))
                    }
                    style={{ minWidth: 160 }}
                  />
                </td>
                <td>
                  <input
                    aria-label="Valor mínimo"
                    type="number"
                    min="0"
                    step="0.01"
                    value={c.valor_min}
                    onChange={(e) =>
                      setClusters((atual) => atual.map((x, j) => (j === i ? { ...x, valor_min: e.target.value } : x)))
                    }
                    style={{ width: 120 }}
                  />
                </td>
                <td>
                  <button
                    type="button"
                    className="danger small"
                    onClick={() => setClusters((atual) => atual.filter((_, j) => j !== i))}
                    title="Remover cluster"
                  >
                    <IconTrash width={15} height={15} />
                  </button>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <div className="actions-row">
        <button
          type="button"
          className="secondary small"
          onClick={() => setClusters((atual) => [...atual, { nome: "", valor_min: "0" }])}
        >
          <IconPlus width={15} height={15} /> Adicionar cluster
        </button>
        <button type="button" className="small" onClick={salvarClusters} disabled={salvandoClusters}>
          {salvandoClusters ? "Salvando..." : "Salvar clusters"}
        </button>
      </div>

      <h4 style={{ marginTop: 28 }}>Faixas de atraso</h4>
      <p className="card-subtitle" style={{ marginTop: 0 }}>
        Intervalo de dias de atraso. Deixe "dia máximo" em branco na última faixa para não ter limite superior.
      </p>
      <div className="table-wrap">
        <table>
          <thead>
            <tr>
              <th scope="col">Nome</th>
              <th scope="col">Dia mínimo</th>
              <th scope="col">Dia máximo</th>
              <th scope="col"></th>
            </tr>
          </thead>
          <tbody>
            {faixas.map((f, i) => (
              <tr key={f.id ?? `nova-${i}`}>
                <td>
                  <input
                    aria-label="Nome da faixa"
                    value={f.nome}
                    onChange={(e) =>
                      setFaixas((atual) => atual.map((x, j) => (j === i ? { ...x, nome: e.target.value } : x)))
                    }
                    style={{ minWidth: 140 }}
                  />
                </td>
                <td>
                  <input
                    aria-label="Dia mínimo"
                    type="number"
                    value={f.dia_min}
                    onChange={(e) =>
                      setFaixas((atual) =>
                        atual.map((x, j) => (j === i ? { ...x, dia_min: Number(e.target.value) } : x))
                      )
                    }
                    style={{ width: 90 }}
                  />
                </td>
                <td>
                  <input
                    aria-label="Dia máximo"
                    type="number"
                    value={f.dia_max ?? ""}
                    placeholder="sem limite"
                    onChange={(e) =>
                      setFaixas((atual) =>
                        atual.map((x, j) =>
                          j === i ? { ...x, dia_max: e.target.value === "" ? null : Number(e.target.value) } : x
                        )
                      )
                    }
                    style={{ width: 90 }}
                  />
                </td>
                <td>
                  <button
                    type="button"
                    className="danger small"
                    onClick={() => setFaixas((atual) => atual.filter((_, j) => j !== i))}
                    title="Remover faixa"
                  >
                    <IconTrash width={15} height={15} />
                  </button>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <div className="actions-row">
        <button
          type="button"
          className="secondary small"
          onClick={() => setFaixas((atual) => [...atual, { nome: "", dia_min: 0, dia_max: null }])}
        >
          <IconPlus width={15} height={15} /> Adicionar faixa
        </button>
        <button type="button" className="small" onClick={salvarFaixas} disabled={salvandoFaixas}>
          {salvandoFaixas ? "Salvando..." : "Salvar faixas"}
        </button>
      </div>

      <h4 style={{ marginTop: 28 }}>Quem entra na cobrança de WhatsApp</h4>
      <p className="card-subtitle" style={{ marginTop: 0 }}>
        Marque, para cada cluster e faixa de atraso, se essa combinação entra na cobrança via WhatsApp.
      </p>
      <div className="table-wrap">
        <table className="matriz-table">
          <thead>
            <tr>
              <th scope="col">Cluster \ Faixa</th>
              {config.faixas.map((f) => (
                <th scope="col" key={f.id}>
                  {f.nome}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {config.clusters.map((cl) => (
              <tr key={cl.id}>
                <td className="cell-strong">{cl.nome}</td>
                {config.faixas.map((f) => (
                  <td key={f.id} style={{ textAlign: "center" }}>
                    <input
                      type="checkbox"
                      aria-label={`${cl.nome} entra no WhatsApp na faixa ${f.nome}`}
                      checked={matriz.has(chave(cl.id, f.id))}
                      onChange={() => toggleCelula(cl.id, f.id)}
                    />
                  </td>
                ))}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <div className="actions-row">
        <button type="button" className="small" onClick={salvarMatriz} disabled={salvandoMatriz}>
          {salvandoMatriz ? "Salvando..." : "Salvar regra do WhatsApp"}
        </button>
      </div>
    </div>
  );
}
