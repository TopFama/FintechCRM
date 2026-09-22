import { useRef, useState } from "react";
import { useNavigate } from "react-router-dom";
import { api, mensagemErroSeta, FiltrosCobranca, RelatorioCobranca } from "../../api";
import { formatBRL } from "../../format";
import { IconAlert } from "../../icons";
import BarraFiltrosCobranca, { FILTROS_COBRANCA_PADRAO } from "../BarraFiltrosCobranca";
import MatrizTable from "../MatrizTable";
import { OpcoesCobranca } from "../useOpcoesCobranca";

type Aba = "clientes" | "spc" | "valor";
const ROTULOS: Record<Aba, string> = {
  clientes: "Clientes",
  spc: "Clientes com restrição no SPC",
  valor: "Valor em aberto",
};

export default function MatrizCobrancaCard({ opcoes }: { opcoes: OpcoesCobranca }) {
  const navigate = useNavigate();
  const [filtros, setFiltros] = useState<FiltrosCobranca>(FILTROS_COBRANCA_PADRAO);
  const [relatorio, setRelatorio] = useState<RelatorioCobranca | null>(null);
  const [erro, setErro] = useState<string | null>(null);
  const [carregando, setCarregando] = useState(false);
  const [aba, setAba] = useState<Aba>("clientes");
  const reqRef = useRef(0);

  function aplicar() {
    setErro(null);
    setCarregando(true);
    const seq = ++reqRef.current;
    api
      .relatorioCobranca(filtros)
      .then((r) => seq === reqRef.current && setRelatorio(r))
      .catch((e) => seq === reqRef.current && setErro(mensagemErroSeta(e)))
      .finally(() => seq === reqRef.current && setCarregando(false));
  }

  function abrirNaCobranca(cluster: string, faixa: string) {
    navigate(`/cobranca?${new URLSearchParams({ cluster, faixa }).toString()}`);
  }

  const matriz = relatorio
    ? aba === "spc"
      ? relatorio.quantidade_com_restricao_spc
      : aba === "valor"
        ? relatorio.valor_em_aberto
        : relatorio.quantidade
    : null;

  return (
    <div className="card">
      <div className="card-header">
        <h3>Base de cobrança — cluster × faixa</h3>
      </div>

      <BarraFiltrosCobranca
        valor={filtros}
        onChange={setFiltros}
        onAplicar={aplicar}
        opcoes={opcoes}
        idPrefixo="dash-matriz"
      />

      <div className="abas" role="tablist" style={{ marginTop: 16 }}>
        {(Object.keys(ROTULOS) as Aba[]).map((a) => (
          <button
            key={a}
            type="button"
            role="tab"
            aria-selected={aba === a}
            className={aba === a ? "" : "secondary"}
            onClick={() => setAba(a)}
          >
            {ROTULOS[a]}
          </button>
        ))}
      </div>

      {erro && (
        <div className="error-box">
          <IconAlert width={16} height={16} />
          <span>{erro}</span>
        </div>
      )}
      {carregando && <div className="loading-state">Consultando o ERP SETA — pode levar até um minuto...</div>}
      {matriz && relatorio && !carregando && (
        <>
          <MatrizTable
            clusters={relatorio.clusters}
            faixas={relatorio.faixas}
            matriz={matriz}
            formato={aba === "valor" ? formatBRL : (v) => Number(v).toLocaleString("pt-BR")}
            elegivel={(c, f) => (opcoes.regras?.faixas_whatsapp[c] ?? []).includes(f)}
            onCelulaClick={abrirNaCobranca}
          />
          <div className="field-hint">
            Clique numa célula para ver os clientes na tela Cobrança. Células esmaecidas não recebem WhatsApp pela regra
            atual.
          </div>
        </>
      )}
      {!relatorio && !carregando && !erro && (
        <div className="empty-state">
          <p>Aplique os filtros para ver a matriz cluster × faixa.</p>
        </div>
      )}
    </div>
  );
}
