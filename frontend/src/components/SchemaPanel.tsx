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
  activeExample: string;
  onPickExample: (question: string) => void;
}

export default function SchemaPanel({ schema, loading, error, activeExample, onPickExample }: Props) {
  return (
    <aside className="flex max-h-64 w-full shrink-0 flex-col gap-6 overflow-y-auto border-b border-slate-800 bg-slate-900/50 p-4 md:h-full md:max-h-none md:w-80 md:border-b-0 md:border-r">
      <div>
        <h2 className="mb-2 text-xs font-semibold uppercase tracking-wider text-slate-400">
          Database schema
        </h2>
        {loading && (
          <div className="space-y-2" aria-label="Loading schema">
            {[...Array(4)].map((_, i) => (
              <div key={i} className="h-3 w-full animate-pulse rounded bg-slate-800" />
            ))}
          </div>
        )}
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
          {EXAMPLE_QUESTIONS.map((q) => {
            const isActive = q === activeExample;
            return (
              <li key={q}>
                <button
                  onClick={() => onPickExample(q)}
                  aria-current={isActive}
                  className={`w-full rounded-md px-2 py-1.5 text-left text-sm transition hover:bg-slate-800 hover:text-white ${
                    isActive ? "bg-indigo-950 text-white ring-1 ring-inset ring-indigo-700" : "text-slate-300"
                  }`}
                >
                  {q}
                </button>
              </li>
            );
          })}
        </ul>
        <p className="mt-2 text-xs text-slate-500">
          The last one is deliberately destructive — watch the guardrail block it.
        </p>
      </div>
    </aside>
  );
}
