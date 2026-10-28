import { useEffect, useState } from "react";
import { api, PainelMensagens, PainelTemplate, Template, WhatsappNumber } from "../../api";
import { formatBRL, formatNumero, formatPercentual } from "../../format";
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

// Linhas fixas do quadro (zeradas também) mais o que a Meta mandar fora da lista
function linhas<T>(fixas: [string, string][], dados: Record<string, T>): [string, string, T | undefined][] {
  const extras = Object.keys(dados).filter((k) => !fixas.some(([c]) => c === k));
  return [...fixas, ...extras.map((k): [string, string] => [k, k === "OUTRAS" ? "Outras" : k])].map(
    ([c, nome]): [string, string, T | undefined] => [c, nome, dados[c]]
  );
}

function Quadro({ titulo, total, children }: { titulo: string; total: string; children: React.ReactNode }) {
  return (
    <div className="painel-quadro">
      <div className="painel-quadro-topo">
        <strong>{titulo}</strong>
        <strong>{total}</strong>
      </div>
      {children}
    </div>
  );
}

function Linha({ rotulo, valor }: { rotulo: string; valor: string }) {
  return (
    <div className="painel-linha">
      <span>{rotulo}</span>
      <span>{valor}</span>
    </div>
  );
}

type Coluna = {
  chave: string;
  rotulo: string;
  dica?: { texto: string; formula: string };
  valor: (t: PainelTemplate) => string | number | null;
  formato: (t: PainelTemplate) => string;
};

const COLUNAS: Coluna[] = [
  { chave: "enviados", rotulo: "Enviados", valor: (t) => t.enviados, formato: (t) => formatNumero(t.enviados) },
  { chave: "entregues", rotulo: "Entregues", valor: (t) => t.entregues, formato: (t) => formatNumero(t.entregues) },
  { chave: "lidas", rotulo: "Lidas", valor: (t) => t.lidas, formato: (t) => formatNumero(t.lidas) },
  { chave: "cliques", rotulo: "Cliques", valor: (t) => t.cliques, formato: (t) => formatNumero(t.cliques) },
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
      texto: "Estimado: a Meta não informa o custo por template. Cada envio vale a tarifa unitária da categoria do template na WABA.",
      formula: "Enviados × (custo ÷ mensagens cobradas da categoria no período)",
    },
    valor: (t) => (t.custo_brl === null ? null : Number(t.custo_brl)),
    formato: (t) => formatBRL(t.custo_brl),
  },
];

// Mini-tabelas do "Preços das mensagens" do analytics da Meta (em R$) e métricas por
// template. Filtros próprios; a Meta não filtra por template nem campanha, então com
// um deles marcado os quadros vêm da fila (o backend avisa em `origem`).
export default function PainelMensagensCard({ recarregar }: { recarregar: number }) {
  const [periodo, setPeriodo] = useState<Periodo>(() => periodoDe("7dias"));
  const [telefones, setTelefones] = useState<string[]>([]);
  const [wabas, setWabas] = useState<string[]>([]);
  const [templates, setTemplates] = useState<string[]>([]);
  const [campanha, setCampanha] = useState("");
  const [numeros, setNumeros] = useState<WhatsappNumber[]>([]);
  const [modelos, setModelos] = useState<Template[]>([]);
  const [dados, setDados] = useState<PainelMensagens | null>(null);
  const [erro, setErro] = useState<string | null>(null);
  const ordenacao = useSort<string>(null);

  useEffect(() => {
    api.listNumbers().then(setNumeros).catch(() => undefined);
    api.listTemplates().then(setModelos).catch(() => undefined);
  }, []);

  useEffect(() => {
    if (!periodo.de || !periodo.ate) return;
    let atual = true;
    setDados(null);
    setErro(null);
    api
      .getPainelMensagens({ de: periodo.de, ate: periodo.ate, telefone: telefones, waba: wabas, template: templates, campanha })
      .then((d) => atual && setDados(d))
      .catch((e) => atual && setErro(e.message));
    return () => {
      atual = false;
    };
  }, [periodo.de, periodo.ate, telefones, wabas, templates, campanha, recarregar]);

  const opcoesWaba = [...new Set(numeros.map((n) => n.waba_id))].map((w) => ({ value: w, label: w }));
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
                : "Envios da fila; custo = quantidade × tarifa da categoria"}
            </div>
          )}
        </div>
      </div>

      <FiltroPeriodo opcoes={["7dias", "mes", "personalizado"]} inicial="7dias" onChange={(p) => setPeriodo(p)} />
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
      </div>

      {erro ? (
        <div className="error-box">
          <IconAlert width={16} height={16} />
          <span>{erro}</span>
        </div>
      ) : !periodo.de || !periodo.ate ? (
        <div className="empty-state">
          <p>Escolha a data mínima e a máxima.</p>
        </div>
      ) : !dados ? (
        <div className="loading-state">Carregando mensagens...</div>
      ) : (
        <>
          {dados.avisos.length > 0 && (
            <div className="error-box" style={{ alignItems: "flex-start" }}>
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
              <Quadro titulo="Todas as mensagens" total="">
                <Linha rotulo="Mensagens enviadas" valor={formatNumero(dados.todas.enviadas)} />
                {dados.origem === "meta" && (
                  <>
                    <Linha rotulo="Mensagens entregues" valor={formatNumero(dados.todas.entregues)} />
                    <Linha rotulo="Mensagens recebidas" valor={formatNumero(dados.todas.recebidas)} />
                  </>
                )}
              </Quadro>
            )}
            {dados.entregues && (
              <Quadro titulo="Mensagens entregues" total={formatNumero(dados.entregues.total)}>
                {linhas(CATEGORIAS, dados.entregues.por_categoria).map(([c, nome, v]) => (
                  <Linha key={c} rotulo={nome} valor={formatNumero(v ?? 0)} />
                ))}
              </Quadro>
            )}
            {dados.gratuitas && (
              <Quadro titulo="Mensagens gratuitas entregues" total={formatNumero(dados.gratuitas.total)}>
                {linhas(TIPOS_GRATUITOS, dados.gratuitas.por_tipo).map(([c, nome, v]) => (
                  <Linha key={c} rotulo={nome} valor={formatNumero(v ?? 0)} />
                ))}
              </Quadro>
            )}
            {dados.pagas && (
              <Quadro titulo={dados.origem === "meta" ? "Mensagens pagas entregues" : "Mensagens pagas"} total={formatNumero(dados.pagas.total)}>
                {linhas(CATEGORIAS, dados.pagas.por_categoria).map(([c, nome, v]) => (
                  <Linha key={c} rotulo={nome} valor={formatNumero(v ?? 0)} />
                ))}
              </Quadro>
            )}
            {dados.cobranca && (
              <Quadro titulo="Cobrança total aproximada" total={formatBRL(dados.cobranca.total_brl)}>
                {linhas(CATEGORIAS, dados.cobranca.por_categoria).map(([c, nome, v]) => (
                  <Linha key={c} rotulo={nome} valor={formatBRL(v ?? 0)} />
                ))}
              </Quadro>
            )}
          </div>

          {dados.por_template.length > 0 && (
            <TabelaAjustavel id="painel-por-template" rotulo="Por template" style={{ marginTop: 16 }}>
              <table>
                <thead>
                  <tr>
                    <SortableTh
                      active={ordenacao.sortKey === "nome"}
                      dir={ordenacao.sortDir}
                      onSort={() => ordenacao.toggleSort("nome")}
                    >
                      Template
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
                    dados.por_template,
                    ordenacao.sortKey === "nome" ? (t) => t.nome : coluna ? coluna.valor : null,
                    ordenacao.sortDir
                  ).map((t) => (
                    <tr key={t.template_id}>
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
