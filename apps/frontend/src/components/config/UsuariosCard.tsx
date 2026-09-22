import { FormEvent, useCallback, useEffect, useState } from "react";
import { api, Usuario } from "../../api";
import { formatDataHora } from "../../format";
import SortableTh from "../SortableTh";
import { IconAlert, IconUserShield } from "../../icons";
import { ordenarPor, useSort } from "../../sort";

type ColunaUsuario = "email" | "is_admin" | "created_at";

// Quem pode entrar no portal — só visível pra quem é admin (a permissão de
// verdade é sempre checada no backend, isso aqui só evita mostrar a UI).
export default function UsuariosCard() {
  const [lista, setLista] = useState<Usuario[]>([]);
  const [carregando, setCarregando] = useState(false);
  const [erroTabela, setErroTabela] = useState<string | null>(null);
  const listaSort = useSort<ColunaUsuario>();
  const listaOrdenada = ordenarPor(
    lista,
    listaSort.sortKey
      ? (item: Usuario) => (listaSort.sortKey === "is_admin" ? (item.is_admin ? "1" : "0") : item[listaSort.sortKey as "email" | "created_at"])
      : null,
    listaSort.sortDir
  );

  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [criando, setCriando] = useState(false);
  const [erroForm, setErroForm] = useState<string | null>(null);
  const [sucessoForm, setSucessoForm] = useState<string | null>(null);

  const carregar = useCallback(() => {
    setCarregando(true);
    setErroTabela(null);
    api
      .listUsuarios()
      .then(setLista)
      .catch((e) => setErroTabela(e instanceof Error ? e.message : "Erro ao carregar"))
      .finally(() => setCarregando(false));
  }, []);

  useEffect(() => {
    carregar();
  }, [carregar]);

  async function criar(e: FormEvent) {
    e.preventDefault();
    setErroForm(null);
    setSucessoForm(null);
    setCriando(true);
    try {
      await api.criarUsuario(email.trim(), password);
      setSucessoForm(`Usuário "${email.trim()}" criado.`);
      setEmail("");
      setPassword("");
      carregar();
    } catch (err) {
      setErroForm(err instanceof Error ? err.message : "Erro ao criar usuário");
    } finally {
      setCriando(false);
    }
  }

  async function excluir(usuario: Usuario) {
    if (!window.confirm(`Excluir o usuário "${usuario.email}"?`)) return;
    setErroTabela(null);
    try {
      await api.excluirUsuario(usuario.id);
      carregar();
    } catch (err) {
      setErroTabela(err instanceof Error ? err.message : "Erro ao excluir");
    }
  }

  return (
    <>
      <div className="card">
        <div className="card-header">
          <h3>Criar usuário</h3>
        </div>
        {erroForm && (
          <div className="error-box">
            <IconAlert width={16} height={16} />
            <span>{erroForm}</span>
          </div>
        )}
        {sucessoForm && <div className="success-box">{sucessoForm}</div>}
        <form onSubmit={criar}>
          <div className="form-row">
            <div className="field">
              <label htmlFor="us-email">Email</label>
              <input
                id="us-email"
                type="email"
                value={email}
                onChange={(e) => setEmail(e.target.value)}
                placeholder="pessoa@topfama.com.br"
                required
              />
            </div>
            <div className="field">
              <label htmlFor="us-senha">Senha</label>
              <input
                id="us-senha"
                type="password"
                value={password}
                onChange={(e) => setPassword(e.target.value)}
                placeholder="Mínimo 8 caracteres"
                minLength={8}
                required
              />
            </div>
          </div>
          <button type="submit" disabled={criando}>
            {criando ? "Criando..." : "Criar usuário"}
          </button>
        </form>
      </div>

      <div className="card">
        <div className="card-header">
          <h3>Usuários ({lista.length})</h3>
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
            <IconUserShield width={28} height={28} />
            <div className="title">Nenhum usuário encontrado</div>
          </div>
        )}

        {!carregando && lista.length > 0 && (
          <div className="table-wrap">
            <table>
              <thead>
                <tr>
                  <SortableTh scope="col" active={listaSort.sortKey === "email"} dir={listaSort.sortDir} onSort={() => listaSort.toggleSort("email")}>
                    Email
                  </SortableTh>
                  <SortableTh
                    scope="col"
                    active={listaSort.sortKey === "is_admin"}
                    dir={listaSort.sortDir}
                    onSort={() => listaSort.toggleSort("is_admin")}
                  >
                    Acesso
                  </SortableTh>
                  <SortableTh
                    scope="col"
                    active={listaSort.sortKey === "created_at"}
                    dir={listaSort.sortDir}
                    onSort={() => listaSort.toggleSort("created_at")}
                  >
                    Criado em
                  </SortableTh>
                  <th scope="col"></th>
                </tr>
              </thead>
              <tbody>
                {listaOrdenada.map((usuario) => (
                  <tr key={usuario.id}>
                    <td className="cell-strong">{usuario.email}</td>
                    <td>
                      <span className={`badge ${usuario.is_admin ? "approved" : "draft"}`}>
                        {usuario.is_admin ? "Administrador" : "Padrão"}
                      </span>
                    </td>
                    <td className="text-muted">{formatDataHora(usuario.created_at)}</td>
                    <td>
                      {!usuario.is_admin && (
                        <button type="button" className="danger small" onClick={() => excluir(usuario)}>
                          Excluir
                        </button>
                      )}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>
    </>
  );
}
