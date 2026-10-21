import { useState } from "react";
import { ColunaPlanilha, MapeamentoClientes } from "../api";

interface Props {
  arquivo: string;
  colunas: ColunaPlanilha[];
  /** Mapeamento já feito, ao editar; sem ele as colunas são sugeridas pelo cabeçalho. */
  inicial?: MapeamentoClientes | null;
  onConfirmar: (mapeamento: MapeamentoClientes) => void;
  onCancelar: () => void;
}

const MAX_TELEFONES = 4;
const norm = (s: string) => s.normalize("NFD").replace(/[̀-ͯ]/g, "").toUpperCase().trim();

// Sugestão pelo cabeçalho; o usuário confere e troca.
const achar = (colunas: ColunaPlanilha[], nomes: string[]) =>
  colunas.find((c) => nomes.some((n) => norm(c.nome).includes(n)))?.indice;

export default function MapeamentoPlanilha({ arquivo, colunas, inicial, onConfirmar, onCancelar }: Props) {
  const codigo = achar(colunas, ["CODIGO", "COD", "PESSOA"]);
  const cpf = codigo === undefined ? achar(colunas, ["CPF", "DOCUMENTO"]) : undefined;
  const sugerido = achar(colunas, ["CELULAR", "TELEFONE", "FONE", "WHATSAPP"]);
  const [porCpf, setPorCpf] = useState(inicial ? inicial.por_cpf : codigo === undefined && cpf !== undefined);
  const [coluna, setColuna] = useState(String(inicial ? inicial.coluna : (codigo ?? cpf ?? "")));
  const [telefones, setTelefones] = useState<string[]>(
    inicial ? inicial.celulares.map(String) : sugerido === undefined ? [] : [String(sugerido)],
  );

  const opcoes = colunas.map((c) => (
    <option key={c.indice} value={c.indice}>
      {c.nome}
      {c.exemplos.length ? ` (ex.: ${c.exemplos.join(", ")})` : ""}
    </option>
  ));

  function quantidade(n: number) {
    setTelefones((t) => Array.from({ length: n }, (_, i) => t[i] ?? ""));
  }

  const completo = coluna !== "" && telefones.every((t) => t !== "");

  return (
    <div className="sub-card" style={{ marginBottom: 12 }}>
      <h4>Colunas de {arquivo}</h4>
      <div className="form-row" style={{ flexWrap: "wrap" }}>
        <div className="field" style={{ maxWidth: 200 }}>
          <label htmlFor="map-tipo">Cliente identificado por</label>
          <select id="map-tipo" value={porCpf ? "cpf" : "codigo"} onChange={(e) => setPorCpf(e.target.value === "cpf")}>
            <option value="codigo">Código SETA</option>
            <option value="cpf">CPF</option>
          </select>
        </div>
        <div className="field" style={{ maxWidth: 320 }}>
          <label htmlFor="map-coluna">{porCpf ? "Coluna do CPF" : "Coluna do código"}</label>
          <select id="map-coluna" value={coluna} onChange={(e) => setColuna(e.target.value)}>
            <option value="">Escolha a coluna</option>
            {opcoes}
          </select>
        </div>
        <div className="field" style={{ maxWidth: 200 }}>
          <label htmlFor="map-qtd">Telefones na planilha</label>
          <select id="map-qtd" value={telefones.length} onChange={(e) => quantidade(Number(e.target.value))}>
            <option value={0}>Nenhum (usa o do SETA)</option>
            {Array.from({ length: MAX_TELEFONES }, (_, i) => (
              <option key={i + 1} value={i + 1}>
                {i + 1}
              </option>
            ))}
          </select>
        </div>
      </div>
      {telefones.map((t, i) => (
        <div className="field" key={i} style={{ maxWidth: 320 }}>
          <label htmlFor={`map-tel-${i}`}>Telefone {i + 1}</label>
          <select
            id={`map-tel-${i}`}
            value={t}
            onChange={(e) => setTelefones((l) => l.map((x, j) => (j === i ? e.target.value : x)))}
          >
            <option value="">Escolha a coluna</option>
            {opcoes}
          </select>
        </div>
      ))}
      <div className="actions-row">
        <button
          type="button"
          className="small"
          disabled={!completo}
          onClick={() => onConfirmar({ coluna: Number(coluna), por_cpf: porCpf, celulares: telefones.map(Number) })}
        >
          Usar estas colunas
        </button>
        <button type="button" className="secondary small" onClick={onCancelar}>
          Cancelar
        </button>
      </div>
    </div>
  );
}
