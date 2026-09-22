import { useEffect, useState } from "react";
import { api, MetaToken, WhatsappNumber } from "../../api";
import { IconAlert, IconPhone } from "../../icons";

interface Edicao {
  label: string;
  active: boolean;
  meta_token_id: string;
  chatwoot_inbox_id: string;
}

// Números de WhatsApp importados da Meta (card Tokens da Meta). Aqui se liga cada
// número à sua inbox do Chatwoot, ao token que ele usa e se ele envia ou não.
export default function NumerosCard({ versao }: { versao: number }) {
  const [numeros, setNumeros] = useState<WhatsappNumber[]>([]);
  const [tokens, setTokens] = useState<MetaToken[]>([]);
  const [erro, setErro] = useState<string | null>(null);
  const [editandoId, setEditandoId] = useState<string | null>(null);
  const [edicao, setEdicao] = useState<Edicao>({ label: "", active: true, meta_token_id: "", chatwoot_inbox_id: "" });
  const [salvando, setSalvando] = useState(false);

  function carregar() {
    api.listNumbers().then(setNumeros).catch((e) => setErro(e.message));
    api.listarTokensMeta().then(setTokens).catch((e) => setErro(e.message));
  }

  useEffect(carregar, [versao]);

  function editar(n: WhatsappNumber) {
    setErro(null);
    setEditandoId(n.id);
    setEdicao({
      label: n.label,
      active: n.active,
      meta_token_id: n.meta_token_id ?? "",
      chatwoot_inbox_id: n.chatwoot_inbox_id ? String(n.chatwoot_inbox_id) : "",
    });
  }

  async function salvar(id: string) {
    setErro(null);
    setSalvando(true);
    try {
      await api.atualizarNumero(id, {
        label: edicao.label.trim(),
        active: edicao.active,
        meta_token_id: edicao.meta_token_id || null,
        chatwoot_inbox_id: edicao.chatwoot_inbox_id ? parseInt(edicao.chatwoot_inbox_id, 10) : null,
      });
      setEditandoId(null);
      carregar();
    } catch (e) {
      setErro(e instanceof Error ? e.message : "Erro ao salvar o número");
    } finally {
      setSalvando(false);
    }
  }

  async function excluir(n: WhatsappNumber) {
    if (
      !window.confirm(
        `Excluir o número "${n.label || n.display_phone_number}"? Ele sai de qualquer faixa que o usava. Pra só parar de enviar por ele, use "Editar" e marque como inativo em vez de excluir.`
      )
    )
      return;
    setErro(null);
    try {
      await api.excluirNumero(n.id);
      carregar();
    } catch (e) {
      setErro(e instanceof Error ? e.message : "Erro ao excluir o número");
    }
  }

  return (
    <div className="card">
      <div className="card-header">
        <div>
          <h3>Números de WhatsApp</h3>
          <div className="card-subtitle">
            Os números entram pelo botão "Números da Meta" de um token. Aqui você informa a inbox do Chatwoot de cada um
            e desativa os que não devem enviar.
          </div>
        </div>
      </div>

      {erro && (
        <div className="error-box" style={{ marginBottom: 16 }}>
          <IconAlert width={16} height={16} />
          <span>{erro}</span>
        </div>
      )}

      {numeros.length === 0 ? (
        <div className="empty-state">
          <IconPhone width={28} height={28} />
          <div className="title">Nenhum número importado</div>
          <p>Cadastre um token da Meta acima e importe os números da WABA.</p>
        </div>
      ) : (
        <div className="table-wrap">
          <table>
            <thead>
              <tr>
                <th scope="col">Apelido</th>
                <th scope="col">Número</th>
                <th scope="col">WABA</th>
                <th scope="col">Token</th>
                <th scope="col">Inbox do Chatwoot</th>
                <th scope="col">Ativo</th>
                <th scope="col">Ações</th>
              </tr>
            </thead>
            <tbody>
              {numeros.map((n) =>
                editandoId === n.id ? (
                  <tr key={n.id}>
                    <td>
                      <input
                        aria-label="Apelido"
                        value={edicao.label}
                        onChange={(e) => setEdicao({ ...edicao, label: e.target.value })}
                        style={{ minWidth: 120 }}
                      />
                    </td>
                    <td>{n.display_phone_number}</td>
                    <td className="text-muted">{n.waba_id}</td>
                    <td>
                      <select
                        aria-label="Token"
                        value={edicao.meta_token_id}
                        onChange={(e) => setEdicao({ ...edicao, meta_token_id: e.target.value })}
                      >
                        <option value="">Token da WABA</option>
                        {tokens
                          .filter((t) => t.ativo || t.id === n.meta_token_id)
                          .map((t) => (
                            <option key={t.id} value={t.id}>
                              {t.nome} (…{t.ultimos4}){t.ativo ? "" : " (inativo)"}
                            </option>
                          ))}
                      </select>
                    </td>
                    <td>
                      <input
                        aria-label="ID da inbox do Chatwoot"
                        type="number"
                        min="1"
                        step="1"
                        value={edicao.chatwoot_inbox_id}
                        onChange={(e) => setEdicao({ ...edicao, chatwoot_inbox_id: e.target.value })}
                        placeholder="ex. 12"
                        style={{ width: 90 }}
                      />
                    </td>
                    <td>
                      <select
                        aria-label="Ativo"
                        value={edicao.active ? "sim" : "nao"}
                        onChange={(e) => setEdicao({ ...edicao, active: e.target.value === "sim" })}
                      >
                        <option value="sim">Sim</option>
                        <option value="nao">Não</option>
                      </select>
                    </td>
                    <td>
                      <div style={{ display: "flex", gap: 6 }}>
                        <button type="button" className="small" onClick={() => salvar(n.id)} disabled={salvando}>
                          {salvando ? "Salvando..." : "Salvar"}
                        </button>
                        <button
                          type="button"
                          className="secondary small"
                          onClick={() => setEditandoId(null)}
                          disabled={salvando}
                        >
                          Cancelar
                        </button>
                      </div>
                    </td>
                  </tr>
                ) : (
                  <tr key={n.id}>
                    <td className="cell-strong">{n.label || "—"}</td>
                    <td>{n.display_phone_number}</td>
                    <td className="text-muted">{n.waba_id}</td>
                    <td>{n.meta_token_nome ?? <span className="text-muted">da WABA</span>}</td>
                    <td>{n.chatwoot_inbox_id ?? <span className="text-muted">não informada</span>}</td>
                    <td>
                      <span className={`status-pill ${n.active ? "on" : "off"}`}>{n.active ? "Sim" : "Não"}</span>
                    </td>
                    <td style={{ display: "flex", gap: 6 }}>
                      <button type="button" className="danger small" onClick={() => excluir(n)}>
                        Excluir
                      </button>
                      <button type="button" className="secondary small" onClick={() => editar(n)}>
                        Editar
                      </button>
                    </td>
                  </tr>
                ),
              )}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}
