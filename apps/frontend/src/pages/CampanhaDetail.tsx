import { ChangeEvent, FormEvent, useEffect, useRef, useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import { api, Campanha, CampanhaIn, Faixa, FiltrosCobranca, foiCancelada, mensagemErroSeta, PreviaCampanha } from "../api";
import BarraFiltrosCobranca, { FILTROS_COBRANCA_PADRAO } from "../components/BarraFiltrosCobranca";
import AvisosCategoria from "../components/AvisosCategoria";
import EnviosFaixa from "../components/EnviosFaixa";
import Paginacao, { LIMIT_OPCOES_PADRAO } from "../components/Paginacao";
import SortableTh from "../components/SortableTh";
import { useOpcoesCobranca } from "../components/useOpcoesCobranca";
import { useRequisicaoUnica } from "../components/useRequisicaoUnica";
import { formatBRL, formatCelular, formatData, formatDataHora } from "../format";
import { IconAlert, IconBolt, IconCheckCircle, IconEye, IconTrash, IconUpload } from "../icons";
import ModalDecisaoVariaveis from "../components/ModalDecisaoVariaveis";
import { ColunaEmBranco } from "../api";
import { SortDirection, useSort } from "../sort";
import { AcoesCampanha, criadoEm, periodoCampanha, situacaoCampanha } from "./Campanhas";

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
  todos_da_planilha: false,
  incluir_cobrados_hoje: false,
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
    todos_da_planilha: c.todos_da_planilha,
    incluir_cobrados_hoje: c.incluir_cobrados_hoje,
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
  const [avisosCategoria, setAvisosCategoria] = useState<string[]>([]);
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
  const [colunasEmBranco, setColunasEmBranco] = useState<ColunaEmBranco[]>([]);
  const [pendentesPlanilha, setPendentesPlanilha] = useState<Record<string, number>>({});
  const [completadosSeta, setCompletadosSeta] = useState<Record<string, number>>({});

  const alterado = !campanha || JSON.stringify(paraPayload(form)) !== JSON.stringify(paraPayload(paraForm(campanha)));

  function carregar() {
    if (!id) return;
    api
      .getCampanha(id)
      .then((c) => {
        setCampanha(c);
        if (c.clientes_arquivo) {
          api.getColunasEmBrancoCampanha(id).then(cb => { if (cb.length > 0) setColunasEmBranco(cb); }).catch(() => {});
        }
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
        `Planilha lida pela coluna ${r.coluna}: ${r.clientes} cliente(s) válidos` +
          (r.ignoradas ? `, ${r.ignoradas} linha(s) sem cliente identificado.` : ".")
      );
      setPendentesPlanilha(r.pendentes || {});
      setCompletadosSeta(r.completados_pelo_seta || {});
      if (r.colunas_em_branco && r.colunas_em_branco.length > 0) {
        setColunasEmBranco(r.colunas_em_branco);
      }
      setPrevia(null);
      recarregarCampanha();
    } catch (err) {
      setErro(err instanceof Error ? err.message : "Erro ao ler a planilha");
    } finally {
      setEnviandoPlanilha(false);
    }
  }

  async function autorizarValorSeta(autorizado: boolean) {
    if (!id) return;
    setErro(null);
    try {
      setCampanha(await api.autorizarValorSetaCampanha(id, autorizado));
      setPrevia(null);
    } catch (err) {
      setErro(err instanceof Error ? err.message : "Erro ao salvar a decisão");
    }
  }

  async function removerPlanilha() {
    if (!id || !window.confirm("Remover a planilha de clientes? A campanha volta a usar só os filtros.")) return;
    try {
      await api.removerClientesCampanha(id);
      setForm((f) => ({ ...f, fonte_valores: "seta", todos_da_planilha: false }));
      setPrevia(null);
      recarregarCampanha();
    } catch (err) {
      setErro(err instanceof Error ? err.message : "Erro ao tirar a planilha");
    }
  }

  const novaPrevia = useRequisicaoUnica();
  const novaExecucao = useRequisicaoUnica();

  function carregarPrevia(
    offset: number = previaOffset,
    limit: number = previaLimit,
    sortBy: ColunaPrevia | null = previaSort.sortKey,
    sortDir: SortDirection = previaSort.sortDir,
  ) {
    if (!id) return;
    setErro(null);
    setCarregandoPrevia(true);
    // Só a consulta mais recente vale: página ou ordenação trocada no meio cancela
    // a anterior (e o polling dela), que não sobrescreve a resposta nova
    const signal = novaPrevia();
    api
      .previaCampanha(id, { limit, offset, sort_by: sortBy ?? undefined, sort_dir: sortDir }, signal)
      .then(setPrevia)
      .catch((e) => !foiCancelada(e) && setErro(mensagemErroSeta(e)))
      .finally(() => !signal.aborted && setCarregandoPrevia(false));
  }

  async function executar() {
    if (!id) return;
    if (
      !window.confirm("Colocar agora na fila quem entraria na campanha? Os envios saem dentro do horário de disparo.")
    )
      return;
    setErro(null);
    setSucesso(null);
    setAvisosCategoria([]);
    setExecutando(true);
    const signal = novaExecucao();
    try {
      const r = await api.executarCampanha(id, signal);
      setSucesso(`${r.na_fila} cliente(s) colocado(s) na fila (de ${r.encontrados} encontrado(s)).`);
      setAvisosCategoria(r.avisos_categoria);
      setPrevia(null);
      recarregarCampanha();
    } catch (err) {
      if (!foiCancelada(err)) setErro(mensagemErroSeta(err));
    } finally {
      if (!signal.aborted) setExecutando(false);
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
      {colunasEmBranco.length > 0 && campanha && (
        <ModalDecisaoVariaveis
          campanhaId={campanha.id}
          colunasEmBranco={colunasEmBranco}
          onClose={() => setColunasEmBranco([])}
          onSalvo={() => {
            setColunasEmBranco([]);
            setPrevia(null);
            recarregarCampanha();
          }}
        />
      )}
      <Link to="/campanhas" className="back-link">
        ← Campanhas
      </Link>
      <div className="page-header">
        <div>
          <h2>{nova ? "Nova campanha" : campanha!.nome}</h2>
          {campanha && (
            <div className="subtitle">
              {criadoEm(campanha)} · {periodoCampanha(campanha)} · {campanha.enviados} enviada(s) · {campanha.pendentes} pendente(s) ·{" "}
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
      <AvisosCategoria avisos={avisosCategoria} />

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
              ? "Para um dia só, use a mesma data no início e no fim."
              : 'Só entra na fila ao clicar em "Colocar na fila agora".'}
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
            {form.todos_da_planilha
              ? "Todos os clientes da planilha com parcela em aberto no SETA, em atraso ou não."
              : "Só clientes em atraso no SETA, ou na faixa Antecipado."}
          </p>
          <BarraFiltrosCobranca
            valor={form.filtros}
            onChange={(filtros) => setForm({ ...form, filtros })}
            opcoes={opcoes}
            idPrefixo="camp"
            incluirSoCampanhas
          />

          <div className="sub-card" style={{ marginTop: 16 }}>
            <h4>Planilha de clientes (opcional)</h4>
            <>
              <p className="field-hint">
                Coluna Codigo ou CPF. Os filtros acima continuam valendo.
              </p>
              {Object.keys(pendentesPlanilha).length > 0 && (
                <div className="error-box" style={{ marginBottom: 12, fontSize: '0.9em' }}>
                  <strong>Atenção: alguns clientes ficaram de fora por dados obrigatórios inválidos:</strong>
                  <ul style={{ margin: "4px 0 0 20px" }}>
                    {Object.entries(pendentesPlanilha).map(([motivo, qtd]) => (
                      <li key={motivo}>{qtd} cliente(s) {motivo}</li>
                    ))}
                  </ul>
                </div>
              )}
              {campanha?.fonte_valores === "planilha" && campanha.valor_invalido > 0 && (
                <div className={campanha.valor_seta_autorizado === null ? "error-box" : "success-box"} style={{ marginBottom: 12, fontSize: "0.9em" }}>
                  <strong>
                    {campanha.valor_invalido} cliente(s) sem valor válido na planilha.{" "}
                    {campanha.valor_seta_autorizado === null
                      ? "Usar o valor do SETA para eles?"
                      : campanha.valor_seta_autorizado
                        ? "Usando o valor do SETA."
                        : "Ficam fora da campanha."}
                  </strong>
                  <div style={{ display: "flex", gap: 8, marginTop: 8 }}>
                    <button type="button" className="small" disabled={campanha.valor_seta_autorizado === true} onClick={() => autorizarValorSeta(true)}>
                      Usar o valor do SETA
                    </button>
                    <button type="button" className="secondary small" disabled={campanha.valor_seta_autorizado === false} onClick={() => autorizarValorSeta(false)}>
                      Deixar fora
                    </button>
                  </div>
                </div>
              )}
              {Object.keys(completadosSeta).length > 0 && (
                <div className="success-box" style={{ marginBottom: 12, fontSize: '0.9em' }}>
                  <strong>Dados completados pelo SETA (vazios na planilha):</strong>
                  <ul style={{ margin: "4px 0 0 20px" }}>
                    {Object.entries(completadosSeta).map(([campo, qtd]) => (
                      <li key={campo}>{qtd} cliente(s) sem {campo}</li>
                    ))}
                  </ul>
                </div>
              )}
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
                    <button
                      type="button"
                      className="danger small"
                      onClick={() => {
                        setPlanilhaNova(null);
                        setForm((f) => ({ ...f, todos_da_planilha: false }));
                      }}
                    >
                      <IconTrash width={14} height={14} /> Remover planilha
                    </button>
                  </>
                )}
                {temPlanilha && (
                  <>
                    <span className="text-muted">
                      {campanha!.clientes_arquivo} · {campanha!.clientes_total} cliente(s)
                    </span>
                    <button type="button" className="danger small" onClick={removerPlanilha}>
                      <IconTrash width={14} height={14} /> Remover planilha
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
                    As outras colunas podem ir nas variáveis do template.
                  </span>
                )}
              </div>
              <label className="checkbox-row">
                <input
                  type="checkbox"
                  checked={form.todos_da_planilha}
                  disabled={!temPlanilhaOuNova}
                  onChange={(e) => setForm({ ...form, todos_da_planilha: e.target.checked })}
                />
                Todos os clientes da planilha com parcela em aberto, em atraso ou não
              </label>
              <p className="field-hint" style={{ marginTop: 0 }}>
                Quem está em atraso entra na sua faixa de atraso, e quem não está, na faixa Antecipado. Sem filtro
                de faixa nem de valor em atraso.
              </p>
            </>
          </div>
        </div>

        <div className="card">
          <div className="card-header">
            <h3>Regra de uma mensagem por dia</h3>
          </div>
          <label className="checkbox-row">
            <input
              type="checkbox"
              checked={form.incluir_cobrados_hoje}
              onChange={(e) => setForm({ ...form, incluir_cobrados_hoje: e.target.checked })}
            />
            Incluir quem já recebeu mensagem hoje
          </label>
          <p className="field-hint" style={{ marginTop: 0 }}>
            {form.incluir_cobrados_hoje
              ? "Esta campanha envia mesmo para quem já recebeu outra mensagem hoje (régua, outra campanha ou remarketing)."
              : "Quem já recebeu mensagem hoje por outro caminho fica fora deste envio (uma mensagem por cliente por dia)."}
          </p>
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
          descricao={null}
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
            A prévia não coloca ninguém na fila.
            {alterado && " Salve para ver a prévia atualizada."}
          </p>
          {previa && (
            <>
                            <div style={{ marginBottom: 16 }}>
                <p className="card-subtitle" style={{ margin: "0 0 8px 0" }}>
                  <strong>{previa.total}</strong> cliente(s) entrariam na fila, de <strong>{previa.total_base}</strong> na base filtrada do SETA.
                </p>
                {previa.diagnostico && (
                  <ul className="card-subtitle" style={{ margin: 0, paddingLeft: 20 }}>
                    <li><strong>{previa.diagnostico.pronto}</strong> prontos para envio (na lista abaixo).</li>
                    {previa.diagnostico.ja_recebeu > 0 && <li><strong>{previa.diagnostico.ja_recebeu}</strong> já receberam (na campanha ou bloqueados).</li>}
                    {previa.diagnostico.blacklist > 0 && <li><strong>{previa.diagnostico.blacklist}</strong> na blacklist ou pausados.</li>}
                    {previa.diagnostico.fora_por_decisao > 0 && <li><strong>{previa.diagnostico.fora_por_decisao}</strong> fora por decisão (valor em branco ou inválido).</li>}
                    {previa.diagnostico.aguardando_decisao > 0 && <li><strong style={{color: 'var(--color-danger)'}}>{previa.diagnostico.aguardando_decisao}</strong> aguardando decisão (valor em branco ou inválido).</li>}
                  </ul>
                )}
              </div>
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
              <Link to={`/faixas/${faixa.id}`}>Ver a fila</Link> · <Link to="/relatorios">Relatórios</Link>
            </p>
          )}
        </div>
      )}
    </div>
  );
}
