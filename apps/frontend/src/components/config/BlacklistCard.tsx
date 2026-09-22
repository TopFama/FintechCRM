import { useCallback, useEffect, useRef, useState } from "react";
import { api, Bloqueado } from "../../api";
import { formatCpf, formatDataHora } from "../../format";
import SortableTh from "../SortableTh";
import { IconAlert, IconBan } from "../../icons";
import { ordenarPor, useSort } from "../../sort";

type ColunaBloqueado = "tipo" | "valor" | "motivo" | "created_at";

export default function BlacklistCard() {
  const [lista, setLista] = useState<Bloqueado[]>([]);
  const [busca, setBusca] = useState("");
  const [carregando, setCarregando] = useState(false);
  const listaSort = useSort<ColunaBloqueado>();
  const listaOrdenada = ordenarPor(
    lista,
    listaSort.sortKey ? (item: Bloqueado) => item[listaSort.sortKey as ColunaBloqueado] : null,
    listaSort.sortDir
  );

  // Formulário individual
  const [doc, setDoc] = useState("");
  const [motivoDoc, setMotivoDoc] = useState("");
  const [adicionando, setAdicionando] = useState(false);
  const [erroDoc, setErroDoc] = useState<string | null>(null);
  const [sucessoDoc, setSucessoDoc] = useState<string | null>(null);

  // Bloco de lote
  const [loteTexto, setLoteTexto] = useState("");
  const [motivoLote, setMotivoLote] = useState("");
  const [adicionandoLote, setAdicionandoLote] = useState(false);
  const [erroLote, setErroLote] = useState<string | null>(null);
  const [sucessoLote, setSucessoLote] = useState<string | null>(null);
  const [invalidosLote, setInvalidosLote] = useState<string[]>([]);
  const [erroTabela, setErroTabela] = useState<string | null>(null);

  const debounceRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  const carregar = useCallback((termo: string) => {
    setCarregando(true);
    setErroTabela(null);
    api
      .listarBlacklist(termo || undefined)
      .then(setLista)
      .catch((e) => setErroTabela(e instanceof Error ? e.message : "Erro ao carregar"))
      .finally(() => setCarregando(false));
  }, []);

  useEffect(() => {
    carregar("");
  }, [carregar]);

  function onBuscaChange(valor: string) {
    setBusca(valor);
    if (debounceRef.current) clearTimeout(debounceRef.current);
    debounceRef.current = setTimeout(() => carregar(valor), 400);
  }

  function onBuscaKeyDown(e: React.KeyboardEvent<HTMLInputElement>) {
    if (e.key === "Enter") {
      if (debounceRef.current) clearTimeout(debounceRef.current);
      carregar(busca);
    }
  }

  async function adicionarUm(e: React.FormEvent) {
    e.preventDefault();
    setErroDoc(null);
    setSucessoDoc(null);
    setAdicionando(true);
    try {
      await api.adicionarBlacklist(doc.trim(), motivoDoc.trim() || undefined);
      setSucessoDoc(`"${doc.trim()}" adicionado à blacklist.`);
      setDoc("");
      setMotivoDoc("");
      carregar(busca);
    } catch (err) {
      setErroDoc(err instanceof Error ? err.message : "Erro ao adicionar");
    } finally {
      setAdicionando(false);
    }
  }

  async function adicionarLote(e: React.FormEvent) {
    e.preventDefault();
    setErroLote(null);
    setSucessoLote(null);
    setInvalidosLote([]);
    setAdicionandoLote(true);
    // Divide por quebras de linha, vírgulas ou ponto-e-vírgulas
    const documentos = loteTexto
      .split(/[\n,;]+/)
      .map((s) => s.trim())
      .filter(Boolean);
    try {
      const r = await api.adicionarBlacklistLote(documentos, motivoLote.trim() || undefined);
      setSucessoLote(`${r.adicionados} adicionados, ${r.ja_existiam} já estavam na lista.`);
      setInvalidosLote(r.invalidos);
      setLoteTexto("");
      setMotivoLote("");
      carregar(busca);
    } catch (err) {
      setErroLote(err instanceof Error ? err.message : "Erro ao adicionar lote");
    } finally {
      setAdicionandoLote(false);
    }
  }

  async function remover(item: Bloqueado) {
    if (!window.confirm(`Remover "${item.valor}" da blacklist?`)) return;
    setErroTabela(null);
    try {
      await api.removerBlacklist(item.id);
      carregar(busca);
    } catch (err) {
      setErroTabela(err instanceof Error ? err.message : "Erro ao remover");
    }
  }

  function tipoLabel(tipo: "seta" | "cpf"): string {
    return tipo === "seta" ? "Código SETA" : "CPF";
  }

  return (
    <div>
      {/* Adicionar individualmente */}
      <div className="card">
        <div className="card-header">
          <h3>Adicionar</h3>
        </div>
        {erroDoc && (
          <div className="error-box">
            <IconAlert width={16} height={16} />
            <span>{erroDoc}</span>
          </div>
        )}
        {sucessoDoc && <div className="success-box">{sucessoDoc}</div>}
        <form onSubmit={adicionarUm}>
          <div className="form-row">
            <div className="field">
              <label htmlFor="bl-doc">Código SETA ou CPF</label>
              <input
                id="bl-doc"
                value={doc}
                onChange={(e) => setDoc(e.target.value)}
                placeholder="Ex: 00123456 ou 123.456.789-00"
                required
              />
            </div>
            <div className="field">
              <label htmlFor="bl-motivo">Motivo (opcional)</label>
              <input
                id="bl-motivo"
                value={motivoDoc}
                onChange={(e) => setMotivoDoc(e.target.value)}
                placeholder="Ex: Solicitação do cliente"
              />
            </div>
          </div>
          <button type="submit" disabled={adicionando}>
            {adicionando ? "Adicionando..." : "Adicionar"}
          </button>
        </form>
      </div>

      {/* Colar lista */}
      <div className="card">
        <div className="card-header">
          <h3>Colar lista</h3>
        </div>
        {erroLote && (
          <div className="error-box">
            <IconAlert width={16} height={16} />
            <span>{erroLote}</span>
          </div>
        )}
        {sucessoLote && (
          <div className="success-box">
            {sucessoLote}
            {invalidosLote.length > 0 && (
              <span>
                {" "}
                Inválidos: <strong>{invalidosLote.join(", ")}</strong>
              </span>
            )}
          </div>
        )}
        <form onSubmit={adicionarLote}>
          <div className="field">
            <label htmlFor="bl-lote">Documentos (um por linha, ou separados por vírgula/ponto e vírgula)</label>
            <textarea
              id="bl-lote"
              rows={5}
              value={loteTexto}
              onChange={(e) => setLoteTexto(e.target.value)}
              placeholder={"00123456\n00234567\n123.456.789-00"}
            />
          </div>
          <div className="field">
            <label htmlFor="bl-motivo-lote">Motivo (opcional)</label>
            <input
              id="bl-motivo-lote"
              value={motivoLote}
              onChange={(e) => setMotivoLote(e.target.value)}
            />
          </div>
          <button type="submit" disabled={adicionandoLote || !loteTexto.trim()}>
            {adicionandoLote ? "Adicionando..." : "Adicionar lista"}
          </button>
        </form>
      </div>

      {/* Tabela */}
      <div className="card">
        <div className="card-header">
          <h3>Registros ({lista.length})</h3>
          <div className="field" style={{ margin: 0, minWidth: 240 }}>
            <label htmlFor="bl-busca" className="sr-only">
              Buscar
            </label>
            <input
              id="bl-busca"
              value={busca}
              onChange={(e) => onBuscaChange(e.target.value)}
              onKeyDown={onBuscaKeyDown}
              placeholder="Buscar por código ou CPF..."
            />
          </div>
        </div>

        {erroTabela && (
          <div className="error-box">
            <IconAlert width={16} height={16} />
            <span>{erroTabela}</span>
          </div>
        )}

        {carregando && <div className="loading-state">Carregando...</div>}

        {!carregando && lista.length === 0 && (
          <div className="empty-state">
            <IconBan width={28} height={28} />
            <div className="title">Nenhum registro encontrado</div>
            <p>Adicione um código SETA ou CPF acima para bloqueá-lo.</p>
          </div>
        )}

        {!carregando && lista.length > 0 && (
          <div className="table-wrap">
            <table>
              <thead>
                <tr>
                  <SortableTh scope="col" active={listaSort.sortKey === "tipo"} dir={listaSort.sortDir} onSort={() => listaSort.toggleSort("tipo")}>
                    Tipo
                  </SortableTh>
                  <SortableTh scope="col" active={listaSort.sortKey === "valor"} dir={listaSort.sortDir} onSort={() => listaSort.toggleSort("valor")}>
                    Documento
                  </SortableTh>
                  <SortableTh scope="col" active={listaSort.sortKey === "motivo"} dir={listaSort.sortDir} onSort={() => listaSort.toggleSort("motivo")}>
                    Motivo
                  </SortableTh>
                  <SortableTh
                    scope="col"
                    active={listaSort.sortKey === "created_at"}
                    dir={listaSort.sortDir}
                    onSort={() => listaSort.toggleSort("created_at")}
                  >
                    Adicionado em
                  </SortableTh>
                  <th scope="col"></th>
                </tr>
              </thead>
              <tbody>
                {listaOrdenada.map((item) => (
                  <tr key={item.id}>
                    <td>
                      <span className="badge draft">{tipoLabel(item.tipo)}</span>
                    </td>
                    <td className="cell-strong">
                      {item.tipo === "cpf" ? formatCpf(item.valor) : item.valor}
                    </td>
                    <td className="text-muted">{item.motivo || "—"}</td>
                    <td className="text-muted">{formatDataHora(item.created_at)}</td>
                    <td>
                      <button
                        type="button"
                        className="danger small"
                        onClick={() => remover(item)}
                      >
                        Remover
                      </button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>
    </div>
  );
}
