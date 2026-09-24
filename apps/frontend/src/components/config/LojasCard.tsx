import { FormEvent, useCallback, useEffect, useMemo, useState } from "react";
import { api, Loja, LojaEditavel } from "../../api";
import { BadgeClusterInad } from "../dashboard/EfetividadeCard";
import { IconAlert, IconPlus, IconRefresh, IconTrash } from "../../icons";

const CAMPOS: { campo: keyof LojaEditavel; rotulo: string }[] = [
  { campo: "nome_com_cod", rotulo: "Nome" },
  { campo: "regional", rotulo: "Regional" },
  { campo: "estado", rotulo: "Estado" },
  { campo: "cluster_cobradora", rotulo: "Cobradora" },
  { campo: "cluster_inad", rotulo: "Cluster INAD" },
  { campo: "cluster_populacao", rotulo: "Cluster população" },
];

const VAZIA: LojaEditavel = {
  nome_com_cod: null,
  regional: null,
  estado: null,
  cluster_cobradora: null,
  cluster_inad: null,
  cluster_populacao: null,
};

// Base de lojas (tabela do banco). Usada nos filtros de loja, regional,
// cobradora e clusters de todas as telas.
export default function LojasCard() {
  const [lojas, setLojas] = useState<Loja[]>([]);
  const [carregando, setCarregando] = useState(false);
  const [busca, setBusca] = useState("");
  const [erro, setErro] = useState<string | null>(null);
  const [sucesso, setSucesso] = useState<string | null>(null);

  const [editando, setEditando] = useState<string | null>(null);
  const [rascunho, setRascunho] = useState<LojaEditavel>(VAZIA);
  const [salvando, setSalvando] = useState(false);

  const [novaFilial, setNovaFilial] = useState("");
  const [nova, setNova] = useState<LojaEditavel>(VAZIA);
  const [criando, setCriando] = useState(false);
  const [sincronizando, setSincronizando] = useState(false);

  const carregar = useCallback(() => {
    setCarregando(true);
    api
      .listarLojas()
      .then(setLojas)
      .catch((e) => setErro(e instanceof Error ? e.message : "Erro ao carregar lojas"))
      .finally(() => setCarregando(false));
  }, []);

  useEffect(() => {
    carregar();
  }, [carregar]);

  // Sugestões de preenchimento com os valores que já existem na base
  const sugestoes = useMemo(() => {
    const por: Partial<Record<keyof LojaEditavel, string[]>> = {};
    for (const { campo } of CAMPOS) {
      if (campo === "nome_com_cod") continue;
      por[campo] = [...new Set(lojas.map((l) => l[campo]).filter((v): v is string => !!v))].sort();
    }
    return por;
  }, [lojas]);

  const filtradas = useMemo(() => {
    const t = busca.trim().toUpperCase();
    if (!t) return lojas;
    return lojas.filter((l) =>
      [l.filial, ...CAMPOS.map(({ campo }) => l[campo])].some((v) => v && v.toUpperCase().includes(t))
    );
  }, [lojas, busca]);

  function limparAvisos() {
    setErro(null);
    setSucesso(null);
  }

  function comecarEdicao(loja: Loja) {
    limparAvisos();
    setEditando(loja.filial);
    const { filial: _f, ...resto } = loja;
    setRascunho(resto);
  }

  async function salvarEdicao(e: FormEvent) {
    e.preventDefault();
    if (!editando) return;
    limparAvisos();
    setSalvando(true);
    try {
      const salva = await api.editarLoja(editando, rascunho);
      setLojas((atual) => atual.map((l) => (l.filial === salva.filial ? salva : l)));
      setSucesso(`Loja ${salva.filial} salva.`);
      setEditando(null);
    } catch (err) {
      setErro(err instanceof Error ? err.message : "Erro ao salvar a loja");
    } finally {
      setSalvando(false);
    }
  }

  async function criar(e: FormEvent) {
    e.preventDefault();
    limparAvisos();
    setCriando(true);
    try {
      const criada = await api.criarLoja({ filial: novaFilial.trim(), ...nova });
      setSucesso(`Loja ${criada.filial} adicionada.`);
      setNovaFilial("");
      setNova(VAZIA);
      carregar();
    } catch (err) {
      setErro(err instanceof Error ? err.message : "Erro ao adicionar a loja");
    } finally {
      setCriando(false);
    }
  }

  async function excluir(loja: Loja) {
    if (!window.confirm(`Excluir a loja ${loja.nome_com_cod ?? loja.filial}?`)) return;
    limparAvisos();
    try {
      await api.excluirLoja(loja.filial);
      setLojas((atual) => atual.filter((l) => l.filial !== loja.filial));
      setSucesso(`Loja ${loja.filial} excluída.`);
    } catch (err) {
      setErro(err instanceof Error ? err.message : "Erro ao excluir a loja");
    }
  }

  async function sincronizar() {
    if (
      !window.confirm(
        "Sincronizar com a planilha de lojas? Os campos que estão na planilha substituem os valores daqui; lojas que só existem aqui ficam como estão."
      )
    )
      return;
    limparAvisos();
    setSincronizando(true);
    try {
      const r = await api.sincronizarLojas();
      setSucesso(
        `Sincronizado com a planilha: ${r.novas} novas, ${r.atualizadas} atualizadas, ${r.sem_mudanca} sem mudança.`
      );
      setEditando(null);
      carregar();
    } catch (err) {
      setErro(err instanceof Error ? err.message : "Erro ao sincronizar com a planilha");
    } finally {
      setSincronizando(false);
    }
  }

  function campoTexto(
    valores: LojaEditavel,
    set: (v: LojaEditavel) => void,
    campo: keyof LojaEditavel,
    rotulo: string,
    id: string
  ) {
    const lista = sugestoes[campo];
    return (
      <>
        <input
          id={id}
          aria-label={rotulo}
          value={valores[campo] ?? ""}
          maxLength={campo === "estado" ? 2 : undefined}
          list={lista ? `${id}-sugestoes` : undefined}
          onChange={(e) => set({ ...valores, [campo]: e.target.value })}
        />
        {lista && (
          <datalist id={`${id}-sugestoes`}>
            {lista.map((v) => (
              <option key={v} value={v} />
            ))}
          </datalist>
        )}
      </>
    );
  }

  return (
    <div>
      <div className="card">
        <div className="card-header">
          <h3>Lojas</h3>
          <button type="button" className="secondary small" onClick={sincronizar} disabled={sincronizando}>
            <IconRefresh width={15} height={15} /> {sincronizando ? "Sincronizando..." : "Sincronizar com a planilha"}
          </button>
        </div>
        <p className="field-hint" style={{ marginTop: 0 }}>
          Base usada nos filtros de loja, regional, cobradora e clusters de todas as telas. Loja sem cobradora aparece
          como "Sem cobradora" no filtro.
        </p>
        {erro && (
          <div className="error-box">
            <IconAlert width={16} height={16} />
            <span>{erro}</span>
          </div>
        )}
        {sucesso && <div className="success-box">{sucesso}</div>}

        <div className="field" style={{ maxWidth: 320 }}>
          <label htmlFor="lojas-busca">Buscar</label>
          <input
            id="lojas-busca"
            placeholder="Filial, nome, regional, cobradora..."
            value={busca}
            onChange={(e) => setBusca(e.target.value)}
          />
        </div>

        {carregando && lojas.length === 0 ? (
          <div className="loading-state">Carregando...</div>
        ) : filtradas.length === 0 ? (
          <div className="empty-state">
            <div className="title">Nenhuma loja encontrada</div>
          </div>
        ) : (
          <form onSubmit={salvarEdicao}>
            <div className="table-wrap">
              <table>
                <thead>
                  <tr>
                    <th scope="col">Filial</th>
                    {CAMPOS.map((c) => (
                      <th scope="col" key={c.campo}>
                        {c.rotulo}
                      </th>
                    ))}
                    <th scope="col" aria-label="Ações" />
                  </tr>
                </thead>
                <tbody>
                  {filtradas.map((l) =>
                    editando === l.filial ? (
                      <tr key={l.filial}>
                        <td className="cell-strong">{l.filial}</td>
                        {CAMPOS.map((c) => (
                          <td key={c.campo}>
                            {campoTexto(rascunho, setRascunho, c.campo, c.rotulo, `loja-${l.filial}-${c.campo}`)}
                          </td>
                        ))}
                        <td style={{ whiteSpace: "nowrap" }}>
                          <button type="submit" className="small" disabled={salvando}>
                            {salvando ? "Salvando..." : "Salvar"}
                          </button>{" "}
                          <button type="button" className="secondary small" onClick={() => setEditando(null)}>
                            Cancelar
                          </button>
                        </td>
                      </tr>
                    ) : (
                      <tr key={l.filial}>
                        <td className="cell-strong">{l.filial}</td>
                        <td>{l.nome_com_cod ?? <span className="text-faint">—</span>}</td>
                        <td>{l.regional ?? <span className="text-faint">—</span>}</td>
                        <td>{l.estado ?? <span className="text-faint">—</span>}</td>
                        <td>
                          {l.cluster_cobradora ? (
                            <span className="badge draft">{l.cluster_cobradora}</span>
                          ) : (
                            <span className="text-faint">Sem cobradora</span>
                          )}
                        </td>
                        <td>
                          <BadgeClusterInad valor={l.cluster_inad} />
                        </td>
                        <td>{l.cluster_populacao ?? <span className="text-faint">—</span>}</td>
                        <td style={{ whiteSpace: "nowrap" }}>
                          <button
                            type="button"
                            className="secondary small"
                            onClick={() => comecarEdicao(l)}
                            disabled={editando !== null}
                          >
                            Editar
                          </button>{" "}
                          <button
                            type="button"
                            className="danger small"
                            onClick={() => excluir(l)}
                            disabled={editando !== null}
                            title={`Excluir a loja ${l.filial}`}
                            aria-label={`Excluir a loja ${l.filial}`}
                          >
                            <IconTrash width={14} height={14} />
                          </button>
                        </td>
                      </tr>
                    )
                  )}
                </tbody>
              </table>
            </div>
          </form>
        )}
      </div>

      <div className="card" style={{ marginTop: 16 }}>
        <div className="card-header">
          <h3>Adicionar loja</h3>
        </div>
        <form onSubmit={criar}>
          <div className="form-row" style={{ flexWrap: "wrap" }}>
            <div className="field" style={{ flex: "0 1 120px" }}>
              <label htmlFor="loja-nova-filial">Filial</label>
              <input
                id="loja-nova-filial"
                placeholder="ex. 42"
                maxLength={4}
                value={novaFilial}
                onChange={(e) => setNovaFilial(e.target.value)}
                required
              />
            </div>
            {CAMPOS.map((c) => (
              <div className="field" key={c.campo} style={{ flex: "1 1 160px" }}>
                <label htmlFor={`loja-nova-${c.campo}`}>{c.rotulo}</label>
                {campoTexto(nova, setNova, c.campo, c.rotulo, `loja-nova-${c.campo}`)}
              </div>
            ))}
          </div>
          <button type="submit" disabled={criando || !novaFilial.trim()}>
            <IconPlus width={15} height={15} /> {criando ? "Adicionando..." : "Adicionar loja"}
          </button>
        </form>
      </div>
    </div>
  );
}
