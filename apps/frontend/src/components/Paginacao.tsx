interface PaginacaoProps {
  total: number;
  limit: number;
  offset: number;
  onChange: (novoOffset: number) => void;
}

export default function Paginacao({ total, limit, offset, onChange }: PaginacaoProps) {
  const pagina = Math.floor(offset / limit) + 1;
  const totalPaginas = Math.max(1, Math.ceil(total / limit));
  const inicio = total === 0 ? 0 : offset + 1;
  const fim = Math.min(offset + limit, total);

  return (
    <div className="paginacao">
      <span className="paginacao-info">
        Mostrando {inicio}–{fim} de {total}
      </span>
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
