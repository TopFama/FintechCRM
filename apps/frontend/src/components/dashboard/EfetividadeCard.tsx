import { useRef, useState } from "react";
import { api, mensagemErroSeta, FiltrosEfetividade, LinhaEfetividade, RelatorioEfetividade } from "../../api";
import { formatBRL, formatPercentual } from "../../format";
import { IconAlert } from "../../icons";
import CamposLoja from "../CamposLoja";
import MultiSelect from "../MultiSelect";
import { OpcoesCobranca } from "../useOpcoesCobranca";

type Aba = "faixa" | "loja";

// "" = qualquer data após o envio (sem limite); "outro" = número digitado
const JANELAS = [
  { value: "", label: "Qualquer data após o envio" },
  { value: "7", label: "Até 7 dias" },
  { value: "15", label: "Até 15 dias" },
  { value: "30", label: "Até 30 dias" },
  { value: "outro", label: "Outro (dias)" },
];

const FILTROS_PADRAO: FiltrosEfetividade = {
  cobrado_de: "",
  cobrado_ate: "",
  faixa: [],
  cluster: [],
  loja: [],
  regional: [],
  estado: [],
  cluster_inad: [],
};

function semAcento(texto: string): string {
  return texto.normalize("NFD").replace(/\p{Diacritic}/gu, "").toUpperCase();
}

// Formatação condicional do cluster de inadimplência da loja (os valores vêm da planilha)
export function BadgeClusterInad({ valor }: { valor: string | null }) {
  if (!valor) return <span className="text-faint">—</span>;
  const t = semAcento(valor);
  const tom = t.includes("ALT") ? "alto" : t.includes("MED") ? "medio" : t.includes("BAIX") ? "baixo" : "neutro";
  return <span className={`badge cluster-inad-${tom}`}>{valor}</span>;
}

function Metricas({ linha }: { linha: LinhaEfetividade }) {
  return (
    <>
      <td>{linha.qtd_envios.toLocaleString("pt-BR")}</td>
      <td>{linha.clientes_cobrados.toLocaleString("pt-BR")}</td>
      <td>{linha.clientes_pagaram.toLocaleString("pt-BR")}</td>
      <td>{formatPercentual(linha.conversao_clientes)}</td>
      <td>{formatBRL(linha.valor_pago)}</td>
    </>
  );
}

const CABECALHO_METRICAS = ["Qtd. de envios", "Clientes cobrados", "Clientes pagou", "% Conv.", "Recebimento"];

export default function EfetividadeCard({ opcoes }: { opcoes: OpcoesCobranca }) {
  const [filtros, setFiltros] = useState<FiltrosEfetividade>(FILTROS_PADRAO);
  const [janela, setJanela] = useState("7");
  const [janelaOutro, setJanelaOutro] = useState("");
  const [relatorio, setRelatorio] = useState<RelatorioEfetividade | null>(null);
  const [erro, setErro] = useState<string | null>(null);
  const [carregando, setCarregando] = useState(false);
  const [exportando, setExportando] = useState(false);
  const [exportandoClientes, setExportandoClientes] = useState(false);
  const [aba, setAba] = useState<Aba>("faixa");
  const reqRef = useRef(0);

  function filtrosComJanela(): FiltrosEfetividade {
    const dias = janela === "outro" ? janelaOutro : janela;
    return dias === "" ? filtros : { ...filtros, dias_janela: Number(dias) };
  }

  const janelaInvalida =
    janela === "outro" && !(janelaOutro !== "" && Number(janelaOutro) >= 0 && Number(janelaOutro) <= 365);

  function aplicar() {
    if (janelaInvalida) return;
    setErro(null);
    setCarregando(true);
    const seq = ++reqRef.current;
    api
      .relatorioEfetividade(filtrosComJanela())
      .then((r) => seq === reqRef.current && setRelatorio(r))
      .catch((e) => seq === reqRef.current && setErro(mensagemErroSeta(e)))
      .finally(() => seq === reqRef.current && setCarregando(false));
  }

  async function exportar() {
    if (janelaInvalida) return;
    setExportando(true);
    setErro(null);
    try {
      await api.exportarEfetividade(filtrosComJanela());
    } catch (e) {
      setErro(mensagemErroSeta(e));
    } finally {
      setExportando(false);
    }
  }

  async function exportarClientes() {
    if (janelaInvalida) return;
    setExportandoClientes(true);
    setErro(null);
    try {
      await api.exportarEfetividadeClientes(filtrosComJanela());
    } catch (e) {
      setErro(mensagemErroSeta(e));
    } finally {
      setExportandoClientes(false);
    }
  }

  const paraOpcoes = (valores: string[] = []) => valores.map((v) => ({ value: v, label: v }));

  return (
    <div className="card">
      <div className="card-header">
        <div>
          <h3>Efetividade da cobrança</h3>
          <div className="card-subtitle">Das parcelas cobradas por WhatsApp, quantas foram pagas após o envio</div>
        </div>
        <div style={{ display: "flex", gap: 8 }}>
          <button type="button" className="secondary" onClick={exportar} disabled={exportando || janelaInvalida}>
            {exportando ? "Exportando..." : "Exportar Excel"}
          </button>
          <button
            type="button"
            className="secondary"
            onClick={exportarClientes}
            disabled={exportandoClientes || janelaInvalida}
          >
            {exportandoClientes ? "Exportando..." : "Exportar por cliente"}
          </button>
        </div>
      </div>

      <div className="form-row" style={{ flexWrap: "wrap" }}>
        <div className="field" style={{ flex: "1 1 160px" }}>
          <label htmlFor="efet-de">Enviado de</label>
          <input
            id="efet-de"
            type="date"
            value={filtros.cobrado_de ?? ""}
            onChange={(e) => setFiltros({ ...filtros, cobrado_de: e.target.value })}
          />
        </div>
        <div className="field" style={{ flex: "1 1 160px" }}>
          <label htmlFor="efet-ate">Enviado até</label>
          <input
            id="efet-ate"
            type="date"
            value={filtros.cobrado_ate ?? ""}
            onChange={(e) => setFiltros({ ...filtros, cobrado_ate: e.target.value })}
          />
        </div>
        <div className="field" style={{ flex: "1 1 200px" }}>
          <label htmlFor="efet-janela">Janela de pagamento</label>
          <select id="efet-janela" value={janela} onChange={(e) => setJanela(e.target.value)}>
            {JANELAS.map((j) => (
              <option key={j.value} value={j.value}>
                {j.label}
              </option>
            ))}
          </select>
        </div>
        {janela === "outro" && (
          <div className="field" style={{ flex: "0 1 120px" }}>
            <label htmlFor="efet-janela-dias">Dias (0–365)</label>
            <input
              id="efet-janela-dias"
              type="number"
              min={0}
              max={365}
              value={janelaOutro}
              onChange={(e) => setJanelaOutro(e.target.value)}
            />
          </div>
        )}
      </div>
      {janelaInvalida && <div className="field-hint">Informe uma janela entre 0 e 365 dias.</div>}

      <div className="form-row" style={{ flexWrap: "wrap" }}>
        <MultiSelect
          label="Faixa de atraso"
          options={paraOpcoes(opcoes.regras?.faixas)}
          value={filtros.faixa ?? []}
          onChange={(v) => setFiltros({ ...filtros, faixa: v })}
        />
        <MultiSelect
          label="Cluster"
          options={paraOpcoes(opcoes.regras?.clusters)}
          value={filtros.cluster ?? []}
          onChange={(v) => setFiltros({ ...filtros, cluster: v })}
        />
      </div>

      <CamposLoja
        valor={filtros}
        onChange={(v) => setFiltros({ ...filtros, ...v })}
        opcoes={opcoes}
        semClusterPopulacao
        idPrefixo="efet"
      />

      <div className="actions-row">
        <button type="button" onClick={aplicar} disabled={janelaInvalida}>
          Aplicar filtros
        </button>
        <button
          type="button"
          className="secondary"
          onClick={() => {
            setFiltros(FILTROS_PADRAO);
            setJanela("7");
          }}
        >
          Limpar
        </button>
      </div>

      <div className="abas" role="tablist" style={{ marginTop: 16 }}>
        <button
          type="button"
          role="tab"
          aria-selected={aba === "faixa"}
          className={aba === "faixa" ? "" : "secondary"}
          onClick={() => setAba("faixa")}
        >
          Por faixa de atraso
        </button>
        <button
          type="button"
          role="tab"
          aria-selected={aba === "loja"}
          className={aba === "loja" ? "" : "secondary"}
          onClick={() => setAba("loja")}
        >
          Por loja
        </button>
      </div>

      {erro && (
        <div className="error-box">
          <IconAlert width={16} height={16} />
          <span>{erro}</span>
        </div>
      )}
      {carregando && <div className="loading-state">Cruzando as parcelas cobradas com o ERP SETA...</div>}

      {relatorio && !carregando && (
        <>
          {relatorio.valor_a_pagar_brl !== null && (
            <div className="field-hint" style={{ marginBottom: 8 }}>
              Valor a pagar (Meta, conversas do período convertidas em BRL): {formatBRL(relatorio.valor_a_pagar_brl)}
            </div>
          )}
          {relatorio.leads_sem_parcelas > 0 && (
            <div className="field-hint" style={{ marginBottom: 8 }}>
              {relatorio.leads_sem_parcelas} lead(s) antigo(s) não entram no relatório (foram gerados antes do registro
              das parcelas).
            </div>
          )}
          {relatorio.total.clientes_cobrados === 0 ? (
            <div className="empty-state">
              <p>Nenhum lead enviado no período e filtros escolhidos.</p>
            </div>
          ) : (
            <div className="table-wrap">
              <table>
                <thead>
                  <tr>
                    {aba === "faixa" ? (
                      <th scope="col">Faixa</th>
                    ) : (
                      <>
                        <th scope="col">Loja</th>
                        <th scope="col">Regional</th>
                        <th scope="col">Cluster INAD</th>
                      </>
                    )}
                    {CABECALHO_METRICAS.map((c) => (
                      <th scope="col" key={c}>
                        {c}
                      </th>
                    ))}
                  </tr>
                </thead>
                <tbody>
                  {aba === "faixa"
                    ? relatorio.por_faixa.map((l) => (
                        <tr key={l.faixa}>
                          <td className="cell-strong">{l.faixa}</td>
                          <Metricas linha={l} />
                        </tr>
                      ))
                    : relatorio.por_loja.map((l) => (
                        <tr key={l.loja}>
                          <td className="cell-strong">{l.loja_nome ?? l.loja}</td>
                          <td>{l.regional ?? "—"}</td>
                          <td>
                            <BadgeClusterInad valor={l.cluster_inad} />
                          </td>
                          <Metricas linha={l} />
                        </tr>
                      ))}
                  <tr className="linha-total">
                    <td className="cell-strong" colSpan={aba === "faixa" ? 1 : 3}>
                      Total
                    </td>
                    <Metricas linha={relatorio.total} />
                  </tr>
                </tbody>
              </table>
            </div>
          )}
        </>
      )}
      {!relatorio && !carregando && !erro && (
        <div className="empty-state">
          <p>Aplique os filtros para ver quem pagou as parcelas cobradas.</p>
        </div>
      )}
    </div>
  );
}
