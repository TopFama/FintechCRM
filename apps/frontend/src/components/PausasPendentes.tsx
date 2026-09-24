import { useEffect, useState } from "react";
import { api, EscopoPausa, PausaEnvio } from "../api";
import { formatData, formatDataHora } from "../format";

// Ação pedida na aba Pendentes, esperando confirmação na própria tela
export type AcaoPendentes = {
  tipo: "pausar" | "parar";
  escopo: EscopoPausa;
  valor: string;
  rotulo: string; // "o cliente 00000008 · Carlos", "a régua 11 A 20", "a loja 07"
};

const NOME_ESCOPO: Record<EscopoPausa, string> = { cliente: "Cliente", faixa: "Régua", loja: "Loja" };

export function PainelAcao({
  acao,
  onCancelar,
  onConcluir,
}: {
  acao: AcaoPendentes;
  onCancelar: () => void;
  onConcluir: (mensagem: string) => void;
}) {
  const [motivo, setMotivo] = useState("");
  const [ate, setAte] = useState("");
  const [qtd, setQtd] = useState<number | null>(null);
  const [erro, setErro] = useState<string | null>(null);
  const [salvando, setSalvando] = useState(false);

  useEffect(() => {
    setMotivo("");
    setAte("");
    setErro(null);
    setQtd(null);
    if (acao.tipo !== "parar") return;
    let atual = true;
    api
      .previaPararEnvio(acao.escopo, acao.valor)
      .then((r) => atual && setQtd(r.qtd))
      .catch((e) => atual && setErro(e.message));
    return () => {
      atual = false;
    };
  }, [acao]);

  async function confirmar() {
    setSalvando(true);
    setErro(null);
    try {
      if (acao.tipo === "pausar") {
        await api.pausarEnvio({ escopo: acao.escopo, valor: acao.valor, motivo: motivo.trim(), ate: ate || undefined });
        onConcluir(`Envio pausado para ${acao.rotulo}.`);
      } else {
        const r = await api.pararEnvio(acao.escopo, acao.valor);
        onConcluir(`Envio parado para ${acao.rotulo}: ${r.qtd} pendente(s) cancelado(s).`);
      }
    } catch (e) {
      setErro(e instanceof Error ? e.message : "Erro ao salvar");
    } finally {
      setSalvando(false);
    }
  }

  if (acao.tipo === "parar") {
    return (
      <div className="painel-acao perigo" role="alertdialog" aria-labelledby="titulo-parar">
        <strong id="titulo-parar">Parar o envio para {acao.rotulo}?</strong>
        <p style={{ margin: "6px 0 0" }}>
          {qtd === null
            ? "Contando os pendentes..."
            : `${qtd} pendente(s) serão cancelados e não serão enviados. O registro fica na fila como "parado"; não dá para desfazer.`}
        </p>
        {erro && <div className="error-box" style={{ marginTop: 8 }}>{erro}</div>}
        <div className="acoes">
          <button className="danger" onClick={confirmar} disabled={salvando || qtd === null}>
            {salvando ? "Parando..." : `Parar ${qtd ?? ""} envio(s)`}
          </button>
          <button className="secondary" onClick={onCancelar} disabled={salvando}>
            Cancelar
          </button>
        </div>
      </div>
    );
  }

  return (
    <div className="painel-acao" role="dialog" aria-labelledby="titulo-pausar">
      <strong id="titulo-pausar">Pausar o envio para {acao.rotulo}</strong>
      <p className="text-muted" style={{ margin: "4px 0 10px" }}>
        Os pendentes ficam retidos na fila (inclusive os que entrarem depois) até você retomar ou até a data final.
      </p>
      <div className="form-row" style={{ flexWrap: "wrap" }}>
        <div className="field" style={{ flex: 2, minWidth: 240 }}>
          <label htmlFor="pausa-motivo">Motivo</label>
          <input
            id="pausa-motivo"
            value={motivo}
            onChange={(e) => setMotivo(e.target.value)}
            placeholder="Ex.: cliente pediu para negociar na loja"
            aria-required="true"
          />
        </div>
        <div className="field">
          <label htmlFor="pausa-ate">Até (opcional)</label>
          <input id="pausa-ate" type="date" value={ate} onChange={(e) => setAte(e.target.value)} />
        </div>
      </div>
      {erro && <div className="error-box" style={{ marginTop: 8 }}>{erro}</div>}
      <div className="acoes">
        <button onClick={confirmar} disabled={salvando || !motivo.trim()}>
          {salvando ? "Pausando..." : "Pausar"}
        </button>
        <button className="secondary" onClick={onCancelar} disabled={salvando}>
          Cancelar
        </button>
      </div>
    </div>
  );
}

export function PausasAtivas({ pausas, onRetomar }: { pausas: PausaEnvio[]; onRetomar: (p: PausaEnvio) => void }) {
  if (pausas.length === 0) return null;
  return (
    <section className="pausas-ativas" aria-labelledby="titulo-pausas-ativas">
      <h3 id="titulo-pausas-ativas">Pausas ativas</h3>
      <div className="table-wrap">
        <table>
          <thead>
            <tr>
              <th scope="col">Escopo</th>
              <th scope="col">O quê</th>
              <th scope="col">Motivo</th>
              <th scope="col">Quem</th>
              <th scope="col">Desde</th>
              <th scope="col">Até</th>
              <th scope="col">Retidos</th>
              <th scope="col">
                <span className="sr-only">Ações</span>
              </th>
            </tr>
          </thead>
          <tbody>
            {pausas.map((p) => (
              <tr key={p.id}>
                <td>{NOME_ESCOPO[p.escopo]}</td>
                <td className="cell-strong">{p.valor_legivel}</td>
                <td>{p.motivo}</td>
                <td className="text-muted">{p.created_by || "—"}</td>
                <td className="text-faint">{formatDataHora(p.created_at)}</td>
                <td className="text-muted">{p.ate ? formatData(p.ate) : "Sem data"}</td>
                <td>{p.qtd_retidos}</td>
                <td>
                  <button className="small secondary" onClick={() => onRetomar(p)} aria-label={`Retomar ${p.valor_legivel}`}>
                    Retomar
                  </button>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </section>
  );
}
