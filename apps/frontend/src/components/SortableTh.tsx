import { ReactNode, ThHTMLAttributes } from "react";
import { IconSort, IconSortDown, IconSortUp } from "../icons";
import { SortDirection } from "../sort";

interface SortableThProps extends ThHTMLAttributes<HTMLTableCellElement> {
  active: boolean;
  dir: SortDirection;
  onSort: () => void;
  // controle extra no cabeçalho (ex.: filtro da coluna); clicar nele não ordena
  filtro?: ReactNode;
}

/** Cabeçalho de coluna clicável pra ordenar a tabela — mesmo visual em toda
 * a tela, só muda a seta conforme a coluna ativa e a direção. */
export default function SortableTh({ active, dir, onSort, filtro, children, ...rest }: SortableThProps) {
  return (
    <th
      {...rest}
      className={`th-sortable${rest.className ? ` ${rest.className}` : ""}`}
      onClick={onSort}
      aria-sort={active ? (dir === "asc" ? "ascending" : "descending") : "none"}
    >
      <span className="th-sortable-inner">
        {children}
        {active ? (
          dir === "asc" ? (
            <IconSortUp width={12} height={12} />
          ) : (
            <IconSortDown width={12} height={12} />
          )
        ) : (
          <IconSort width={12} height={12} className="th-sortable-icon-idle" />
        )}
        {filtro && <span onClick={(e) => e.stopPropagation()}>{filtro}</span>}
      </span>
    </th>
  );
}
