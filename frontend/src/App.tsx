import { useEffect, useState } from "react";

import { fetchSchema, submitQuery } from "./api";
import ConfidenceBadge from "./components/ConfidenceBadge";
import HistoryList from "./components/HistoryList";
import QueryForm from "./components/QueryForm";
import ResultsTable from "./components/ResultsTable";
import SchemaPanel from "./components/SchemaPanel";
import type { ClarificationDetail, QueryResponse } from "./types";

export default function App() {
  const [question, setQuestion] = useState("");
  const [loading, setLoading] = useState(false);

  const [schema, setSchema] = useState<string | null>(null);
  const [schemaLoading, setSchemaLoading] = useState(true);
  const [schemaError, setSchemaError] = useState<string | null>(null);

  const [result, setResult] = useState<QueryResponse | null>(null);
  const [clarification, setClarification] = useState<ClarificationDetail | null>(null);
  const [errorMessage, setErrorMessage] = useState<string | null>(null);
  const [history, setHistory] = useState<QueryResponse[]>([]);

  useEffect(() => {
    fetchSchema()
      .then((res) => setSchema(res.schema))
      .catch((err) => setSchemaError(err instanceof Error ? err.message : "Failed to load schema"))
      .finally(() => setSchemaLoading(false));
  }, []);

  async function handleAsk(q: string) {
    setLoading(true);
    setResult(null);
    setClarification(null);
    setErrorMessage(null);

    const outcome = await submitQuery(q);

    if (outcome.kind === "success") {
      setResult(outcome.data);
      setHistory((prev) => [outcome.data, ...prev].slice(0, 10));
    } else if (outcome.kind === "clarification") {
      setClarification(outcome.data);
    } else {
      setErrorMessage(outcome.message);
    }

    setLoading(false);
  }

  return (
    <div className="flex h-screen">
      <SchemaPanel
        schema={schema}
        loading={schemaLoading}
        error={schemaError}
        onPickExample={(q) => {
          setQuestion(q);
          handleAsk(q);
        }}
      />

      <main className="flex flex-1 flex-col gap-6 overflow-y-auto p-6">
        <header>
          <h1 className="text-xl font-semibold text-white">🗄️ Text-to-SQL with Guardrails</h1>
          <p className="mt-1 text-sm text-slate-400">
            Ask a question in plain English. The generated SQL runs read-only, is checked for
            unsafe statements, and comes with a confidence score based on hallucination checks.
          </p>
        </header>

        <QueryForm value={question} onChange={setQuestion} onSubmit={handleAsk} loading={loading} />

        {errorMessage && (
          <div className="rounded-lg border border-red-800 bg-red-950/50 p-4 text-sm text-red-300">
            {errorMessage}
          </div>
        )}

        {clarification && (
          <div className="rounded-lg border border-amber-800 bg-amber-950/30 p-4">
            <p className="text-sm font-medium text-amber-300">{clarification.message}</p>
            <ul className="mt-2 list-inside list-disc text-sm text-amber-200/80">
              {clarification.interpretations.map((interp) => (
                <li key={interp}>{interp}</li>
              ))}
            </ul>
          </div>
        )}

        {result?.guardrail_blocked && (
          <div className="rounded-lg border border-red-800 bg-red-950/50 p-4">
            <p className="text-sm font-medium text-red-300">🚫 Blocked by guardrails</p>
            <p className="mt-1 text-sm text-red-200/80">{result.block_reason}</p>
            <pre className="mt-3 whitespace-pre-wrap rounded bg-slate-950 p-3 font-mono text-xs text-slate-400">
              {result.sql}
            </pre>
          </div>
        )}

        {result && !result.guardrail_blocked && (
          <div className="flex flex-col gap-4">
            <div className="grid grid-cols-1 gap-4 lg:grid-cols-[2fr_1fr]">
              <div>
                <h2 className="mb-2 text-xs font-semibold uppercase tracking-wider text-slate-400">
                  Generated SQL
                </h2>
                <pre className="whitespace-pre-wrap rounded-lg border border-slate-800 bg-slate-950 p-3 font-mono text-sm text-slate-200">
                  {result.sql}
                </pre>
                <p className="mt-2 text-sm text-slate-400">{result.explanation}</p>
                <p className="mt-1 text-xs text-slate-500">
                  {result.execution_time_ms} ms · {result.row_count} rows
                </p>
              </div>
              <ConfidenceBadge confidence={result.confidence} />
            </div>

            {result.warnings.length > 0 && (
              <div className="rounded-lg border border-amber-800 bg-amber-950/30 p-3 text-sm text-amber-200">
                {result.warnings.map((w) => (
                  <p key={w}>⚠️ {w}</p>
                ))}
              </div>
            )}

            <ResultsTable columns={result.columns} rows={result.rows} />
          </div>
        )}

        <HistoryList items={history.slice(1)} />
      </main>
    </div>
  );
}
