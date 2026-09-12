interface Props {
  columns: string[];
  rows: unknown[][];
}

export default function ResultsTable({ columns, rows }: Props) {
  if (rows.length === 0) {
    return (
      <p className="rounded-lg border border-slate-800 bg-slate-900/40 p-4 text-sm text-slate-400">
        Query executed successfully but returned no rows.
      </p>
    );
  }

  return (
    <div className="overflow-x-auto rounded-lg border border-slate-800">
      <table className="w-full text-left text-sm">
        <thead className="bg-slate-900 text-xs uppercase tracking-wider text-slate-400">
          <tr>
            {columns.map((col) => (
              <th key={col} className="px-4 py-2.5 font-medium">
                {col}
              </th>
            ))}
          </tr>
        </thead>
        <tbody className="divide-y divide-slate-800">
          {rows.map((row, i) => (
            <tr key={i} className="hover:bg-slate-900/60">
              {row.map((cell, j) => (
                <td key={j} className="whitespace-nowrap px-4 py-2 text-slate-200">
                  {cell === null ? <span className="text-slate-600 italic">null</span> : String(cell)}
                </td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
