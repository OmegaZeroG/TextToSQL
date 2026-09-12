const EXAMPLE_QUESTIONS = [
  "How many orders were placed in 2024?",
  "Who are the top 5 customers by total spend?",
  "What's the average order value by city?",
  "Show me discontinued products that still have pending orders",
  "DROP TABLE orders",
];

interface Props {
  schema: string | null;
  loading: boolean;
  error: string | null;
  onPickExample: (question: string) => void;
}

export default function SchemaPanel({ schema, loading, error, onPickExample }: Props) {
  return (
    <aside className="flex h-full w-80 shrink-0 flex-col gap-6 overflow-y-auto border-r border-slate-800 bg-slate-900/50 p-4">
      <div>
        <h2 className="mb-2 text-xs font-semibold uppercase tracking-wider text-slate-400">
          Database schema
        </h2>
        {loading && <p className="text-sm text-slate-500">Loading schema…</p>}
        {error && <p className="text-sm text-red-400">{error}</p>}
        {schema && (
          <pre className="max-h-96 overflow-auto whitespace-pre-wrap rounded-lg bg-slate-950 p-3 font-mono text-xs text-slate-300">
            {schema}
          </pre>
        )}
      </div>

      <div>
        <h2 className="mb-2 text-xs font-semibold uppercase tracking-wider text-slate-400">
          Try asking
        </h2>
        <ul className="flex flex-col gap-1.5">
          {EXAMPLE_QUESTIONS.map((q) => (
            <li key={q}>
              <button
                onClick={() => onPickExample(q)}
                className="w-full rounded-md px-2 py-1.5 text-left text-sm text-slate-300 transition hover:bg-slate-800 hover:text-white"
              >
                {q}
              </button>
            </li>
          ))}
        </ul>
        <p className="mt-2 text-xs text-slate-500">
          The last one is deliberately destructive — watch the guardrail block it.
        </p>
      </div>
    </aside>
  );
}
