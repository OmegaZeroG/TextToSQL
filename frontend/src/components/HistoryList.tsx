import { useState } from "react";

import type { QueryResponse } from "../types";

export default function HistoryList({ items }: { items: QueryResponse[] }) {
  const [openIndex, setOpenIndex] = useState<number | null>(null);

  if (items.length === 0) return null;

  return (
    <div>
      <h2 className="mb-2 text-xs font-semibold uppercase tracking-wider text-slate-400">
        History
      </h2>
      <ul className="flex flex-col gap-1">
        {items.map((item, i) => (
          <li key={i} className="rounded-lg border border-slate-800">
            <button
              onClick={() => setOpenIndex(openIndex === i ? null : i)}
              className="w-full px-3 py-2 text-left text-sm text-slate-300 hover:bg-slate-900"
            >
              {item.question}
            </button>
            {openIndex === i && (
              <pre className="whitespace-pre-wrap border-t border-slate-800 bg-slate-950 p-3 font-mono text-xs text-slate-400">
                {item.sql}
              </pre>
            )}
          </li>
        ))}
      </ul>
    </div>
  );
}
