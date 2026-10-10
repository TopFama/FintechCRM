import { useState } from "react";
import { api, foiCancelada, mensagemErroSeta, FiltrosEfetividade, LinhaEfetividade, RelatorioEfetividade } from "../../api";
import { formatBRL, formatDataHora, formatPercentual, formatRoas } from "../../format";
import { IconAlert } from "../../icons";
import { useSetaFora } from "../AvisoSetaFora";
import CamposLoja from "../CamposLoja";
import DicaIndicador from "../DicaIndicador";
import MultiSelect from "../MultiSelect";
import SelectCampanha from "../SelectCampanha";
import SelectJanelaPagamento from "../SelectJanelaPagamento";
import { OpcoesCobranca, opcoesCluster } from "../useOpcoesCobranca";
import { useRequisicaoUnica } from "../useRequisicaoUnica";
import SortableTh from "../SortableTh";
import TabelaAjustavel from "../TabelaAjustavel";
import { ordemFaixaFn, ordenarPor, SortDirection, useSort } from "../../sort";

type Aba = "faixa" | "loja" | "campanha";

const FILTROS_PADRAO: FiltrosEfetividade = {
  cobrado_de: "",
  cobrado_ate: "",
  faixa: [],
  cluster: [],
  loja: [],
  regional: [],
  estado: [],
  cluster_inad: [],
  cobradora: [],
  campanha: "",
};

function semAcento(texto: string): string {
  return texto.normalize("NFD").replace(/\p{Diacritic}/gu, "").toUpperCase();
}

// Formatação condicional do cluster de inadimplência da loja: mesmas cores da
// planilha de lojas (TOP azul, UTI vermelho, UTI + roxo)
export function BadgeClusterInad({ valor }: { valor: string | null }) {
  if (!valor) return <span className="text-faint">—</span>;
  const t = semAcento(valor).replace(/\s+/g, " ").trim();
  const tom =
    t === "CLUSTER TOP"
      ? "top"
      : t === "CLUSTER UTI +"
        ? "uti-mais"
        : t === "CLUSTER UTI"
          ? "uti"
          : t.includes("ALT")
            ? "alto"
            : t.includes("MED")
              ? "medio"
              : t.includes("BAIX")
                ? "baixo"
                : "neutro";
  return <span className={`badge cluster-inad-${tom}`}>{valor}</span>;
}

type ColunaMetrica = "qtd_envios" | "clientes_cobrados" | "clientes_pagaram" | "conversao_clientes" | "valor_pago" | "roas";
type Coluna = ColunaMetrica | "faixa" | "campanha" | "loja" | "loja_nome" | "regional" | "cluster_inad";

function Metricas({ linha }: { linha: LinhaEfetividade }) {
  return (
    <>
      <td>{linha.qtd_envios.toLocaleString("pt-BR")}</td>
      <td>{linha.clientes_cobrados.toLocaleString("pt-BR")}</td>
      <td>{linha.clientes_pagaram.toLocaleString("pt-BR")}</td>
      <td>{formatPercentual(linha.conversao_clientes)}</td>
      <td>{formatBRL(linha.valor_pago)}</td>
      <td>{formatRoas(linha.roas)}</td>
    </>
  );
}

const CABECALHO_METRICAS: [ColunaMetrica, string][] = [
  ["qtd_envios", "Qtd. de envios"],
  ["clientes_cobrados", "Clientes cobrados"],
  ["clientes_pagaram", "Clientes pagou"],
  ["conversao_clientes", "% Conv."],
  ["valor_pago", "Recebimento"],
  ["roas", "ROAS"],
];

// Texto do ícone de info, só nas colunas que precisam de explicação
const DICAS: Partial<Record<Coluna, { texto: string; formula: string }>> = {
  roas: {
    texto:
      "Quanto voltou em pagamento (Recebimento) para cada R$ 1 gasto com WhatsApp nos envios desta linha. O custo de cada dia na Meta é dividido pelas mensagens enviadas no dia.",
    formula: "Recebimento ÷ Custo do WhatsApp dos envios da linha",
  },
};

const COLUNAS_LOJA: [Coluna, string][] = [
  ["loja", "Código"],
  ["loja_nome", "Loja"],
  ["regional", "Regional"],
  ["cluster_inad", "Cluster INAD"],
];

export default function EfetividadeCard({ opcoes }: { opcoes: OpcoesCobranca }) {
  const [filtros, setFiltros] = useState<FiltrosEfetividade>(FILTROS_PADRAO);
  const [janela, setJanela] = useState<string | null>("7");
  const [relatorio, setRelatorio] = useState<RelatorioEfetividade | null>(null);
  const setaFora = useSetaFora();
  const [erro, setErro] = useState<string | null>(null);
  const [carregando, setCarregando] = useState(false);
  const [exportando, setExportando] = useState(false);
  const [exportandoClientes, setExportandoClientes] = useState(false);
  const [aba, setAba] = useState<Aba>("faixa");
  const novaRequisicao = useRequisicaoUnica();
  // o relatório vem inteiro (sem paginação): ordenar na tela cobre o resultado todo e não reconsulta o SETA
  const ordenacao = useSort<Coluna>(null);
  const ordemFaixa = ordemFaixaFn(opcoes.regras?.faixas);

  function ordenar<T extends LinhaEfetividade>(linhas: T[]): T[] {
    const chave = ordenacao.sortKey;
    if (!chave) return linhas;
    return ordenarPor(
      linhas,
      (l) => {
        const v = (l as unknown as Record<string, string | number | null>)[chave];
        if (chave === "faixa") return ordemFaixa(v as string);
        if (chave === "conversao_clientes" || chave === "valor_pago" || chave === "roas") return v == null ? null : Number(v);
        return typeof v === "string" ? v.toUpperCase() : v;
      },
      ordenacao.sortDir
    );
  }

  function filtrosComJanela(): FiltrosEfetividade {
    return janela ? { ...filtros, dias_janela: Number(janela) } : filtros;
  }

  const janelaInvalida = janela === null;

  function comOrdenacao(f: FiltrosEfetividade, sortBy: Coluna | null, sortDir: SortDirection): FiltrosEfetividade {
    return sortBy ? { ...f, sort_by: sortBy, sort_dir: sortDir } : f;
  }

  function aplicar() {
    if (janelaInvalida) return;
    const f = filtrosComJanela();
    setErro(null);
    setCarregando(true);
    const signal = novaRequisicao();
    api
      .relatorioEfetividade(f, signal)
      .then(setRelatorio)
      .catch((e) => !foiCancelada(e) && setErro(mensagemErroSeta(e)))
      .finally(() => !signal.aborted && setCarregando(false));
  }

  async function exportar() {
    if (janelaInvalida) return;
    setExportando(true);
    setErro(null);
    try {
      await api.exportarEfetividade(comOrdenacao(filtrosComJanela(), ordenacao.sortKey, ordenacao.sortDir));
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
        <SelectJanelaPagamento id="efet-janela" valor={janela} onChange={setJanela} />
      </div>

      <div className="form-row" style={{ flexWrap: "wrap" }}>
        <MultiSelect
          label="Faixa de atraso"
          options={paraOpcoes(opcoes.regras?.faixas)}
          value={filtros.faixa ?? []}
          onChange={(v) => setFiltros({ ...filtros, faixa: v })}
        />
        <MultiSelect
          label="Cluster"
          options={opcoesCluster(opcoes.regras)}
          value={filtros.cluster ?? []}
          onChange={(v) => setFiltros({ ...filtros, cluster: v })}
        />
        <SelectCampanha
          id="efet-campanha"
          value={filtros.campanha ?? ""}
          enviadoDe={filtros.cobrado_de || undefined}
          enviadoAte={filtros.cobrado_ate || undefined}
          onChange={(v) => setFiltros({ ...filtros, campanha: v })}
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
        <button type="button" onClick={aplicar} disabled={janelaInvalida || carregando}>
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
        <button
          type="button"
          role="tab"
          aria-selected={aba === "campanha"}
          className={aba === "campanha" ? "" : "secondary"}
          onClick={() => setAba("campanha")}
        >
          Por campanha
        </button>
      </div>

      {erro && (
        <div className="error-box">
          <IconAlert width={16} height={16} />
          <span>{erro}</span>
        </div>
      )}
      {carregando && <div className="loading-state">Cruzando as parcelas cobradas com o SETA...</div>}

      {relatorio && !carregando && (
        <>
          {relatorio.desatualizado && (
            <div className="field-hint" style={{ marginBottom: 8 }}>
              {setaFora
                ? `Sem conexão com o SETA: dados de ${formatDataHora(relatorio.gerado_em)}.`
                : `Dados do SETA de ${formatDataHora(relatorio.gerado_em)}: o relatório está sendo atualizado. Aplique de novo daqui a pouco.`}
            </div>
          )}
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
            <TabelaAjustavel id="efetividade" rotulo="Efetividade">
              <table>
                <thead>
                  <tr>
                    {(aba === "faixa"
                      ? ([["faixa", "Faixa"]] as [Coluna, string][])
                      : aba === "campanha"
                        ? ([["campanha", "Campanha"]] as [Coluna, string][])
                        : COLUNAS_LOJA
                    )
                      .concat(CABECALHO_METRICAS)
                      .map(([coluna, rotulo]) => (
                        <SortableTh
                          scope="col"
                          key={coluna}
                          active={ordenacao.sortKey === coluna}
                          dir={ordenacao.sortDir}
                          onSort={() => ordenacao.toggleSort(coluna)}
                        >
                          {rotulo}
                          {DICAS[coluna] && (
                            <DicaIndicador titulo={rotulo} texto={DICAS[coluna].texto} formula={DICAS[coluna].formula} />
                          )}
                        </SortableTh>
                      ))}
                  </tr>
                </thead>
                <tbody>
                  {aba === "faixa"
                    ? ordenar(relatorio.por_faixa).map((l) => (
                        <tr key={l.faixa}>
                          <td className="cell-strong">{l.faixa}</td>
                          <Metricas linha={l} />
                        </tr>
                      ))
                    : aba === "campanha"
                      ? ordenar(relatorio.por_campanha ?? []).map((l) => (
                          <tr key={l.campanha_id || "regua"}>
                            <td className="cell-strong">{l.campanha}</td>
                            <Metricas linha={l} />
                          </tr>
                        ))
                      : ordenar(relatorio.por_loja).map((l) => (
                          <tr key={l.loja}>
                            <td className="cell-strong">{l.loja}</td>
                            <td>{l.loja_nome ?? "—"}</td>
                            <td>{l.regional ?? "—"}</td>
                            <td>
                              <BadgeClusterInad valor={l.cluster_inad} />
                            </td>
                            <Metricas linha={l} />
                          </tr>
                        ))}
                  <tr className="linha-total">
                    <td className="cell-strong" colSpan={aba === "loja" ? 4 : 1}>
                      Total
                    </td>
                    <Metricas linha={relatorio.total} />
                  </tr>
                </tbody>
              </table>
            </TabelaAjustavel>
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
