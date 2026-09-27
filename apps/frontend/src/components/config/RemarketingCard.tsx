import { FormEvent, useEffect, useState } from "react";
import { Link } from "react-router-dom";
import EnviosFaixa from "../EnviosFaixa";
import { api, Faixa, pareceAdmin, PreviaRemarketing, SegmentoRemarketing, SegmentoRemarketingIn } from "../../api";
import { formatBRL, formatCelular, formatData, formatDataHora } from "../../format";
import { IconAlert, IconEye, IconRefresh } from "../../icons";
import FiltroPeriodo, { Periodo } from "../FiltroPeriodo";
import MultiSelect from "../MultiSelect";
import Paginacao from "../Paginacao";
import SortableTh from "../SortableTh";
import { ordenarPor, useSort } from "../../sort";
import CampoValorMaximo from "../CampoValorMaximo";
import { opcoesCluster, useOpcoesCobranca } from "../useOpcoesCobranca";

// Remarketing de quem desistiu no portal Renegocie (aba de Campanhas). Cada
// segmento tem o próprio número + template e filtros que decidem quem entra.
export default function RemarketingCard() {
  const [segmentos, setSegmentos] = useState<SegmentoRemarketing[]>([]);
  const [erro, setErro] = useState<string | null>(null);
  const [executando, setExecutando] = useState(false);
  const [sucesso, setSucesso] = useState<string | null>(null);
  const admin = pareceAdmin();

  function carregar() {
    api
      .segmentosRemarketing()
      .then(setSegmentos)
      .catch((e) => setErro(e instanceof Error ? e.message : "Erro ao carregar o remarketing"));
  }

  useEffect(carregar, []);

  async function executar() {
    setErro(null);
    setSucesso(null);
    setExecutando(true);
    try {
      const r = await api.executarRemarketing();
      const total = Object.values(r).reduce((soma, s) => soma + s.na_fila, 0);
      setSucesso(
        Object.keys(r).length === 0
          ? "Nenhum segmento ligado."
          : `${total} cliente(s) colocado(s) na fila de disparo.`,
      );
      carregar();
    } catch (e) {
      setErro(e instanceof Error ? e.message : "Erro ao buscar agora");
    } finally {
      setExecutando(false);
    }
  }

  return (
    <>
      <div className="card">
        <div className="card-header">
          <h3>Remarketing do Renegocie</h3>
          {admin && (
            <button type="button" className="secondary" onClick={executar} disabled={executando}>
              <IconRefresh width={16} height={16} />
              {executando ? "Buscando..." : "Buscar agora"}
            </button>
          )}
        </div>
        {erro && (
          <div className="error-box">
            <IconAlert width={16} height={16} />
            <span>{erro}</span>
          </div>
        )}
        {sucesso && <div className="success-box">{sucesso}</div>}
      </div>
      {segmentos.map((s) => (
        <SegmentoForm
          key={s.segmento}
          segmento={s}
          podeEditar={admin}
          onSalvo={(novo) => setSegmentos((lista) => lista.map((x) => (x.segmento === novo.segmento ? novo : x)))}
          onEnviosAlterados={carregar}
        />
      ))}
    </>
  );
}

type ClientePrevia = PreviaRemarketing["clientes"][number];
type ColunaPrevia =
  | "nome"
  | "celular"
  | "cluster"
  | "faixa"
  | "valor_cobrar"
  | "evento_em"
  | "proposta"
  | "entrada_vencimento";

// Rótulo da data do evento em cada segmento
const ROTULO_EVENTO: Record<string, string> = {
  SO_IDENTIFICOU: "Identificou-se em",
  VIU_PROPOSTA: "Simulou em",
  ACORDO_ATIVO: "Lançado em",
};

function colunasDaPrevia(segmento: string): [ColunaPrevia, string][] {
  const colunas: [ColunaPrevia, string][] = [
    ["nome", "Cliente"],
    ["celular", "Celular"],
    ["cluster", "Cluster"],
    ["faixa", "Faixa"],
    ["valor_cobrar", "Valor a cobrar"],
    ["evento_em", ROTULO_EVENTO[segmento] ?? "Data"],
    ["proposta", "Proposta"],
  ];
  if (segmento === "ACORDO_ATIVO") colunas.push(["entrada_vencimento", "Entrada venceu em"]);
  return colunas;
}

function paraForm(s: SegmentoRemarketing): SegmentoRemarketingIn {
  return {
    ativo: s.ativo,
    janela_dias: s.janela_dias,
    recontato_dias: s.recontato_dias,
    cobradoras: s.cobradoras,
    faixas_atraso: s.faixas_atraso,
    clusters: s.clusters,
    valor_min: s.valor_min,
    valor_max: s.valor_max,
  };
}

function SegmentoForm({
  segmento,
  podeEditar,
  onSalvo,
  onEnviosAlterados,
}: {
  segmento: SegmentoRemarketing;
  podeEditar: boolean;
  onSalvo: (s: SegmentoRemarketing) => void;
  onEnviosAlterados: () => void;
}) {
  const opcoes = useOpcoesCobranca();
  const [form, setForm] = useState<SegmentoRemarketingIn>(() => paraForm(segmento));
  const [erro, setErro] = useState<string | null>(null);
  const [salvo, setSalvo] = useState(false);
  const [salvando, setSalvando] = useState(false);
  const [previa, setPrevia] = useState<PreviaRemarketing | null>(null);
  const [carregandoPrevia, setCarregandoPrevia] = useState(false);
  const [previaOffset, setPreviaOffset] = useState(0);
  const [previaLimit, setPreviaLimit] = useState(25);
  const previaSort = useSort<ColunaPrevia>("evento_em");
  const [periodoPrevia, setPeriodoPrevia] = useState<Periodo>({});
  const temPeriodo = Boolean(periodoPrevia.de || periodoPrevia.ate);
  const acordo = segmento.segmento === "ACORDO_ATIVO";
  const id = segmento.segmento.toLowerCase();
  const alterado = JSON.stringify(form) !== JSON.stringify(paraForm(segmento));
  const chavePrevia = previaSort.sortKey;
  const valorPrevia: ((c: ClientePrevia) => string | number | null) | null = !chavePrevia
    ? null
    : chavePrevia === "faixa"
      ? (c) => c.dias_atraso
      : chavePrevia === "valor_cobrar"
        ? (c) => Number(c.valor_cobrar)
        : (c) => (c[chavePrevia] ?? null) as string | null;
  const clientesPrevia = previa ? previa.clientes : [];
  const paginaPrevia = ordenarPor(clientesPrevia, valorPrevia, previaSort.sortDir).slice(
    previaOffset,
    previaOffset + previaLimit,
  );
  const colunasPrevia = colunasDaPrevia(segmento.segmento);

  useEffect(() => setForm(paraForm(segmento)), [segmento]);

  // Número e template do segmento ficam aqui mesmo, não na lista de faixas de atraso.
  const [faixa, setFaixa] = useState<Faixa | null>(null);
  const carregarFaixa = () => {
    api.getFaixa(segmento.faixa_id).then(setFaixa).catch(() => undefined);
  };
  useEffect(carregarFaixa, [segmento.faixa_id]);

  async function salvar(e: FormEvent) {
    e.preventDefault();
    setErro(null);
    setSalvo(false);
    setSalvando(true);
    try {
      onSalvo(
        await api.salvarSegmentoRemarketing(segmento.segmento, {
          ...form,
          valor_min: form.valor_min || null,
          valor_max: form.valor_max || null,
        }),
      );
      setSalvo(true);
    } catch (err) {
      setErro(err instanceof Error ? err.message : "Erro ao salvar");
    } finally {
      setSalvando(false);
    }
  }

  async function verPrevia() {
    setErro(null);
    setCarregandoPrevia(true);
    try {
      setPrevia(await api.previaRemarketing(segmento.segmento, periodoPrevia));
      setPreviaOffset(0);
    } catch (err) {
      setErro(err instanceof Error ? err.message : "Erro ao gerar a prévia");
    } finally {
      setCarregandoPrevia(false);
    }
  }

  const resultado = segmento.ultimo_resultado;
  return (
    <div className="card">
      <div className="card-header">
        <h3>{segmento.nome}</h3>
        <span className={`status-pill ${segmento.ativo ? "on" : "off"}`} style={{ fontSize: 14 }}>
          {segmento.ativo ? "Ligado" : "Desligado"}
        </span>
      </div>
      <p className="card-subtitle">{segmento.descricao}</p>
      <p className="card-subtitle">
        <Link to={`/faixas/${segmento.faixa_id}`}>Ver a fila</Link>.{" "}
        {segmento.ultima_execucao
          ? `Última busca em ${formatDataHora(segmento.ultima_execucao)}: ${resultado.encontrados ?? 0} encontrado(s), ${resultado.na_fila ?? 0} na fila.`
          : "Ainda não rodou."}
      </p>
      {segmento.envios_ativos === 0 && (
        <div className="error-box">
          <IconAlert width={16} height={16} />
          <span>Ainda sem número e template: vincule logo abaixo, senão ninguém recebe.</span>
        </div>
      )}
      {erro && (
        <div className="error-box">
          <IconAlert width={16} height={16} />
          <span>{erro}</span>
        </div>
      )}
      {faixa && (
        <EnviosFaixa
          faixa={faixa}
          onAlterado={() => {
            carregarFaixa();
            onEnviosAlterados();
          }}
          rotuloAlvo="deste segmento"
          titulo="Templates deste segmento"
          descricao={null}
          embutido
        />
      )}

      {salvo && !alterado && <div className="success-box">Configuração salva.</div>}

      <h4 style={{ marginTop: 16 }}>Quem entra neste segmento</h4>
      <form onSubmit={salvar}>
        <fieldset disabled={!podeEditar} style={{ border: 0, padding: 0, margin: 0 }}>
          <label style={{ display: "flex", alignItems: "center", gap: 8, marginBottom: 12 }}>
            <input
              type="checkbox"
              checked={form.ativo}
              onChange={(e) => setForm({ ...form, ativo: e.target.checked })}
            />
            Enviar remarketing para este segmento
          </label>
          <div className="form-row">
            <div className="field">
              <label htmlFor={`${id}-janela`}>Desistiu há no máximo (dias)</label>
              <input
                id={`${id}-janela`}
                type="number"
                min={1}
                max={180}
                required
                value={form.janela_dias}
                onChange={(e) => setForm({ ...form, janela_dias: Number(e.target.value) })}
              />
            </div>
            <div className="field">
              <label htmlFor={`${id}-recontato`}>Recontatar a cada (dias)</label>
              <input
                id={`${id}-recontato`}
                type="number"
                min={1}
                max={365}
                required
                value={form.recontato_dias}
                onChange={(e) => setForm({ ...form, recontato_dias: Number(e.target.value) })}
              />
            </div>
          </div>
          <div className="form-row">
            <MultiSelect
              id={`${id}-faixas`}
              label="Faixas de atraso"
              options={(opcoes.regras?.faixas ?? []).map((f) => ({ value: f, label: f }))}
              value={form.faixas_atraso}
              onChange={(v) => setForm({ ...form, faixas_atraso: v })}
              placeholder="Todas"
            />
            <MultiSelect
              id={`${id}-clusters`}
              label="Clusters"
              options={opcoesCluster(opcoes.regras)}
              value={form.clusters}
              onChange={(v) => setForm({ ...form, clusters: v })}
              placeholder="Todos"
            />
            <MultiSelect
              id={`${id}-cobradoras`}
              label="Cobradora"
              options={opcoes.cobradoras}
              value={form.cobradoras}
              onChange={(v) => setForm({ ...form, cobradoras: v })}
              placeholder="Todas"
            />
          </div>
          <div className="form-row">
            <div className="field">
              <label htmlFor={`${id}-valor-min`}>Valor a cobrar mínimo (R$)</label>
              <input
                id={`${id}-valor-min`}
                type="number"
                min={0}
                step="0.01"
                value={form.valor_min ?? ""}
                onChange={(e) => setForm({ ...form, valor_min: e.target.value || null })}
              />
            </div>
            <div className="field">
              <CampoValorMaximo
                id={`${id}-valor-max`}
                label="Valor a cobrar máximo (R$)"
                value={form.valor_max ?? ""}
                onChange={(v) => setForm({ ...form, valor_max: v || null })}
              />
            </div>
          </div>
        </fieldset>
        <div className="field" style={{ marginBottom: 12 }}>
          <FiltroPeriodo
            opcoes={["hoje", "7dias", "mes", "personalizado"]}
            inicial={null}
            permiteLimpar
            onChange={setPeriodoPrevia}
          />
        </div>
        <div style={{ display: "flex", gap: 10, flexWrap: "wrap" }}>
          {podeEditar && (
            <button type="submit" disabled={salvando || !alterado}>
              {salvando ? "Salvando..." : "Salvar"}
            </button>
          )}
          <button type="button" className="secondary" onClick={verPrevia} disabled={carregandoPrevia || alterado}>
            <IconEye width={16} height={16} />
            {carregandoPrevia ? "Consultando..." : temPeriodo ? "Ver clientes do período" : "Ver quem entraria hoje"}
          </button>
          {alterado && <span className="field-hint">Salve para ver a prévia com os filtros novos.</span>}
        </div>
      </form>

      {previa && (
        <div style={{ marginTop: 16 }}>
          <p className="card-subtitle">
            {previa.total} de {previa.total_renegocie} cliente(s) do Renegocie passam nos filtros
            {acordo ? " (acordos com a entrada vencida e em aberto no SETA)" : ""}.
          </p>
          {clientesPrevia.length > 0 && (
            <div className="table-wrap">
              <table>
                <thead>
                  <tr>
                    {colunasPrevia.map(([chave, rotulo]) => (
                      <SortableTh
                        key={chave}
                        scope="col"
                        active={previaSort.sortKey === chave}
                        dir={previaSort.sortDir}
                        onSort={() => {
                          previaSort.toggleSort(chave);
                          setPreviaOffset(0);
                        }}
                      >
                        {rotulo}
                      </SortableTh>
                    ))}
                  </tr>
                </thead>
                <tbody>
                  {paginaPrevia.map((c) => (
                    <tr key={c.codigo}>
                      <td>
                        {c.codigo} · {c.nome}
                      </td>
                      <td>{formatCelular(c.celular)}</td>
                      <td>{c.cluster || "—"}</td>
                      <td>
                        {c.faixa ?? "—"} ({c.dias_atraso} dias)
                      </td>
                      <td>{formatBRL(c.valor_cobrar)}</td>
                      <td>{formatDataHora(c.evento_em)}</td>
                      <td>{c.proposta ?? "—"}</td>
                      {acordo && <td>{c.entrada_vencimento ? formatData(c.entrada_vencimento) : "—"}</td>}
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
          {clientesPrevia.length > 0 && (
            <Paginacao
              total={clientesPrevia.length}
              limit={previaLimit}
              offset={previaOffset}
              onChange={setPreviaOffset}
              onLimitChange={(n) => {
                setPreviaLimit(n);
                setPreviaOffset(0);
              }}
            />
          )}
        </div>
      )}
    </div>
  );
}
