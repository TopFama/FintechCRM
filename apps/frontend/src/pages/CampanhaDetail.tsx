import { ChangeEvent, FormEvent, useEffect, useRef, useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import { api, Campanha, CampanhaIn, Faixa, FiltrosCobranca, mensagemErroSeta, PreviaCampanha } from "../api";
import BarraFiltrosCobranca, { FILTROS_COBRANCA_PADRAO } from "../components/BarraFiltrosCobranca";
import EnviosFaixa from "../components/EnviosFaixa";
import Paginacao, { LIMIT_OPCOES_PADRAO } from "../components/Paginacao";
import SortableTh from "../components/SortableTh";
import { useOpcoesCobranca } from "../components/useOpcoesCobranca";
import { formatBRL, formatCelular, formatData, formatDataHora } from "../format";
import { IconAlert, IconBolt, IconCheckCircle, IconEye, IconTrash, IconUpload } from "../icons";
import { SortDirection, useSort } from "../sort";
import { AcoesCampanha, periodoCampanha, situacaoCampanha } from "./Campanhas";

// Numa campanha, o padrão é pegar todos os dias da faixa e não aplicar a matriz
// do WhatsApp: quem entra é decidido pelos filtros da própria campanha.
const FILTROS_CAMPANHA_PADRAO: FiltrosCobranca = {
  ...FILTROS_COBRANCA_PADRAO,
  apenas_primeiro_dia: false,
  somente_regra_whatsapp: false,
};

const NOVA: CampanhaIn = {
  nome: "",
  ativa: false,
  data_inicio: null,
  data_fim: null,
  fonte_valores: "seta",
  recontato_dias: null,
  filtros: FILTROS_CAMPANHA_PADRAO,
};

type ColunaPrevia = "codigo" | "nome" | "cluster" | "faixa" | "dias_atraso" | "valor_cobrar";

function paraForm(c: Campanha): CampanhaIn {
  const filtros: FiltrosCobranca = { ...FILTROS_CAMPANHA_PADRAO };
  for (const [k, v] of Object.entries(c.filtros)) {
    (filtros as Record<string, unknown>)[k] = v === null ? "" : v;
  }
  return {
    nome: c.nome,
    ativa: c.ativa,
    data_inicio: c.data_inicio,
    data_fim: c.data_fim,
    fonte_valores: c.fonte_valores,
    recontato_dias: c.recontato_dias,
    filtros,
  };
}

// Campos vazios do formulário viram null (a API recusa data ou valor "").
function paraPayload(f: CampanhaIn): CampanhaIn {
  const filtros: Record<string, unknown> = {};
  for (const [k, v] of Object.entries(f.filtros)) filtros[k] = v === "" ? null : v;
  return {
    ...f,
    data_inicio: f.data_inicio || null,
    data_fim: f.data_fim || null,
    recontato_dias: f.recontato_dias || null,
    filtros: filtros as FiltrosCobranca,
  };
}

export default function CampanhaDetail() {
  const { id } = useParams<{ id: string }>();
  const nova = !id;
  const navigate = useNavigate();
  const opcoes = useOpcoesCobranca();
  const [campanha, setCampanha] = useState<Campanha | null>(null);
  const [faixa, setFaixa] = useState<Faixa | null>(null);
  const [form, setForm] = useState<CampanhaIn>(NOVA);
  const [erro, setErro] = useState<string | null>(null);
  const [sucesso, setSucesso] = useState<string | null>(null);
  const [salvando, setSalvando] = useState(false);
  const [enviandoPlanilha, setEnviandoPlanilha] = useState(false);
  // Na criação, a planilha fica guardada e sobe logo depois de criar a campanha.
  const [planilhaNova, setPlanilhaNova] = useState<File | null>(null);
  const planilhaRef = useRef<HTMLInputElement>(null);

  const [previa, setPrevia] = useState<PreviaCampanha | null>(null);
  const [carregandoPrevia, setCarregandoPrevia] = useState(false);
  const [previaOffset, setPreviaOffset] = useState(0);
  const [previaLimit, setPreviaLimit] = useState(LIMIT_OPCOES_PADRAO[1]);
  const previaSort = useSort<ColunaPrevia>(null, (chave, dir) => {
    setPreviaOffset(0);
    carregarPrevia(0, previaLimit, chave, dir);
  });
  const [executando, setExecutando] = useState(false);

  const alterado = !campanha || JSON.stringify(paraPayload(form)) !== JSON.stringify(paraPayload(paraForm(campanha)));

  function carregar() {
    if (!id) return;
    api
      .getCampanha(id)
      .then((c) => {
        setCampanha(c);
        setForm(paraForm(c));
        return api.getFaixa(c.faixa_id).then(setFaixa);
      })
      .catch((e) => setErro(e instanceof Error ? e.message : "Erro ao abrir a campanha"));
  }

  function recarregarCampanha() {
    if (!id) return;
    api
      .getCampanha(id)
      .then(setCampanha)
      .catch(() => undefined);
    if (campanha)
      api
        .getFaixa(campanha.faixa_id)
        .then(setFaixa)
        .catch(() => undefined);
  }

  useEffect(carregar, [id]);

  async function salvar(e: FormEvent) {
    e.preventDefault();
    setErro(null);
    setSucesso(null);
    setSalvando(true);
    try {
      if (nova) {
        const payload = paraPayload(form);
        if (!planilhaNova) {
          const criada = await api.criarCampanha(payload);
          navigate(`/campanhas/${criada.id}`, { replace: true });
          return;
        }
        // Cria sem ligar, sobe a planilha e só então aplica envio automático e fonte dos valores.
        const criada = await api.criarCampanha({
          ...payload,
          ativa: false,
          fonte_valores: "seta",
        });
        try {
          await api.subirClientesCampanha(criada.id, planilhaNova);
          if (payload.ativa || payload.fonte_valores !== "seta") await api.salvarCampanha(criada.id, payload);
        } catch (err) {
          navigate(`/campanhas/${criada.id}`, { replace: true });
          setErro(
            `Campanha criada, mas a planilha não foi aplicada: ${err instanceof Error ? err.message : "erro ao ler"}`,
          );
          return;
        }
        navigate(`/campanhas/${criada.id}`, { replace: true });
        return;
      }
      const salva = await api.salvarCampanha(id!, paraPayload(form));
      setCampanha(salva);
      setForm(paraForm(salva));
      setPrevia(null);
      setSucesso("Campanha salva.");
    } catch (err) {
      setErro(err instanceof Error ? err.message : "Erro ao salvar a campanha");
    } finally {
      setSalvando(false);
    }
  }

  async function subirPlanilha(e: ChangeEvent<HTMLInputElement>) {
    const arquivo = e.target.files?.[0];
    e.target.value = "";
    if (arquivo && nova) {
      setPlanilhaNova(arquivo);
      return;
    }
    if (!arquivo || !id) return;
    setErro(null);
    setSucesso(null);
    setEnviandoPlanilha(true);
    try {
      const r = await api.subirClientesCampanha(id, arquivo);
      setSucesso(
        `Planilha lida pela coluna ${r.coluna}: ${r.clientes} cliente(s)` +
          (r.ignoradas ? `, ${r.ignoradas} linha(s) sem cliente identificado.` : "."),
      );
      setPrevia(null);
      recarregarCampanha();
    } catch (err) {
      setErro(err instanceof Error ? err.message : "Erro ao ler a planilha");
    } finally {
      setEnviandoPlanilha(false);
    }
  }

  async function removerPlanilha() {
    if (!id || !window.confirm("Tirar a planilha de clientes? A campanha volta a usar só os filtros.")) return;
    try {
      await api.removerClientesCampanha(id);
      setForm((f) => ({ ...f, fonte_valores: "seta" }));
      setPrevia(null);
      recarregarCampanha();
    } catch (err) {
      setErro(err instanceof Error ? err.message : "Erro ao tirar a planilha");
    }
  }

  function carregarPrevia(
    offset: number = previaOffset,
    limit: number = previaLimit,
    sortBy: ColunaPrevia | null = previaSort.sortKey,
    sortDir: SortDirection = previaSort.sortDir,
  ) {
    if (!id) return;
    setErro(null);
    setCarregandoPrevia(true);
    api
      .previaCampanha(id, {
        limit,
        offset,
        sort_by: sortBy ?? undefined,
        sort_dir: sortDir,
      })
      .then(setPrevia)
      .catch((e) => setErro(mensagemErroSeta(e)))
      .finally(() => setCarregandoPrevia(false));
  }

  async function executar() {
    if (!id) return;
    if (
      !window.confirm("Colocar agora na fila quem entraria na campanha? Os envios saem dentro do horário de disparo.")
    )
      return;
    setErro(null);
    setSucesso(null);
    setExecutando(true);
    try {
      const r = await api.executarCampanha(id);
      setSucesso(`${r.na_fila} cliente(s) colocado(s) na fila (de ${r.encontrados} encontrado(s)).`);
      setPrevia(null);
      recarregarCampanha();
    } catch (err) {
      setErro(mensagemErroSeta(err));
    } finally {
      setExecutando(false);
    }
  }

  async function excluir() {
    if (!id || !campanha) return;
    if (!window.confirm(`Excluir a campanha "${campanha.nome}"? O histórico de envios continua nos relatórios.`))
      return;
    try {
      await api.excluirCampanha(id);
      navigate("/campanhas");
    } catch (err) {
      setErro(err instanceof Error ? err.message : "Erro ao excluir");
    }
  }

  if (!nova && !campanha) {
    return erro ? (
      <div>
        <Link to="/campanhas" className="back-link">
          ← Campanhas
        </Link>
        <div className="error-box">
          <IconAlert width={16} height={16} />
          <span>{erro}</span>
        </div>
      </div>
    ) : (
      <div className="loading-state">Carregando campanha...</div>
    );
  }

  const temPlanilha = (campanha?.clientes_total ?? 0) > 0;
  const temPlanilhaOuNova = temPlanilha || Boolean(planilhaNova);
  const colunasPrevia: [ColunaPrevia, string][] = [
    ["nome", "Cliente"],
    ["cluster", "Cluster"],
    ["faixa", "Faixa de atraso"],
    ["valor_cobrar", form.fonte_valores === "planilha" ? "Valor (planilha)" : "Valor a cobrar"],
  ];

  return (
    <div>
      <Link to="/campanhas" className="back-link">
        ← Campanhas
      </Link>
      <div className="page-header">
        <div>
          <h2>{nova ? "Nova campanha" : campanha!.nome}</h2>
          {campanha && (
            <div className="subtitle">
              {periodoCampanha(campanha)} · {campanha.enviados} enviada(s) · {campanha.pendentes} pendente(s) ·{" "}
              {campanha.erros} erro(s)
              {campanha.ultima_execucao &&
                ` · última busca ${formatDataHora(campanha.ultima_execucao)}: ${campanha.ultimo_resultado.na_fila ?? 0} na fila`}
            </div>
          )}
        </div>
        {campanha && (
          <div style={{ display: "flex", gap: 10, alignItems: "center" }}>
            <AcoesCampanha
              campanha={campanha}
              onAlterada={(c, mensagem) => {
                setErro(null);
                setSucesso(mensagem);
                setCampanha(c);
                setForm((f) => ({ ...f, ativa: c.ativa }));
              }}
              onErro={(m) => {
                setSucesso(null);
                setErro(m);
              }}
            />
            <span className={`status-pill ${situacaoCampanha(campanha).classe}`}>
              {situacaoCampanha(campanha).rotulo}
            </span>
          </div>
        )}
      </div>

      {erro && (
        <div className="error-box">
          <IconAlert width={16} height={16} />
          <span>{erro}</span>
        </div>
      )}
      {sucesso && (
        <div className="success-box">
          <IconCheckCircle width={16} height={16} />
          <span>{sucesso}</span>
        </div>
      )}

      <form onSubmit={salvar}>
        <div className="card">
          <div className="card-header">
            <h3>Quando roda</h3>
          </div>
          <div className="form-row" style={{ flexWrap: "wrap" }}>
            <div className="field" style={{ flex: "2 1 260px" }}>
              <label htmlFor="camp-nome">Nome da campanha</label>
              <input
                id="camp-nome"
                required
                maxLength={80}
                value={form.nome}
                onChange={(e) => setForm({ ...form, nome: e.target.value })}
                placeholder="ex. Feirão de outubro"
              />
            </div>
          </div>
          <label className="checkbox-row">
            <input
              type="checkbox"
              checked={form.ativa}
              onChange={(e) => setForm({ ...form, ativa: e.target.checked })}
            />
            Envio automático
          </label>
          <p className="field-hint" style={{ marginTop: 0 }}>
            {form.ativa
              ? `Todo dia de disparo dentro do período, antes do horário de início, a campanha coloca na fila quem passa nos ${
                  temPlanilhaOuNova ? "filtros e está na planilha" : "filtros"
                }. Para um dia só, use a mesma data no início e no fim.`
              : 'Desligado: a campanha só entra na fila quando você clicar em "Colocar na fila agora".'}
          </p>
          <div className="form-row" style={{ flexWrap: "wrap" }}>
            <div className="field" style={{ flex: "1 1 160px" }}>
              <label htmlFor="camp-inicio">Período: de</label>
              <input
                id="camp-inicio"
                type="date"
                value={form.data_inicio ?? ""}
                onChange={(e) => setForm({ ...form, data_inicio: e.target.value || null })}
              />
            </div>
            <div className="field" style={{ flex: "1 1 160px" }}>
              <label htmlFor="camp-fim">Até (vazio = sem data final)</label>
              <input
                id="camp-fim"
                type="date"
                value={form.data_fim ?? ""}
                onChange={(e) => setForm({ ...form, data_fim: e.target.value || null })}
              />
            </div>
            <div className="field" style={{ flex: "1 1 200px" }}>
              <label htmlFor="camp-recontato">Repetir para o mesmo cliente a cada (dias)</label>
              <input
                id="camp-recontato"
                type="number"
                min={1}
                max={365}
                value={form.recontato_dias ?? ""}
                onChange={(e) =>
                  setForm({
                    ...form,
                    recontato_dias: e.target.value ? Number(e.target.value) : null,
                  })
                }
              />
              <span className="field-hint">Vazio: cada cliente recebe uma vez na campanha.</span>
            </div>
          </div>
        </div>

        <div className="card">
          <div className="card-header">
            <h3>Quem recebe</h3>
          </div>
          <p className="card-subtitle">
            Só clientes em atraso no SETA. Os filtros são os mesmos da Cobrança. Continuam valendo a blacklist, as
            pausas e o limite de uma cobrança por cliente por dia.
          </p>
          <BarraFiltrosCobranca
            valor={form.filtros}
            onChange={(filtros) => setForm({ ...form, filtros })}
            opcoes={opcoes}
            idPrefixo="camp"
          />

          <div className="sub-card" style={{ marginTop: 16 }}>
            <h4>Planilha de clientes (opcional)</h4>
            <>
              <p className="field-hint">
                Com planilha, a campanha olha só para os clientes dela (coluna Codigo ou CPF), sempre cruzando com os
                filtros acima. Pode subir já na criação, para cobrar só quem está no Excel.
              </p>
              <div
                style={{
                  display: "flex",
                  gap: 10,
                  alignItems: "center",
                  flexWrap: "wrap",
                  marginBottom: 12,
                }}
              >
                <input
                  ref={planilhaRef}
                  type="file"
                  accept=".xlsx"
                  hidden
                  onChange={subirPlanilha}
                  aria-label="Planilha de clientes"
                />
                <button
                  type="button"
                  className="secondary small"
                  onClick={() => planilhaRef.current?.click()}
                  disabled={enviandoPlanilha}
                >
                  <IconUpload width={14} height={14} />{" "}
                  {enviandoPlanilha ? "Lendo..." : temPlanilhaOuNova ? "Trocar planilha" : "Subir planilha (.xlsx)"}
                </button>
                {planilhaNova && (
                  <>
                    <span className="text-muted">{planilhaNova.name} · será lida ao criar a campanha</span>
                    <button type="button" className="danger small" onClick={() => setPlanilhaNova(null)}>
                      <IconTrash width={14} height={14} /> Tirar planilha
                    </button>
                  </>
                )}
                {temPlanilha && (
                  <>
                    <span className="text-muted">
                      {campanha!.clientes_arquivo} · {campanha!.clientes_total} cliente(s)
                    </span>
                    <button type="button" className="danger small" onClick={removerPlanilha}>
                      <IconTrash width={14} height={14} /> Tirar planilha
                    </button>
                  </>
                )}
              </div>
              <div className="field" style={{ maxWidth: 420 }}>
                <label htmlFor="camp-fonte">Valor, celular e variáveis vêm</label>
                <select
                  id="camp-fonte"
                  value={form.fonte_valores}
                  disabled={!temPlanilhaOuNova}
                  onChange={(e) =>
                    setForm({
                      ...form,
                      fonte_valores: e.target.value as CampanhaIn["fonte_valores"],
                    })
                  }
                >
                  <option value="seta">Do SETA (atualizados no dia)</option>
                  <option value="planilha">Da planilha (colunas Valor e Celular)</option>
                </select>
                {form.fonte_valores === "planilha" && (
                  <span className="field-hint">
                    As outras colunas da planilha podem alimentar as variáveis do template, abaixo.
                  </span>
                )}
              </div>
            </>
          </div>
        </div>

        <div className="actions-row" style={{ marginBottom: 16 }}>
          <button type="submit" disabled={salvando || (!nova && !alterado)}>
            {salvando ? "Salvando..." : nova ? "Criar campanha" : "Salvar"}
          </button>
          {!nova && alterado && <span className="field-hint">Há alterações não salvas.</span>}
          {!nova && (
            <button type="button" className="danger" style={{ marginLeft: "auto" }} onClick={excluir}>
              <IconTrash width={16} height={16} /> Excluir campanha
            </button>
          )}
        </div>
      </form>

      {faixa && campanha && (
        <EnviosFaixa
          faixa={faixa}
          onAlterado={recarregarCampanha}
          rotuloAlvo="desta campanha"
          titulo="Template e número da campanha"
          descricao="O template usado por esta campanha e o número que envia. Com mais de um número, a fila é dividida entre eles e ninguém recebe duas vezes."
          colunasPlanilha={campanha.fonte_valores === "planilha" ? campanha.planilha_colunas : []}
        />
      )}

      {campanha && (
        <div className="card">
          <div className="card-header">
            <h3>Quem entraria agora</h3>
            <div style={{ display: "flex", gap: 8, flexWrap: "wrap" }}>
              <button
                type="button"
                className="secondary"
                onClick={() => {
                  setPreviaOffset(0);
                  carregarPrevia(0);
                }}
                disabled={carregandoPrevia || alterado}
              >
                <IconEye width={16} height={16} /> {carregandoPrevia ? "Consultando o SETA..." : "Ver prévia"}
              </button>
              <button
                type="button"
                onClick={executar}
                disabled={executando || alterado || campanha.envios_ativos === 0}
                title={campanha.envios_ativos === 0 ? "Atribua um template antes" : undefined}
              >
                <IconBolt width={16} height={16} /> {executando ? "Colocando na fila..." : "Colocar na fila agora"}
              </button>
            </div>
          </div>
          <p className="card-subtitle">
            A prévia não coloca ninguém na fila. Quem já recebeu desta campanha não aparece.
            {alterado && " Salve as alterações para ver a prévia com a configuração nova."}
          </p>
          {previa && (
            <>
              <p className="card-subtitle">
                {previa.total} cliente(s) entrariam, de {previa.total_base} na base filtrada.
              </p>
              {previa.itens.length > 0 && (
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
                            onSort={() => previaSort.toggleSort(chave)}
                          >
                            {rotulo}
                          </SortableTh>
                        ))}
                        <th scope="col">Celular</th>
                        <th scope="col">Venc. mais antigo</th>
                      </tr>
                    </thead>
                    <tbody>
                      {previa.itens.map((c) => (
                        <tr key={c.codigo}>
                          <td>
                            {c.codigo} · {c.nome}
                          </td>
                          <td>{c.cluster || "—"}</td>
                          <td>
                            {c.faixa ?? "—"} ({c.dias_atraso} dias)
                          </td>
                          <td>{formatBRL(c.valor_cobrar)}</td>
                          <td>{formatCelular(c.celular)}</td>
                          <td>{formatData(c.vencimento_mais_antigo)}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              )}
              {previa.total > 0 && (
                <Paginacao
                  total={previa.total}
                  limit={previaLimit}
                  offset={previaOffset}
                  onChange={(o) => {
                    setPreviaOffset(o);
                    carregarPrevia(o);
                  }}
                  onLimitChange={(n) => {
                    setPreviaLimit(n);
                    setPreviaOffset(0);
                    carregarPrevia(0, n);
                  }}
                />
              )}
            </>
          )}
          {faixa && (
            <p className="field-hint" style={{ marginTop: 12 }}>
              A fila e os envios desta campanha aparecem em <Link to={`/faixas/${faixa.id}`}>detalhes da fila</Link> e
              em <Link to="/relatorios">Relatórios</Link>.
            </p>
          )}
        </div>
      )}
    </div>
  );
}
