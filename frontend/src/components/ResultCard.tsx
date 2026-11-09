import type { ReactNode } from "react";

import { useElapsed } from "../hooks/useElapsed";
import { cn } from "../lib/cn";
import { downloadText } from "../lib/download";
import type { Dialect, GenerateOutcome } from "../types";
import ConfidenceGauge from "./ConfidenceGauge";
import CopyButton from "./CopyButton";
import LoadingSteps from "./LoadingSteps";
import SqlBlock from "./SqlBlock";
import Badge from "./ui/Badge";
import Button from "./ui/Button";
import Icon from "./ui/Icon";
import Skeleton from "./ui/Skeleton";

interface Props {
  outcome: GenerateOutcome | null;
  loading: boolean;
  hasSchema: boolean;
  dialects: Dialect[];
  canAdoptSchema: boolean;
  adoptingSchema: boolean;
  onAdoptSchema: (ddl: string) => void;
  onCancel: () => void;
  onRetry: () => void;
  /** Changes with every new result so the entrance animation replays. */
  resultKey: number;
}

function CardShell({
  dialectLabel,
  actions,
  children,
}: {
  dialectLabel?: string;
  actions?: ReactNode;
  children: ReactNode;
}) {
  return (
    <section aria-label="Result" className="overflow-hidden rounded-lg border border-border bg-card shadow-card">
      <header className="flex items-center justify-between gap-3 border-b border-border px-4 py-3">
        <div className="flex min-w-0 items-center gap-2">
          <Icon name="code" className="text-primary" />
          <h2 className="text-sm font-semibold">SQL query</h2>
          {dialectLabel && <Badge>{dialectLabel}</Badge>}
        </div>
        {actions && <div className="flex shrink-0 items-center gap-2">{actions}</div>}
      </header>
      {children}
    </section>
  );
}

function ResultSkeleton({ hasSchema, onCancel }: { hasSchema: boolean; onCancel: () => void }) {
  const elapsed = useElapsed(true);
  const steps = [
    hasSchema ? "Reading your schema" : "Assuming a sensible schema",
    "Writing the SQL",
    "Checking it against your question",
  ];

  return (
    <div className="grid animate-fade-in gap-4 xl:grid-cols-[minmax(0,1fr)_260px]" aria-busy="true">
      <CardShell
        actions={
          <Button size="sm" onClick={onCancel}>
            <Icon name="stop" className="size-3.5" />
            Stop
          </Button>
        }
      >
        <div className="space-y-2.5 bg-muted/60 p-4" aria-hidden="true">
          <Skeleton className="h-3.5 w-3/5" />
          <Skeleton className="h-3.5 w-4/5" />
          <Skeleton className="h-3.5 w-2/5" />
          <Skeleton className="h-3.5 w-1/2" />
        </div>
        <div className="p-4">
          <LoadingSteps steps={steps} elapsedMs={elapsed} />
        </div>
      </CardShell>

      <div className="hidden rounded-lg border border-border bg-card p-4 shadow-card xl:block" aria-hidden="true">
        <div className="flex items-center gap-4">
          <Skeleton className="size-16 rounded-full" />
          <div className="flex-1 space-y-2">
            <Skeleton className="h-3 w-16" />
            <Skeleton className="h-5 w-20" />
          </div>
        </div>
        <div className="mt-4 space-y-2.5 border-t border-border pt-3">
          <Skeleton className="h-3 w-full" />
          <Skeleton className="h-3 w-5/6" />
          <Skeleton className="h-3 w-4/6" />
        </div>
      </div>
    </div>
  );
}

function EmptyResult() {
  return (
    <CardShell>
      <div className="bg-dots grid place-items-center px-6 py-14 text-center">
        <div className="mb-4 grid size-11 place-items-center rounded-lg border border-border bg-card text-muted-foreground shadow-sm">
          <Icon name="download" className="size-5" />
        </div>
        <p className="text-sm font-medium">Your query will appear here</p>
        <p className="mt-1 text-xs text-muted-foreground">Write a question or choose an example to get started.</p>
      </div>
    </CardShell>
  );
}

export default function ResultCard({
  outcome,
  loading,
  hasSchema,
  dialects,
  canAdoptSchema,
  adoptingSchema,
  onAdoptSchema,
  onCancel,
  onRetry,
  resultKey,
}: Props) {
  if (loading) return <ResultSkeleton hasSchema={hasSchema} onCancel={onCancel} />;
  if (!outcome || outcome.kind === "cancelled") return <EmptyResult />;

  if (outcome.kind === "error") {
    return (
      <div
        key={resultKey}
        role="alert"
        className="animate-rise-in rounded-lg border border-destructive/30 bg-destructive/10 p-4 shadow-card"
      >
        <div className="flex items-start gap-3">
          <Icon name="alert" className="mt-0.5 size-5 text-destructive" />
          <div className="min-w-0 flex-1">
            <p className="text-sm font-semibold">Something went wrong</p>
            <p className="mt-1 break-words text-sm text-muted-foreground">{outcome.message}</p>
            <Button size="sm" className="mt-3" onClick={onRetry}>
              <Icon name="refresh" />
              Try again
            </Button>
          </div>
        </div>
      </div>
    );
  }

  if (outcome.kind === "clarification") {
    const unanswerable = outcome.data.kind === "unanswerable";
    return (
      <div key={resultKey} className="animate-rise-in rounded-lg border border-warning/40 bg-warning/10 p-4 shadow-card">
        <div className="flex items-start gap-3">
          <Icon name={unanswerable ? "alert" : "sparkles"} className="mt-0.5 size-5 text-warning-foreground" />
          <div className="min-w-0 flex-1">
            <p className="text-sm font-semibold">{outcome.data.message}</p>
            <ul className="mt-2 list-inside list-disc space-y-1 text-sm text-muted-foreground">
              {outcome.data.interpretations.map((reading) => (
                <li key={reading}>{reading}</li>
              ))}
            </ul>
            <p className="mt-3 text-xs text-muted-foreground">
              {unanswerable
                ? "Use Add / edit on your schema to include what's missing, then ask again."
                : "Rephrase the question to say which one you mean, then ask again."}
            </p>
          </div>
        </div>
      </div>
    );
  }

  const result = outcome.data;
  const dialectLabel = dialects.find((d) => d.id === result.dialect)?.label ?? result.dialect;

  if (result.guardrail_blocked) {
    return (
      <div key={resultKey} role="alert" className="animate-rise-in overflow-hidden rounded-lg border border-destructive/30 bg-card shadow-card">
        <div className="flex items-start gap-3 bg-destructive/10 p-4">
          <Icon name="shield" className="mt-0.5 size-5 text-destructive" />
          <div className="min-w-0">
            <p className="text-sm font-semibold">Blocked by guardrails</p>
            <p className="mt-1 text-sm text-muted-foreground">{result.block_reason}</p>
          </div>
        </div>
        <SqlBlock sql={result.sql} label="Blocked SQL" className="opacity-75" />
        <p className="px-4 py-3 text-xs text-muted-foreground">
          Only read-only SELECT queries are ever produced. Nothing was run.
        </p>
      </div>
    );
  }

  return (
    <div key={resultKey} className="animate-rise-in space-y-4">
      <div className="grid gap-4 xl:grid-cols-[minmax(0,1fr)_260px] xl:items-start">
        <CardShell
          dialectLabel={dialectLabel}
          actions={
            <>
              <CopyButton text={result.sql} label="Copy SQL" />
              <Button
                size="sm"
                className="hidden sm:inline-flex"
                onClick={() => downloadText("query.sql", `${result.sql}\n`)}
                aria-label="Download as a .sql file"
              >
                <Icon name="download" />
                .sql
              </Button>
            </>
          }
        >
          <SqlBlock sql={result.sql} />
          {(result.explanation || result.tables_used.length > 0) && (
            <div className="space-y-2.5 p-4 text-sm">
              {result.explanation && <p className="text-muted-foreground">{result.explanation}</p>}
              {result.tables_used.length > 0 && (
                <p className="flex flex-wrap items-center gap-1.5 text-xs text-muted-foreground">
                  Uses
                  {result.tables_used.map((table) => (
                    <Badge key={table} tone="muted">
                      {table}
                    </Badge>
                  ))}
                </p>
              )}
            </div>
          )}
        </CardShell>
        <ConfidenceGauge confidence={result.confidence} schemaProvided={result.schema_provided} dialectLabel={dialectLabel} />
      </div>

      {result.warnings.length > 0 && (
        <div className="space-y-1.5 rounded-lg border border-warning/40 bg-warning/10 p-3 text-sm">
          {result.warnings.map((warning) => (
            <p key={warning} className="flex items-start gap-2">
              <Icon name="alert" className="mt-0.5 text-warning-foreground" />
              <span>{warning}</span>
            </p>
          ))}
        </div>
      )}

      {!result.schema_provided && result.assumed_schema && (
        <section className="rounded-lg border border-border bg-card p-4 shadow-card">
          <h3 className="flex items-center gap-2 text-sm font-semibold">
            <Icon name="table" className="text-primary" />
            The schema I assumed
          </h3>
          <p className="mt-1 text-xs text-muted-foreground">
            You didn't give me a schema, so I guessed these tables. If they match your database, save them as your
            schema and every later answer is checked against them.
          </p>
          {result.assumptions.length > 0 && (
            <ul className="mt-3 list-inside list-disc space-y-0.5 text-xs text-muted-foreground">
              {result.assumptions.map((assumption) => (
                <li key={assumption}>{assumption}</li>
              ))}
            </ul>
          )}
          <SqlBlock sql={result.assumed_schema} label="Assumed schema" className="mt-3 max-h-56 rounded-md" />
          <div className="mt-3 flex flex-wrap items-center gap-2">
            {canAdoptSchema ? (
              <Button
                variant="primary"
                size="sm"
                loading={adoptingSchema}
                onClick={() => onAdoptSchema(result.assumed_schema as string)}
              >
                Use this as my schema
              </Button>
            ) : (
              <span className="text-xs text-muted-foreground">You already have a saved schema.</span>
            )}
            <CopyButton text={result.assumed_schema} label="Copy schema" />
          </div>
        </section>
      )}

      <p className={cn("text-center text-xs text-muted-foreground")}>
        Draft queries should be reviewed before running against production data.
      </p>
    </div>
  );
}
