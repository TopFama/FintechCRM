import { ReactNode, useEffect, useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import { AgruparPainel, api, MetaToken, PainelLinha, PainelMensagens, Template, WhatsappNumber } from "../../api";
import { formatBRL, formatDecimal, formatNumero, formatPercentual, formatRoas, rotuloWaba } from "../../format";
import { IconAlert } from "../../icons";
import { ordenarPor, useSort } from "../../sort";
import DicaIndicador from "../DicaIndicador";
import FiltroPeriodo, { Periodo, periodoDe } from "../FiltroPeriodo";
import MultiSelect from "../MultiSelect";
import SelectCampanha from "../SelectCampanha";
import SortableTh from "../SortableTh";
import TabelaAjustavel from "../TabelaAjustavel";
import { linkRelatorio } from "./linkRelatorio";

// pricing_category da Meta, na ordem do analytics deles; categoria nova da Meta entra no fim
const CATEGORIAS: [string, string][] = [
  ["MARKETING", "Marketing"],
  ["MARKETING_LITE", "Marketing - Lite"],
  ["UTILITY", "Utilidade"],
  ["AUTHENTICATION", "Autenticação"],
  ["AUTHENTICATION_INTERNATIONAL", "Autenticação - internacional"],
  ["SERVICE", "Serviço"],
];
const TIPOS_GRATUITOS: [string, string][] = [
  ["FREE_CUSTOMER_SERVICE", "Atendimento ao cliente grátis"],
  ["FREE_ENTRY_POINT", "Ponto de entrada gratuito"],
];

// Explicação de cada quadro e linha, das definições do "i" do analytics da Meta; com template ou campanha
// marcado os quadros vêm da fila e a explicação diz isso
const DICAS = {
  todas: "Mensagens do WhatsApp do período: as que sua empresa enviou, as que chegaram ao cliente e as que ele enviou para você.",
  enviadas:
    "Total de mensagens que sua empresa enviou para contas individuais. Inclui as que podem não ter sido entregues, por exemplo quando o aparelho do destinatário estava fora de serviço.",
  entregues:
    "Mensagens enviadas para contas individuais ou membros de um grupo do WhatsApp que chegaram com sucesso ao dispositivo. Exclui as não entregues.",
  recebidas: "Mensagens que sua empresa recebeu de contas individuais.",
  entreguesCategoria:
    "Mensagens entregues com sucesso, abertas por categoria (marketing, utilidade, serviço e outras). Mesma definição de Mensagens entregues.",
  gratuitas:
    "Mensagens entregues sem custo: as de ponto de entrada gratuito e as de serviço dentro do limite mensal gratuito (1.000 por número comercial). A partir de 1º/10/2026, mensagens de serviço e utilidade na janela de atendimento de 24 horas são cobradas por mensagem; passando da cota, contam como pagas.",
  atendimento:
    "Mensagens de atendimento dentro do limite gratuito mensal de 1.000 por número, enviadas na janela de 24 horas, que começa quando alguém envia mensagem à empresa. Acima da cota, são cobradas e contam como pagas.",
  pontoEntrada:
    "Mensagens gratuitas porque começaram em pontos de entrada gratuitos. A janela abre quando um cliente (Android ou iOS) escreve a partir de anúncios de clique para o WhatsApp ou de botões da Página do Facebook e você responde em até 24 horas. Pode ser prorrogada por até 7 dias.",
  pagas:
    "Mensagens pagas entregues com sucesso, de marketing, utilidade, autenticação ou atendimento. As de atendimento passam a ser cobradas por mensagem depois que o número usa o limite mensal de 1.000 gratuitas.",
  pagasFila:
    "Envios da fila do filtro escolhido que a Meta cobra, por categoria do template. Não são as entregues: a Meta não separa por template nem campanha.",
  cobranca:
    "Total aproximado das cobranças das mensagens entregues, em reais (dólar pela cotação do dia). Pode diferir da fatura por variações no processamento. O valor de cada mensagem paga depende da tarifa do país do número e de a mensagem ser iniciada pela empresa ou resposta em até 24 horas.",
  cobrancaFila:
    "Gasto real da Meta em cada WABA e categoria, dividido pela fatia dos envios do CRM que o filtro escolhido representa.",
};

const ROTULO_GRUPO: Record<AgruparPainel, string> = { template: "Template", faixa: "Faixa de atraso", campanha: "Campanha" };

// Linhas fixas do quadro (zeradas também) mais o que a Meta mandar fora da lista
function linhas<T>(fixas: [string, string][], dados: Record<string, T>): [string, string, T | undefined][] {
  const extras = Object.keys(dados).filter((k) => !fixas.some(([c]) => c === k));
  return [...fixas, ...extras.map((k): [string, string] => [k, k === "OUTRAS" ? "Outras" : k])].map(
    ([c, nome]): [string, string, T | undefined] => [c, nome, dados[c]]
  );
}

function Quadro({ titulo, total, dica, children }: { titulo: string; total: string; dica?: string; children: React.ReactNode }) {
  return (
    <div className="painel-quadro">
      <div className="painel-quadro-topo">
        <strong>
          {titulo}
          {dica && <DicaIndicador titulo={titulo} texto={dica} />}
        </strong>
        <strong>{total}</strong>
      </div>
      {children}
    </div>
  );
}

function Linha({ rotulo, valor, dica }: { rotulo: string; valor: string; dica?: string }) {
  return (
    <div className="painel-linha">
      <span>
        {rotulo}
        {dica && <DicaIndicador titulo={rotulo} texto={dica} />}
      </span>
      <span>{valor}</span>
    </div>
  );
}

type Dica = { texto: string; formula?: string };
type LinhaTabela = PainelLinha & { frequencia: number | null; representatividade: number | null };
type CelulaLink = (aba: string, valor: number, rotulo: string) => ReactNode;

// Colunas da tabela depois do nome: título, valor para ordenar e célula da linha e do total. As chaves
// são as que ficam guardadas na ordem de colunas de cada usuário (a mesma da antiga tabela Por faixa)
type Coluna = {
  rotulo: string;
  dica?: Dica;
  soFaixa?: boolean; // Pendente e Erro só existem no agrupamento por faixa
  valor: (t: LinhaTabela) => string | number | null;
  celula: (t: LinhaTabela, link: CelulaLink) => ReactNode;
  total?: (t: LinhaTabela) => ReactNode; // quando difere da célula
};

// Divisão por zero vira "—", não 0
const razao = (a: number, b: number) => (b ? a / b : null);
const numero = (v: string | null) => (v === null ? null : Number(v));

function criarColunas(porFaixa: boolean): Record<string, Coluna> {
  return {
    pending: {
      rotulo: "Pendente",
      soFaixa: true,
      valor: (t) => t.pendente,
      celula: (t, l) => l("pendentes", t.pendente, "pendentes"),
    },
    error: { rotulo: "Erro", soFaixa: true, valor: (t) => t.erro, celula: (t, l) => l("erros", t.erro, "erros") },
    sent: { rotulo: "Enviados", valor: (t) => t.enviados, celula: (t, l) => l("envios", t.enviados, "enviados") },
    entregues: {
      rotulo: "Entregues",
      dica: { texto: DICAS.entregues },
      valor: (t) => t.entregues,
      celula: (t) => formatNumero(t.entregues),
    },
    lidas: {
      rotulo: "Lidas",
      dica: { texto: "Mensagens entregues que o cliente abriu e leu." },
      valor: (t) => t.lidas,
      celula: (t) => formatNumero(t.lidas),
    },
    cliques: {
      rotulo: "Cliques",
      dica: { texto: "Cliques nos botões da mensagem." },
      valor: (t) => t.cliques,
      celula: (t) => formatNumero(t.cliques),
    },
    taxa_visualizacao: {
      rotulo: "% Visualização",
      dica: {
        texto: "Das mensagens entregues, quantas foram lidas. A Meta só informa leitura por 7 dias depois do envio.",
        formula: "Lidas ÷ Entregues × 100",
      },
      valor: (t) => numero(t.taxa_visualizacao),
      celula: (t) => formatPercentual(t.taxa_visualizacao),
    },
    taxa_cliques: {
      rotulo: "% Cliques",
      dica: {
        texto: "Das mensagens entregues, quantas tiveram clique em botão. A Meta só informa clique por 7 dias depois do envio.",
        formula: "Cliques ÷ Entregues × 100",
      },
      valor: (t) => numero(t.taxa_cliques),
      celula: (t) => formatPercentual(t.taxa_cliques),
    },
    clientes_cobrados: {
      rotulo: "Clientes cobrados",
      dica: {
        texto: "Clientes distintos que receberam mensagem no período. No total, cada cliente conta uma vez.",
        formula: "Contagem de clientes distintos com mensagem enviada no período",
      },
      valor: (t) => t.cobrados,
      celula: (t) => formatNumero(t.cobrados),
    },
    frequencia: {
      rotulo: "Frequência",
      dica: { texto: "Média de mensagens enviadas no período por cliente cobrado.", formula: "Mensagens enviadas ÷ Clientes cobrados" },
      valor: (t) => t.frequencia,
      celula: (t) => formatDecimal(t.frequencia),
    },
    pagaram: {
      rotulo: porFaixa ? "Pagaram após cobrança" : "Pagaram",
      dica: {
        texto: porFaixa
          ? "Clientes cobrados no período que pagaram depois do primeiro envio do período, em qualquer data."
          : "Clientes cobrados no período que pagaram dentro da janela de pagamento.",
        formula: porFaixa
          ? "Contagem de clientes distintos cobrados que pagaram após o primeiro envio do período"
          : undefined,
      },
      valor: (t) => t.pagaram,
      celula: (t, l) => (t.pagaram === null ? "—" : l("pagamentos", t.pagaram, "clientes que pagaram")),
    },
    representatividade: {
      rotulo: "%\u00a0Rep.",
      dica: {
        texto: "Quanto esta linha representa do total de clientes que pagaram após cobrança. Soma a coluna das linhas para fechar 100%.",
        formula: "Pagaram da linha ÷ Σ Pagaram de todas as linhas × 100",
      },
      valor: (t) => t.representatividade,
      celula: (t) => formatPercentual(t.representatividade),
      total: () => null, // sempre 100%: não traz nada
    },
    conversao: {
      rotulo: "%\u00a0Conv.",
      dica: {
        texto: porFaixa
          ? "Dos clientes cobrados na faixa, quantos pagaram depois da cobrança."
          : "Dos clientes que receberam o template no período, quantos pagaram dentro da janela de pagamento. Cliente que recebeu mais de um template conta em todos.",
        formula: "Pagaram ÷ Clientes cobrados × 100",
      },
      valor: (t) => numero(t.conversao),
      celula: (t) => formatPercentual(t.conversao),
    },
    valor_pago: {
      rotulo: "Valor pago",
      dica: {
        texto:
          "Valor pago depois da cobrança pelos clientes cobrados no período. Cada pagamento conta uma vez por linha e, no total, uma vez só, mesmo com o cliente em mais de uma linha.",
        formula: "Σ valor pago após a cobrança",
      },
      valor: (t) => numero(t.valor_pago),
      celula: (t) => formatBRL(t.valor_pago),
    },
    custo_brl: {
      rotulo: "Custo (R$)",
      dica: {
        texto:
          "A Meta não informa o custo por template. Cada linha leva a parte do gasto real da Meta, por WABA e categoria, igual à fatia dos envios dela. Envio sem template registrado (anterior a 28/10) leva o custo médio da mensagem no dia.",
        formula: "Gasto da WABA e categoria × Enviados da linha ÷ Enviados do CRM na WABA e categoria",
      },
      valor: (t) => numero(t.custo_brl),
      celula: (t) => formatBRL(t.custo_brl),
    },
    roas: {
      rotulo: "ROAS",
      dica: {
        texto: "Quanto voltou em pagamento para cada R$ 1 gasto com WhatsApp nas mensagens da linha. Cliente que recebeu mais de um template conta em todos.",
        formula: "Valor pago dos clientes cobrados ÷ Custo da linha",
      },
      valor: (t) => numero(t.roas),
      celula: (t) => formatRoas(t.roas),
    },
  };
}

// Ordem de quem ainda não arrastou nenhuma coluna
const ORDEM_PADRAO = Object.keys(criarColunas(true));

// Ordem salva na conta: ignora coluna que não existe mais e põe no fim, na ordem padrão, coluna nova
function ordemColunas(salvas: string[]): string[] {
  return [...new Set([...salvas.filter((c) => ORDEM_PADRAO.includes(c)), ...ORDEM_PADRAO])];
}

// Frequência e % Rep. saem das próprias linhas; o total não tem % Rep.
function comDerivados(linhas: PainelLinha[], total: PainelLinha | null): { linhas: LinhaTabela[]; total: LinhaTabela | null } {
  const somaPagaram = linhas.reduce((s, t) => s + (t.pagaram ?? 0), 0);
  const derivar = (t: PainelLinha, rep: number | null): LinhaTabela => ({
    ...t,
    frequencia: razao(t.enviados, t.cobrados),
    representatividade: rep,
  });
  return {
    linhas: linhas.map((t) => derivar(t, t.pagaram === null ? null : razao(t.pagaram, somaPagaram))),
    total: total && derivar(total, null),
  };
}

// Mini-tabelas do "Preços das mensagens" do analytics da Meta (em R$) e métricas por
// template. Filtros próprios; a Meta não filtra por template nem campanha, então com
// um deles marcado os quadros vêm da fila (o backend avisa em `origem`).
export default function PainelMensagensCard({ recarregar }: { recarregar: number }) {
  const [periodo, setPeriodo] = useState<Periodo>(() => periodoDe("mes"));
  const [telefones, setTelefones] = useState<string[]>([]);
  const [wabas, setWabas] = useState<string[]>([]);
  const [templates, setTemplates] = useState<string[]>([]);
  const [campanha, setCampanha] = useState("");
  const [agrupar, setAgrupar] = useState<AgruparPainel>("faixa");
  const [numeros, setNumeros] = useState<WhatsappNumber[]>([]);
  const [tokens, setTokens] = useState<MetaToken[]>([]);
  const [modelos, setModelos] = useState<Template[]>([]);
  const [dados, setDados] = useState<PainelMensagens | null>(null);
  const [erro, setErro] = useState<string | null>(null);
  const ordenacao = useSort<string>(null);
  const navigate = useNavigate();
  const [ordem, setOrdem] = useState<string[]>(ORDEM_PADRAO);
  const [arrastada, setArrastada] = useState<string | null>(null);
  const [alvo, setAlvo] = useState<string | null>(null);

  useEffect(() => {
    api
      .colunasPorFaixa()
      .then((r) => setOrdem(ordemColunas(r.colunas)))
      .catch(() => {}); // sem a ordem salva, fica a padrão
    api.listNumbers().then(setNumeros).catch(() => undefined);
    api.listarTokensMeta().then(setTokens).catch(() => undefined);
    api.listTemplates().then(setModelos).catch(() => undefined);
  }, []);

  useEffect(() => {
    if (!periodo.de || !periodo.ate) return;
    let atual = true;
    setDados(null);
    setErro(null);
    api
      .getPainelMensagens({ de: periodo.de, ate: periodo.ate, telefone: telefones, waba: wabas, template: templates, campanha, agrupar })
      .then((d) => atual && setDados(d))
      .catch((e) => atual && setErro(e.message));
    return () => {
      atual = false;
    };
  }, [periodo.de, periodo.ate, telefones, wabas, templates, campanha, agrupar, recarregar]);

  const opcoesWaba = [...new Set(numeros.map((n) => n.waba_id))].map((w) => ({ value: w, label: rotuloWaba(tokens, w) }));
  const opcoesTelefone = numeros
    .filter((n) => wabas.length === 0 || wabas.includes(n.waba_id))
    .map((n) => ({ value: n.id, label: n.label ? `${n.display_phone_number} (${n.label})` : n.display_phone_number }));
  const opcoesTemplate = modelos
    .filter((t) => t.status === "approved")
    .map((t) => ({ value: t.id, label: t.name }));

  const porFaixa = agrupar === "faixa";
  const colunas = criarColunas(porFaixa);
  const visiveis = ordem.filter((c) => !colunas[c].soFaixa || porFaixa);
  const tabela = dados ? comDerivados(dados.linhas, dados.total) : null;
  const coluna = ordenacao.sortKey ? colunas[ordenacao.sortKey] : undefined;

  // Solta a coluna arrastada no lugar da coluna alvo e salva na conta do usuário
  function soltar(chave: string) {
    if (!arrastada || arrastada === chave) return;
    const nova = ordem.filter((c) => c !== arrastada);
    nova.splice(nova.indexOf(chave) + (ordem.indexOf(arrastada) < ordem.indexOf(chave) ? 1 : 0), 0, arrastada);
    setOrdem(nova);
    api.salvarColunasPorFaixa(nova).catch(() => {}); // sem salvar, a ordem vale só nesta visita
  }

  // A primeira coluna (nome) fica fixa; as outras se arrastam pelo título
  const th = (chave: string, rotulo: string, dica?: Dica) => (
    <SortableTh
      key={chave}
      active={ordenacao.sortKey === chave}
      dir={ordenacao.sortDir}
      onSort={() => ordenacao.toggleSort(chave)}
      {...(chave !== "nome" && {
        draggable: true,
        className: alvo === chave && arrastada !== chave ? "th-alvo-arraste" : undefined,
        onDragStart: (e) => {
          e.dataTransfer.effectAllowed = "move";
          e.dataTransfer.setData("text/plain", chave);
          setArrastada(chave);
        },
        onDragOver: (e) => {
          if (!arrastada) return;
          e.preventDefault();
          setAlvo(chave);
        },
        onDragLeave: () => setAlvo((a) => (a === chave ? null : a)),
        onDrop: (e) => {
          e.preventDefault();
          soltar(chave);
        },
        onDragEnd: () => {
          setArrastada(null);
          setAlvo(null);
        },
      })}
    >
      {rotulo}
      {dica && <DicaIndicador titulo={rotulo} texto={dica.texto} formula={dica.formula} />}
    </SortableTh>
  );

  return (
    <div className="card">
      <div className="card-header">
        <div>
          <h3 style={{ marginBottom: 4 }}>Mensagens</h3>
          {dados && (
            <div className="card-subtitle">
              {dados.origem === "meta"
                ? "Analytics da Meta em R$, valores aproximados"
                : "Envios da fila; custo = gasto real da Meta rateado pelos envios"}
            </div>
          )}
        </div>
      </div>

      <FiltroPeriodo opcoes={["hoje", "7dias", "mes", "personalizado"]} inicial="mes" onChange={(p) => setPeriodo(p)} />
      <div className="form-row">
        <MultiSelect id="painel-waba" label="WABA" options={opcoesWaba} value={wabas} onChange={setWabas} />
        <MultiSelect
          id="painel-telefone"
          label="Telefone"
          options={opcoesTelefone}
          value={telefones}
          onChange={setTelefones}
        />
        <MultiSelect id="painel-template" label="Template" options={opcoesTemplate} value={templates} onChange={setTemplates} />
        <SelectCampanha id="painel-campanha" value={campanha} onChange={setCampanha} enviadoDe={periodo.de} enviadoAte={periodo.ate} />
        <div className="field" style={{ flex: "1 1 200px" }}>
          <label htmlFor="painel-agrupar">Agrupar por</label>
          <select id="painel-agrupar" value={agrupar} onChange={(e) => setAgrupar(e.target.value as AgruparPainel)}>
            <option value="template">Template</option>
            <option value="faixa">Faixa de atraso</option>
            <option value="campanha">Campanha</option>
          </select>
        </div>
      </div>

      {erro ? (
        <div className="error-box">
          <IconAlert width={16} height={16} />
          <span>{erro}</span>
        </div>
      ) : !periodo.de || !periodo.ate ? null : !dados ? (
        <div className="loading-state">Carregando mensagens...</div>
      ) : (
        <>
          {dados.avisos.length > 0 && (
            <div className="warning-box" role="status">
              <IconAlert width={16} height={16} />
              <ul style={{ margin: 0, paddingLeft: 18 }}>
                {dados.avisos.map((a) => (
                  <li key={a}>{a}</li>
                ))}
              </ul>
            </div>
          )}
          <div className="painel-quadros">
            {dados.todas && (
              <Quadro titulo="Todas as mensagens" total="" dica={DICAS.todas}>
                <Linha rotulo="Mensagens enviadas" valor={formatNumero(dados.todas.enviadas)} dica={DICAS.enviadas} />
                {dados.origem === "meta" && (
                  <>
                    <Linha rotulo="Mensagens entregues" valor={formatNumero(dados.todas.entregues)} dica={DICAS.entregues} />
                    <Linha rotulo="Mensagens recebidas" valor={formatNumero(dados.todas.recebidas)} dica={DICAS.recebidas} />
                  </>
                )}
              </Quadro>
            )}
            {dados.entregues && (
              <Quadro titulo="Mensagens entregues" total={formatNumero(dados.entregues.total)} dica={DICAS.entreguesCategoria}>
                {linhas(CATEGORIAS, dados.entregues.por_categoria).map(([c, nome, v]) => (
                  <Linha key={c} rotulo={nome} valor={formatNumero(v ?? 0)} />
                ))}
              </Quadro>
            )}
            {dados.gratuitas && (
              <Quadro titulo="Mensagens gratuitas entregues" total={formatNumero(dados.gratuitas.total)} dica={DICAS.gratuitas}>
                {linhas(TIPOS_GRATUITOS, dados.gratuitas.por_tipo).map(([c, nome, v]) => (
                  <Linha
                    key={c}
                    rotulo={nome}
                    valor={formatNumero(v ?? 0)}
                    dica={c === "FREE_CUSTOMER_SERVICE" ? DICAS.atendimento : c === "FREE_ENTRY_POINT" ? DICAS.pontoEntrada : undefined}
                  />
                ))}
              </Quadro>
            )}
            {dados.pagas && (
              <Quadro
                titulo={dados.origem === "meta" ? "Mensagens pagas entregues" : "Mensagens pagas"}
                total={formatNumero(dados.pagas.total)}
                dica={dados.origem === "meta" ? DICAS.pagas : DICAS.pagasFila}
              >
                {linhas(CATEGORIAS, dados.pagas.por_categoria).map(([c, nome, v]) => (
                  <Linha key={c} rotulo={nome} valor={formatNumero(v ?? 0)} />
                ))}
              </Quadro>
            )}
            {dados.cobranca && (
              <Quadro titulo="Cobrança total aproximada" total={formatBRL(dados.cobranca.total_brl)} dica={dados.origem === "meta" ? DICAS.cobranca : DICAS.cobrancaFila}>
                {linhas(CATEGORIAS, dados.cobranca.por_categoria).map(([c, nome, v]) => (
                  <Linha key={c} rotulo={nome} valor={formatBRL(v ?? 0)} />
                ))}
              </Quadro>
            )}
          </div>

          {tabela && tabela.linhas.length > 0 && (
            <TabelaAjustavel id="painel-por-template" rotulo={`Por ${ROTULO_GRUPO[agrupar].toLowerCase()}`} style={{ marginTop: 16 }}>
              <table className="tabela-por-faixa">
                <thead>
                  <tr>
                    {th("nome", ROTULO_GRUPO[agrupar])}
                    {visiveis.map((c) => th(c, colunas[c].rotulo, colunas[c].dica))}
                  </tr>
                </thead>
                <tbody>
                  {ordenarPor(
                    tabela.linhas,
                    ordenacao.sortKey === "nome" ? (t) => t.nome : coluna ? coluna.valor : null,
                    ordenacao.sortDir
                  ).map((t) => {
                    // Por faixa, cada número abre o próprio relatório da faixa e a linha abre os envios dela
                    const link = (aba: string) =>
                      linkRelatorio(aba, periodo, { faixa_id: t.faixa_id ?? "", ...(aba === "pagamentos" ? { base: "envios" } : {}) });
                    const celula: CelulaLink = (aba, valor, rotulo) =>
                      porFaixa && t.faixa_id ? (
                        <Link
                          to={link(aba)}
                          className="link-celula"
                          aria-label={`Ver ${formatNumero(valor)} ${rotulo} da faixa ${t.nome}`}
                          onClick={(e) => e.stopPropagation()}
                        >
                          {formatNumero(valor)}
                        </Link>
                      ) : (
                        formatNumero(valor)
                      );
                    return (
                      <tr
                        key={t.chave}
                        className={porFaixa && t.faixa_id ? "linha-clicavel" : undefined}
                        onClick={porFaixa && t.faixa_id ? () => navigate(link("envios")) : undefined}
                      >
                        <td className="cell-strong">
                          {porFaixa && t.faixa_id ? (
                            <Link to={link("envios")} className="link-celula" onClick={(e) => e.stopPropagation()}>
                              {t.nome}
                            </Link>
                          ) : (
                            t.nome
                          )}
                        </td>
                        {visiveis.map((c) => (
                          <td key={c}>{colunas[c].celula(t, celula)}</td>
                        ))}
                      </tr>
                    );
                  })}
                </tbody>
                {tabela.total && (
                  <tfoot>
                    <tr className="linha-total">
                      <td className="cell-strong">Total</td>
                      {visiveis.map((c) => (
                        <td key={c}>
                          {(colunas[c].total ?? ((t: LinhaTabela) => colunas[c].celula(t, (_aba, valor) => formatNumero(valor))))(tabela.total!)}
                        </td>
                      ))}
                    </tr>
                  </tfoot>
                )}
              </table>
            </TabelaAjustavel>
          )}
        </>
      )}
    </div>
  );
}
