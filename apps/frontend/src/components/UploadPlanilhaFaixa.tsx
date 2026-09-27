import { useEffect, useMemo, useRef, useState } from "react";
import { Link } from "react-router-dom";
import { api, Faixa, Template, UploadFieldMapping, UploadResult, UploadValorZerado } from "../api";
import { formatNumero } from "../format";
import { IconAlert, IconDownload, IconUpload } from "../icons";

const NO_COLUMN = "";
const DESCARTAR = "descartar";
const OUTRO = "outro";

/** Escolha padrão para a linha zerada: o primeiro valor do sistema, senão descartar. */
function escolhaPadrao(z: UploadValorZerado): string {
  return z.opcoes[0]?.campo ?? DESCARTAR;
}

function pickDefault(columns: string[], previous: string | null | undefined): string {
  if (previous && columns.includes(previous)) return previous;
  return NO_COLUMN;
}

/** Importação de planilha para a fila de uma faixa: baixar modelo, ler o
 * cabeçalho, mapear colunas e confirmar. Usado na aba Cobrança. */
export default function UploadPlanilhaFaixa({ faixaId }: { faixaId: string }) {
  const id = faixaId;
  const [faixa, setFaixa] = useState<Faixa | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [uploadResult, setUploadResult] = useState<UploadResult | null>(null);
  const [downloadingModel, setDownloadingModel] = useState(false);
  // Upload em duas etapas: 1) escolher arquivo e ler as colunas reais do
  // cabeçalho; 2) mapear cada variável/campo para uma dessas colunas antes
  // de confirmar a importação.
  const [pendingFile, setPendingFile] = useState<File | null>(null);
  const [columns, setColumns] = useState<string[] | null>(null);
  const [sampleRow, setSampleRow] = useState<Record<string, string> | null>(null);
  const [loadingColumns, setLoadingColumns] = useState(false);
  const [fieldMap, setFieldMap] = useState<UploadFieldMapping>({
    celular: NO_COLUMN,
    codigo_cliente: NO_COLUMN,
    nome: NO_COLUMN,
    cpf: NO_COLUMN,
    valor: NO_COLUMN,
    variables: {},
  });
  const [importing, setImporting] = useState(false);
  // Linhas de valor zerado: por número da linha, o campo escolhido, "outro" ou "descartar"
  const [escolhas, setEscolhas] = useState<Record<number, string>>({});
  const [outrosValores, setOutrosValores] = useState<Record<number, string>>({});
  const [importandoZerados, setImportandoZerados] = useState(false);

  const fileInputRef = useRef<HTMLInputElement>(null);


  function loadFaixa() {
    api
      .getFaixa(id)
      .then(setFaixa)
      .catch((e) => setError(e.message));
  }

  useEffect(() => {
    setFaixa(null);
    setUploadResult(null);
    cancelMapping();
    loadFaixa();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [id]);

  const templatesAtivos = useMemo(() => {
    const porId = new Map<string, Template>();
    (faixa?.envios || []).forEach((e) => {
      if (e.active) porId.set(e.template_id, e.template);
    });
    return Array.from(porId.values());
  }, [faixa]);

  async function handlePickFile(file: File) {
    setError(null);
    setUploadResult(null);
    setPendingFile(file);
    setColumns(null);
    setLoadingColumns(true);
    try {
      const result = await api.uploadColumns(id, file);
      setColumns(result.columns);
      setSampleRow(result.sample_row);
      const previous = faixa?.upload_field_mapping;
      const variableIds = templatesAtivos.flatMap((t) => t.variables.map((v) => v.id));
      setFieldMap({
        celular: pickDefault(result.columns, previous?.celular),
        codigo_cliente: pickDefault(result.columns, previous?.codigo_cliente),
        nome: pickDefault(result.columns, previous?.nome),
        cpf: pickDefault(result.columns, previous?.cpf),
        valor: pickDefault(result.columns, previous?.valor),
        variables: Object.fromEntries(
          variableIds.map((vid) => [vid, pickDefault(result.columns, previous?.variables?.[vid])])
        ),
      });
    } catch (err) {
      setError(err instanceof Error ? err.message : "Erro ao ler colunas da planilha");
      setPendingFile(null);
    } finally {
      setLoadingColumns(false);
    }
  }

  function cancelMapping() {
    setPendingFile(null);
    setColumns(null);
    setSampleRow(null);
    if (fileInputRef.current) fileInputRef.current.value = "";
  }

  const requiredVariableIds = templatesAtivos
    .flatMap((t) => t.variables)
    .map((v) => v.id);
  const mappingComplete =
    Boolean(fieldMap.celular) &&
    Boolean(fieldMap.codigo_cliente) &&
    Boolean(fieldMap.nome) &&
    Boolean(fieldMap.cpf) &&
    requiredVariableIds.every((vid) => Boolean(fieldMap.variables[vid]));

  async function confirmImport() {
    if (!pendingFile || !mappingComplete) return;
    setError(null);
    setImporting(true);
    try {
      const result = await api.uploadPlanilha(id, pendingFile, fieldMap);
      setUploadResult(result);
      setEscolhas(Object.fromEntries(result.valores_zerados.map((z) => [z.linha, escolhaPadrao(z)])));
      setOutrosValores({});
      cancelMapping();
      loadFaixa();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Erro ao subir planilha");
    } finally {
      setImporting(false);
    }
  }

  function valorEscolhido(z: UploadValorZerado): string | null {
    const escolha = escolhas[z.linha] ?? escolhaPadrao(z);
    if (escolha === DESCARTAR) return null;
    if (escolha === OUTRO) return (outrosValores[z.linha] || "").trim();
    return z.opcoes.find((o) => o.campo === escolha)?.valor ?? null;
  }

  async function confirmarZerados(descartarTodos = false) {
    if (!uploadResult) return;
    const zerados = uploadResult.valores_zerados;
    const linhas = descartarTodos
      ? []
      : zerados.flatMap((z) => {
          const valor = valorEscolhido(z);
          return valor === null ? [] : [{ linha: z.linha, dados: z.dados, valor }];
        });
    if (linhas.some((l) => !l.valor)) {
      setError("Informe o valor de cada linha marcada como \"Outro valor\"");
      return;
    }
    const descartadas = zerados.length - linhas.length;
    const descarte = descartadas ? [`${descartadas} linha(s) com valor zerado descartada(s)`] : [];
    setError(null);
    if (linhas.length === 0) {
      setUploadResult({ ...uploadResult, valores_zerados: [], rejected_reasons: [...uploadResult.rejected_reasons, ...descarte] });
      return;
    }
    setImportandoZerados(true);
    try {
      const r = await api.importarValoresZerados(id, { filename: uploadResult.filename, mapping: fieldMap, linhas });
      setUploadResult({
        ...uploadResult,
        accepted_count: uploadResult.accepted_count + r.accepted_count,
        rejected_count: uploadResult.rejected_count + r.rejected_count,
        invalid_phone_count: uploadResult.invalid_phone_count + r.invalid_phone_count,
        rejected_reasons: [...uploadResult.rejected_reasons, ...r.rejected_reasons, ...descarte],
        valores_zerados: [],
      });
    } catch (err) {
      setError(err instanceof Error ? err.message : "Erro ao importar os valores escolhidos");
    } finally {
      setImportandoZerados(false);
    }
  }

  async function handleDownloadModel() {
    if (!id || !faixa) return;
    setError(null);
    setDownloadingModel(true);
    try {
      await api.downloadSpreadsheetModel(id, faixa.name);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Erro ao baixar modelo");
    } finally {
      setDownloadingModel(false);
    }
  }

  function renderizarPreviewUpload(t: Template): string {
    return t.body_text.replace(/\{\{(\d+)\}\}/g, (match, pos) => {
      const variavel = t.variables.find((v) => v.position === Number(pos));
      if (!variavel) return match;
      const coluna = fieldMap.variables[variavel.id];
      const valor = coluna && sampleRow ? sampleRow[coluna] : "";
      return valor ? valor : `[${variavel.internal_name}]`;
    });
  }

  if (!faixa) return <p className="card-subtitle">Carregando faixa...</p>;

  return (
    <>
      {error && (
        <div className="error-box">
          <IconAlert width={16} height={16} />
          <span>{error}</span>
        </div>
      )}
      {templatesAtivos.length === 0 && (
        <p className="card-subtitle">
          Esta faixa não tem nenhum envio ativo (número + template). Configure em{" "}
          <Link to={`/faixas/${faixa.id}`}>Faixas</Link> antes de subir a planilha.
        </p>
      )}
      {templatesAtivos.length > 0 && (
        <div className="sub-card">
          <div className="card-header">
            <h3>Subir planilha e mapear colunas</h3>
            <button className="ghost small" onClick={handleDownloadModel} disabled={downloadingModel}>
              <IconDownload width={16} height={16} /> {downloadingModel ? "Baixando..." : "Baixar modelo sugerido (.xlsx)"}
            </button>
          </div>
          <p className="card-subtitle">
            Suba a planilha com a base de clientes desta faixa. O sistema lê o cabeçalho (primeira linha) e você
            escolhe, em uma lista suspensa, qual coluna alimenta cada campo — não precisa usar os nomes do modelo.
          </p>

          {!columns && (
            <label className="dropzone">
              <input
                ref={fileInputRef}
                type="file"
                accept=".xlsx"
                onChange={(e) => e.target.files && handlePickFile(e.target.files[0])}
              />
              <IconUpload width={26} height={26} />
              <div className="dz-title">{loadingColumns ? "Lendo colunas da planilha..." : "Clique ou arraste a planilha aqui"}</div>
              <div className="dz-hint">.xlsx</div>
            </label>
          )}

          {columns && (
            <div>
              <p className="card-subtitle" style={{ marginTop: 0 }}>
                Arquivo: <strong>{pendingFile?.name}</strong> — {columns.length} coluna(s) encontrada(s)
              </p>

              <div className="form-row">
                <div className="field">
                  <label htmlFor="upload-coluna-do-codigo">Coluna do código (SETA, até 8 dígitos — completa com zero à esquerda) *</label>
                  <select id="upload-coluna-do-codigo" value={fieldMap.codigo_cliente} onChange={(e) => setFieldMap({ ...fieldMap, codigo_cliente: e.target.value })}>
                    <option value="">Selecione...</option>
                    {columns.map((c) => (
                      <option key={c} value={c}>
                        {c}
                      </option>
                    ))}
                  </select>
                </div>
                <div className="field">
                  <label htmlFor="upload-coluna-do-nome">Coluna do nome (usa só o primeiro nome) *</label>
                  <select id="upload-coluna-do-nome" value={fieldMap.nome} onChange={(e) => setFieldMap({ ...fieldMap, nome: e.target.value })}>
                    <option value="">Selecione...</option>
                    {columns.map((c) => (
                      <option key={c} value={c}>
                        {c}
                      </option>
                    ))}
                  </select>
                </div>
              </div>

              <div className="form-row">
                <div className="field">
                  <label htmlFor="upload-coluna-do-cpf">Coluna do CPF (formata com pontos e traço) *</label>
                  <select id="upload-coluna-do-cpf" value={fieldMap.cpf} onChange={(e) => setFieldMap({ ...fieldMap, cpf: e.target.value })}>
                    <option value="">Selecione...</option>
                    {columns.map((c) => (
                      <option key={c} value={c}>
                        {c}
                      </option>
                    ))}
                  </select>
                </div>
                <div className="field">
                  <label htmlFor="upload-coluna-do-celular">Coluna do celular *</label>
                  <select id="upload-coluna-do-celular" value={fieldMap.celular} onChange={(e) => setFieldMap({ ...fieldMap, celular: e.target.value })}>
                    <option value="">Selecione...</option>
                    {columns.map((c) => (
                      <option key={c} value={c}>
                        {c}
                      </option>
                    ))}
                  </select>
                </div>
              </div>

              <div className="form-row">
                <div className="field">
                  <label htmlFor="upload-coluna-do-valor">Coluna do valor cobrado (opcional)</label>
                  <select id="upload-coluna-do-valor" value={fieldMap.valor || ""} onChange={(e) => setFieldMap({ ...fieldMap, valor: e.target.value })}>
                    <option value="">Nenhuma</option>
                    {columns.map((c) => (
                      <option key={c} value={c}>
                        {c}
                      </option>
                    ))}
                  </select>
                </div>
              </div>

              {templatesAtivos.some((t) => t.variables.length > 0) && (
                <>
                  <label style={{ marginBottom: 8 }}>Variáveis dos templates ativos</label>
                  <div className="form-row" style={{ flexWrap: "wrap" }}>
                    {templatesAtivos.flatMap((t) =>
                      t.variables.map((v) => {
                        return (
                          <div className="field" key={v.id} style={{ minWidth: 220 }}>
                            <label htmlFor={`upload-var-${v.id}`}>
                              {t.name}: {v.internal_name} *
                            </label>
                            <select id={`upload-var-${v.id}`}
                              value={fieldMap.variables[v.id] || ""}
                              onChange={(e) => setFieldMap({ ...fieldMap, variables: { ...fieldMap.variables, [v.id]: e.target.value } })}
                            >
                              <option value="">Selecione...</option>
                              {columns.map((c) => (
                                <option key={c} value={c}>
                                  {c}
                                </option>
                              ))}
                            </select>
                          </div>
                        );
                      })
                    )}
                  </div>
                </>
              )}

              {sampleRow && templatesAtivos.length > 0 && (
                <div className="sub-card" style={{ marginTop: 16 }}>
                  <label style={{ marginBottom: 8, display: "block" }}>
                    Pré-visualização (com a primeira linha da planilha subida)
                  </label>
                  {templatesAtivos.map((t) => (
                    <p key={t.id} className="card-subtitle" style={{ whiteSpace: "pre-wrap" }}>
                      <strong>{t.name}:</strong> {renderizarPreviewUpload(t)}
                    </p>
                  ))}
                </div>
              )}

              <div className="actions-row">
                <button className="secondary" onClick={cancelMapping} disabled={importing}>
                  Cancelar
                </button>
                <button onClick={confirmImport} disabled={!mappingComplete || importing}>
                  {importing ? "Importando..." : "Confirmar e importar"}
                </button>
              </div>
            </div>
          )}

          {uploadResult && (
            <>
              <div className="upload-summary">
                <div className="item">
                  <span className="num" style={{ color: "var(--color-success)" }}>
                    {uploadResult.accepted_count}
                  </span>
                  aceitos
                </div>
                <div className="item">
                  <span className="num" style={{ color: "var(--color-danger)" }}>
                    {uploadResult.rejected_count}
                  </span>
                  rejeitados
                </div>
                {uploadResult.invalid_phone_count > 0 && (
                  <div className="item">
                    <span className="num" style={{ color: "var(--color-warning)" }}>
                      {uploadResult.invalid_phone_count}
                    </span>
                    telefone(s) inválido(s)
                  </div>
                )}
                <div className="item">
                  <span className="num">{uploadResult.row_count}</span>
                  linhas na planilha
                </div>
              </div>
              {uploadResult.valores_zerados.length > 0 && (
                <div className="sub-card" style={{ marginTop: 16 }}>
                  <h3>Valor zerado na planilha ({formatNumero(uploadResult.valores_zerados.length)})</h3>
                  <div className="table-wrap">
                    <table>
                      <thead>
                        <tr>
                          <th>Linha</th>
                          <th>Cliente</th>
                          <th>Valor a usar</th>
                        </tr>
                      </thead>
                      <tbody>
                        {uploadResult.valores_zerados.map((z) => {
                          const escolha = escolhas[z.linha] ?? escolhaPadrao(z);
                          return (
                            <tr key={z.linha}>
                              <td>{z.linha}</td>
                              <td>
                                {z.codigo_cliente} · {z.nome}
                              </td>
                              <td>
                                <div className="form-row" style={{ margin: 0, flexWrap: "wrap" }}>
                                  <select
                                    aria-label={`Valor a usar na linha ${z.linha}`}
                                    value={escolha}
                                    onChange={(e) => setEscolhas({ ...escolhas, [z.linha]: e.target.value })}
                                  >
                                    {z.opcoes.map((o) => (
                                      <option key={o.campo} value={o.campo}>
                                        {o.rotulo}: R$ {o.valor}
                                      </option>
                                    ))}
                                    <option value={OUTRO}>Outro valor</option>
                                    <option value={DESCARTAR}>Descartar</option>
                                  </select>
                                  {escolha === OUTRO && (
                                    <input
                                      aria-label={`Outro valor para a linha ${z.linha}`}
                                      inputMode="decimal"
                                      placeholder="0,00"
                                      value={outrosValores[z.linha] || ""}
                                      onChange={(e) => setOutrosValores({ ...outrosValores, [z.linha]: e.target.value })}
                                      style={{ maxWidth: 140 }}
                                    />
                                  )}
                                </div>
                              </td>
                            </tr>
                          );
                        })}
                      </tbody>
                    </table>
                  </div>
                  <div className="actions-row">
                    <button className="secondary" onClick={() => confirmarZerados(true)} disabled={importandoZerados}>
                      Descartar todos
                    </button>
                    <button onClick={() => confirmarZerados()} disabled={importandoZerados}>
                      {importandoZerados ? "Importando..." : "Confirmar valores"}
                    </button>
                  </div>
                </div>
              )}
              {uploadResult.invalid_phone_count > 0 && (
                <p className="field-hint">
                  <Link to="/relatorios">Ver no relatório de telefones inválidos →</Link>
                </p>
              )}
              {uploadResult.rejected_reasons.length > 0 && (
                <ul style={{ fontSize: 13, color: "var(--color-danger)", marginTop: 10 }}>
                  {uploadResult.rejected_reasons.map((r, i) => (
                    <li key={i}>{r}</li>
                  ))}
                </ul>
              )}
            </>
          )}
        </div>
      )}

    </>
  );
}
