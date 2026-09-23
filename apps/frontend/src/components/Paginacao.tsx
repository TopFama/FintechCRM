export const LIMIT_OPCOES_PADRAO = [25, 50, 100];

interface PaginacaoProps {
  total: number;
  limit: number;
  offset: number;
  onChange: (novoOffset: number) => void;
  onLimitChange?: (novoLimit: number) => void;
  limitOpcoes?: number[];
}

export default function Paginacao({
  total,
  limit,
  offset,
  onChange,
  onLimitChange,
  limitOpcoes = LIMIT_OPCOES_PADRAO,
}: PaginacaoProps) {
  const pagina = Math.floor(offset / limit) + 1;
  const totalPaginas = Math.max(1, Math.ceil(total / limit));
  const inicio = total === 0 ? 0 : offset + 1;
  const fim = Math.min(offset + limit, total);

  return (
    <div className="paginacao">
      <span className="paginacao-info">
        Mostrando {inicio}–{fim} de {total}
      </span>
      {onLimitChange && (
        <label className="paginacao-limit">
          Por página
          <select value={limit} onChange={(e) => onLimitChange(Number(e.target.value))}>
            {limitOpcoes.map((opcao) => (
              <option key={opcao} value={opcao}>
                {opcao}
              </option>
            ))}
          </select>
        </label>
      )}
      <div className="paginacao-nav">
        <button
          type="button"
          className="secondary small"
          onClick={() => onChange(offset - limit)}
          disabled={offset <= 0}
        >
          ← Anterior
        </button>
        <span className="paginacao-pagina">
          Página {pagina} de {totalPaginas}
        </span>
        <button
          type="button"
          className="secondary small"
          onClick={() => onChange(offset + limit)}
          disabled={offset + limit >= total}
        >
          Próxima →
        </button>
      </div>
    </div>
  );
}
