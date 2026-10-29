import { useEffect, useState } from "react";
import { AgruparPainel, api, MetaToken, PainelLinha, PainelMensagens, Template, WhatsappNumber } from "../../api";
import { formatBRL, formatNumero, formatPercentual, formatRoas, rotuloWaba } from "../../format";
import { IconAlert } from "../../icons";
import { ordenarPor, useSort } from "../../sort";
import DicaIndicador from "../DicaIndicador";
import FiltroPeriodo, { Periodo, periodoDe } from "../FiltroPeriodo";
import MultiSelect from "../MultiSelect";
import SelectCampanha from "../SelectCampanha";
import SortableTh from "../SortableTh";
import TabelaAjustavel from "../TabelaAjustavel";

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

type Coluna = {
  chave: string;
  rotulo: string;
  dica?: { texto: string; formula?: string };
  valor: (t: PainelLinha) => string | number | null;
  formato: (t: PainelLinha) => string;
};

const COLUNAS: Coluna[] = [
  { chave: "enviados", rotulo: "Enviados", valor: (t) => t.enviados, formato: (t) => formatNumero(t.enviados) },
  {
    chave: "entregues",
    rotulo: "Entregues",
    dica: { texto: DICAS.entregues },
    valor: (t) => t.entregues,
    formato: (t) => formatNumero(t.entregues),
  },
  {
    chave: "lidas",
    rotulo: "Lidas",
    dica: { texto: "Mensagens entregues que o cliente abriu e leu." },
    valor: (t) => t.lidas,
    formato: (t) => formatNumero(t.lidas),
  },
  {
    chave: "cliques",
    rotulo: "Cliques",
    dica: { texto: "Cliques nos botões da mensagem." },
    valor: (t) => t.cliques,
    formato: (t) => formatNumero(t.cliques),
  },
  {
    chave: "taxa_visualizacao",
    rotulo: "% Visualização",
    dica: {
      texto: "Das mensagens entregues, quantas foram lidas. A Meta só informa leitura por 7 dias depois do envio.",
      formula: "Lidas ÷ Entregues × 100",
    },
    valor: (t) => (t.taxa_visualizacao === null ? null : Number(t.taxa_visualizacao)),
    formato: (t) => formatPercentual(t.taxa_visualizacao),
  },
  {
    chave: "taxa_cliques",
    rotulo: "% Cliques",
    dica: {
      texto: "Das mensagens entregues, quantas tiveram clique em botão. A Meta só informa clique por 7 dias depois do envio.",
      formula: "Cliques ÷ Entregues × 100",
    },
    valor: (t) => (t.taxa_cliques === null ? null : Number(t.taxa_cliques)),
    formato: (t) => formatPercentual(t.taxa_cliques),
  },
  { chave: "cobrados", rotulo: "Clientes cobrados", valor: (t) => t.cobrados, formato: (t) => formatNumero(t.cobrados) },
  { chave: "pagaram", rotulo: "Pagaram", valor: (t) => t.pagaram, formato: (t) => formatNumero(t.pagaram) },
  {
    chave: "conversao",
    rotulo: "% Conv.",
    dica: {
      texto:
        "Dos clientes que receberam o template no período, quantos pagaram dentro da janela de pagamento. Cliente que recebeu mais de um template conta em todos.",
      formula: "Pagaram ÷ Clientes cobrados × 100",
    },
    valor: (t) => (t.conversao === null ? null : Number(t.conversao)),
    formato: (t) => formatPercentual(t.conversao),
  },
  {
    chave: "custo_brl",
    rotulo: "Custo (R$)",
    dica: {
      texto: "A Meta não informa o custo por template. Cada linha leva a parte do gasto real da Meta, por WABA e categoria, igual à fatia dos envios dela.",
      formula: "Gasto da WABA e categoria × Enviados da linha ÷ Enviados do CRM na WABA e categoria",
    },
    valor: (t) => (t.custo_brl === null ? null : Number(t.custo_brl)),
    formato: (t) => formatBRL(t.custo_brl),
  },
  {
    chave: "roas",
    rotulo: "ROAS",
    dica: {
      texto: "Quanto voltou em pagamento para cada R$ 1 gasto com WhatsApp nas mensagens da linha. Cliente que recebeu mais de um template conta em todos.",
      formula: "Valor pago dos clientes cobrados ÷ Custo da linha",
    },
    valor: (t) => (t.roas === null ? null : Number(t.roas)),
    formato: (t) => formatRoas(t.roas),
  },
];

// Mini-tabelas do "Preços das mensagens" do analytics da Meta (em R$) e métricas por
// template. Filtros próprios; a Meta não filtra por template nem campanha, então com
// um deles marcado os quadros vêm da fila (o backend avisa em `origem`).
export default function PainelMensagensCard({ recarregar }: { recarregar: number }) {
  const [periodo, setPeriodo] = useState<Periodo>(() => periodoDe("mes"));
  const [telefones, setTelefones] = useState<string[]>([]);
  const [wabas, setWabas] = useState<string[]>([]);
  const [templates, setTemplates] = useState<string[]>([]);
  const [campanha, setCampanha] = useState("");
  const [agrupar, setAgrupar] = useState<AgruparPainel>("template");
  const [numeros, setNumeros] = useState<WhatsappNumber[]>([]);
  const [tokens, setTokens] = useState<MetaToken[]>([]);
  const [modelos, setModelos] = useState<Template[]>([]);
  const [dados, setDados] = useState<PainelMensagens | null>(null);
  const [erro, setErro] = useState<string | null>(null);
  const ordenacao = useSort<string>(null);

  useEffect(() => {
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

  const coluna = COLUNAS.find((c) => c.chave === ordenacao.sortKey);

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

          {dados.linhas.length > 0 && (
            <TabelaAjustavel id="painel-por-template" rotulo={`Por ${ROTULO_GRUPO[agrupar].toLowerCase()}`} style={{ marginTop: 16 }}>
              <table>
                <thead>
                  <tr>
                    <SortableTh
                      active={ordenacao.sortKey === "nome"}
                      dir={ordenacao.sortDir}
                      onSort={() => ordenacao.toggleSort("nome")}
                    >
                      {ROTULO_GRUPO[agrupar]}
                    </SortableTh>
                    {COLUNAS.map((c) => (
                      <SortableTh
                        key={c.chave}
                        active={ordenacao.sortKey === c.chave}
                        dir={ordenacao.sortDir}
                        onSort={() => ordenacao.toggleSort(c.chave)}
                      >
                        {c.rotulo}
                        {c.dica && <DicaIndicador titulo={c.rotulo} texto={c.dica.texto} formula={c.dica.formula} />}
                      </SortableTh>
                    ))}
                  </tr>
                </thead>
                <tbody>
                  {ordenarPor(
                    dados.linhas,
                    ordenacao.sortKey === "nome" ? (t) => t.nome : coluna ? coluna.valor : null,
                    ordenacao.sortDir
                  ).map((t) => (
                    <tr key={t.chave}>
                      <td className="cell-strong">{t.nome}</td>
                      {COLUNAS.map((c) => (
                        <td key={c.chave}>{c.formato(t)}</td>
                      ))}
                    </tr>
                  ))}
                </tbody>
              </table>
            </TabelaAjustavel>
          )}
        </>
      )}
    </div>
  );
}
