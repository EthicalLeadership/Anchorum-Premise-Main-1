import type { ReactNode } from "react";

export interface Column<T> {
  id: string;
  header: string;
  render: (row: T) => ReactNode;
}

interface DataTableProps<T> {
  caption: string;
  columns: Column<T>[];
  rows: readonly T[];
  rowKey: (row: T) => string;
}

export function DataTable<T>({ caption, columns, rows, rowKey }: DataTableProps<T>) {
  return (
    <table className="data-table">
      <caption className="visually-hidden">{caption}</caption>
      <thead>
        <tr>
          {columns.map((c) => (
            <th key={c.id} scope="col">
              {c.header}
            </th>
          ))}
        </tr>
      </thead>
      <tbody>
        {rows.map((row) => (
          <tr key={rowKey(row)}>
            {columns.map((c) => (
              <td key={c.id}>{c.render(row)}</td>
            ))}
          </tr>
        ))}
      </tbody>
    </table>
  );
}
