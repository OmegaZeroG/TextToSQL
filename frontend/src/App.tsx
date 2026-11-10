import { useEffect, useMemo, useRef, useState } from "react";

import { FALLBACK_DIALECTS, analyzeSchema, fetchDialects, generateSql, updateSchema } from "./api";
import GuideTour from "./components/GuideTour";
import Header from "./components/Header";
import HistoryList from "./components/HistoryList";
import QuestionCard from "./components/QuestionCard";
import ResultCard from "./components/ResultCard";
import SchemaCard from "./components/SchemaCard";
import Icon from "./components/ui/Icon";
import { useServerStatus } from "./hooks/useServerStatus";
import { useTheme } from "./hooks/useTheme";
import { plural } from "./lib/format";
import { suggestQuestions } from "./lib/suggestions";
import {
  MAX_HISTORY,
  clearStoredHistory,
  clearStoredSchema,
  loadDialect,
  loadGuideSeen,
  loadHistory,
  loadSchema,
  storeDialect,
  storeGuideSeen,
  storeHistory,
  storeSchema,
} from "./storage";
import type {
  Dialect,
  GenerateOutcome,
  HistoryEntry,
  SavedSchema,
  SchemaTable,
  Status,
} from "./types";

const STORAGE_WARNING = "This browser blocked storage, so the schema will be forgotten when you refresh.";

function countColumns(tables: SchemaTable[]): number {
  return tables.reduce((sum, t) => sum + t.columns.length, 0);
}

function newId(): string {
  return `${Date.now().toString(36)}-${Math.random().toString(36).slice(2, 8)}`;
}

export default function App() {
  const { theme, toggle: toggleTheme } = useTheme();
  const server = useServerStatus();

  const [dialects, setDialects] = useState<Dialect[]>(FALLBACK_DIALECTS);
  const [schema, setSchema] = useState<SavedSchema | null>(() => loadSchema());
  const [dialectId, setDialectId] = useState<string>(() => loadSchema()?.dialect ?? loadDialect() ?? "postgres");
  const [draft, setDraft] = useState("");
  const [schemaBusy, setSchemaBusy] = useState(false);
  const [schemaStatus, setSchemaStatus] = useState<Status | null>(null);

  const [question, setQuestion] = useState("");
  const [generating, setGenerating] = useState(false);
  const [outcome, setOutcome] = useState<GenerateOutcome | null>(null);
  const [resultKey, setResultKey] = useState(0);
  const [announcement, setAnnouncement] = useState("");
  const [history, setHistory] = useState<HistoryEntry[]>(() => loadHistory());
  const [guideOpen, setGuideOpen] = useState(false);
  const [guideSeen, setGuideSeen] = useState(() => loadGuideSeen());

  // Each request gets an id; a response is applied only if it is still the latest,
  // so a slow, stopped or superseded request can never overwrite a newer result.
  const requestId = useRef(0);
  const abortRef = useRef<AbortController | null>(null);
  const resultRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    fetchDialects().then(setDialects);
  }, []);

  useEffect(() => {
    storeHistory(history);
  }, [history]);

  const suggestions = useMemo(() => suggestQuestions(schema?.tables), [schema]);

  function openGuide() {
    setGuideOpen(true);
    setGuideSeen(true);
    storeGuideSeen();
  }

  function handleDialectChange(id: string) {
    setDialectId(id);
    storeDialect(id);
  }

  /** Reads a schema (DDL, plain English, or a list) and saves it in this browser. */
  async function saveSchemaText(text: string): Promise<SavedSchema | null> {
    setSchemaBusy(true);
    setSchemaStatus(null);
    const result = await analyzeSchema(text, dialectId);
    setSchemaBusy(false);

    if (!result.ok) {
      setSchemaStatus({ kind: "error", message: result.message });
      return null;
    }
    server.markOnline();

    const saved: SavedSchema = {
      ddl: result.data.ddl,
      dialect: result.data.dialect,
      tables: result.data.tables,
      savedAt: Date.now(),
    };
    const stored = storeSchema(saved);
    setSchema(saved);
    setDialectId(saved.dialect);
    setDraft("");

    const details: string[] = [];
    if (result.data.source === "text") details.push("Read from your description. Check the tables below are what you meant.");
    if (!stored) details.push(STORAGE_WARNING);
    setSchemaStatus({
      kind: "success",
      message: `Schema saved: ${plural(saved.tables.length, "table")}, ${plural(countColumns(saved.tables), "column")}.`,
      details,
    });
    return saved;
  }

  async function handleApplyChange(changeText: string): Promise<boolean> {
    if (!schema) return false;
    setSchemaBusy(true);
    setSchemaStatus(null);
    const result = await updateSchema(schema.ddl, changeText, schema.dialect);
    setSchemaBusy(false);

    if (!result.ok) {
      setSchemaStatus({ kind: "error", message: result.message });
      return false;
    }

    const saved: SavedSchema = {
      ddl: result.data.ddl,
      dialect: result.data.dialect,
      tables: result.data.tables,
      savedAt: Date.now(),
    };
    const stored = storeSchema(saved);
    setSchema(saved);
    setSchemaStatus({
      kind: "success",
      message: "Schema updated.",
      details: stored ? result.data.changes : [...result.data.changes, STORAGE_WARNING],
    });
    return true;
  }

  function handleReset() {
    clearStoredSchema();
    setSchema(null);
    setSchemaStatus({ kind: "success", message: "Schema reset. It was removed from this browser." });
  }

  function scrollToResult() {
    if (!window.matchMedia("(max-width: 1023px)").matches) return;
    const reduced = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
    requestAnimationFrame(() =>
      resultRef.current?.scrollIntoView({ behavior: reduced ? "auto" : "smooth", block: "start" }),
    );
  }

  async function handleSubmit() {
    if (generating || schemaBusy) return;
    const trimmedQuestion = question.trim();
    const trimmedDraft = draft.trim();

    let active = schema;
    if (!active && trimmedDraft) {
      active = await saveSchemaText(trimmedDraft);
      if (!active) return;
    }
    if (!trimmedQuestion) return; // schema only: it has been saved, nothing to generate

    abortRef.current?.abort();
    const controller = new AbortController();
    abortRef.current = controller;
    const id = ++requestId.current;

    setGenerating(true);
    setOutcome(null);
    setAnnouncement("Generating SQL.");
    const result = await generateSql(
      trimmedQuestion,
      active?.ddl ?? null,
      active?.dialect ?? dialectId,
      controller.signal,
    );
    if (id !== requestId.current) return; // stopped or superseded

    setGenerating(false);
    if (result.kind === "cancelled") return;

    setOutcome(result);
    setResultKey((key) => key + 1);
    if (result.kind === "success") {
      server.markOnline();
      const data = result.data;
      if (data.guardrail_blocked) {
        setAnnouncement("That request was blocked by the guardrails.");
      } else {
        setAnnouncement(`SQL generated. Confidence ${Math.round(data.confidence.overall * 100)} percent.`);
        const entry: HistoryEntry = {
          id: newId(),
          question: data.question,
          sql: data.sql,
          dialect: data.dialect,
          confidence: data.confidence.overall,
          schemaProvided: data.schema_provided,
          createdAt: Date.now(),
        };
        setHistory((previous) => [entry, ...previous].slice(0, MAX_HISTORY));
      }
    } else if (result.kind === "clarification") {
      setAnnouncement(result.data.message);
    } else {
      setAnnouncement("Something went wrong.");
    }
    scrollToResult();
  }

  function handleCancel() {
    requestId.current += 1;
    abortRef.current?.abort();
    setGenerating(false);
    setOutcome(null);
    setAnnouncement("Stopped.");
  }

  function handleUseHistory(entry: HistoryEntry) {
    setQuestion(entry.question);
    window.scrollTo({ top: 0, behavior: "smooth" });
    document.getElementById("question")?.focus({ preventScroll: true });
  }

  function handleClearHistory() {
    setHistory([]);
    clearStoredHistory();
  }

  const activeDialectId = schema?.dialect ?? dialectId;
  const dialectLabel = dialects.find((d) => d.id === activeDialectId)?.label ?? activeDialectId;
  const hasQuestion = question.trim().length > 0;
  const hasDraft = !schema && draft.trim().length > 0;

  return (
    <div className="min-h-dvh">
      <a
        href="#main"
        className="sr-only z-50 rounded-md bg-primary px-3 py-2 text-sm text-primary-foreground focus:not-sr-only focus:fixed focus:left-4 focus:top-4"
      >
        Skip to content
      </a>
      <Header
        server={server.state}
        onRetry={server.retry}
        theme={theme}
        onToggleTheme={toggleTheme}
        onOpenGuide={openGuide}
        guideHint={!guideSeen}
      />

      <main id="main" className="mx-auto max-w-6xl px-4 pb-safe pt-8 sm:px-6 sm:pt-12">
        {server.state === "offline" && (
          <p
            role="note"
            className="mb-6 flex animate-scale-in items-start gap-2.5 rounded-lg border border-warning/40 bg-warning/10 p-3 text-sm"
          >
            <Icon name="alert" className="mt-0.5 shrink-0 text-warning-foreground" />
            <span>
              Can't reach the server. If you use an ad or content blocker (for example Brave Shields or uBlock),
              turn it off for this site and press Retry. A free server that has been idle can also take up to a
              minute to wake.
            </span>
          </p>
        )}
        <section className="mb-8 max-w-3xl animate-rise-in sm:mb-10">
          <p className="mb-3 flex items-center gap-2 font-mono text-[11px] font-medium uppercase tracking-[0.14em] text-primary">
            <span aria-hidden="true">&lt;/&gt;</span>
            A quieter way to query
          </p>
          <h1 className="font-serif text-[2.6rem] leading-[1.04] sm:text-5xl lg:text-6xl">
            Words in. <span className="text-primary">SQL out.</span>
          </h1>
          <p className="mt-4 max-w-xl text-[15px] text-muted-foreground sm:text-base">
            Ask a question about your data. Add your schema for a query shaped around your tables.
          </p>
        </section>

        {/* One column on phones (question first, schema second); on desktop the schema sits beside the rest. */}
        <div className="grid gap-5 lg:grid-cols-[minmax(300px,340px)_minmax(0,1fr)] lg:gap-6">
          <QuestionCard
            className="order-1 animate-rise-in [animation-delay:90ms] lg:col-start-2 lg:row-start-1"
            question={question}
            onQuestionChange={setQuestion}
            onSubmit={handleSubmit}
            onCancel={handleCancel}
            generating={generating}
            busy={schemaBusy}
            canSubmit={hasQuestion || hasDraft}
            hasSchema={schema !== null}
            hasSchemaDraft={hasDraft}
            dialects={dialects}
            dialectId={activeDialectId}
            dialectLocked={schema !== null}
            onDialectChange={handleDialectChange}
            suggestions={suggestions}
          />

          <SchemaCard
            className="order-2 animate-rise-in [animation-delay:150ms] lg:sticky lg:top-20 lg:col-start-1 lg:row-span-3 lg:row-start-1 lg:self-start"
            schema={schema}
            dialectLabel={dialectLabel}
            draft={draft}
            onDraftChange={setDraft}
            busy={schemaBusy}
            status={schemaStatus}
            onSave={() => void saveSchemaText(draft.trim())}
            onApplyChange={handleApplyChange}
            onReset={handleReset}
            onDismissStatus={() => setSchemaStatus(null)}
            onFileError={(message) => setSchemaStatus({ kind: "error", message })}
          />

          <div ref={resultRef} data-guide="result" className="order-3 scroll-mt-20 lg:col-start-2 lg:row-start-2">
            <ResultCard
              outcome={outcome}
              loading={generating}
              hasSchema={schema !== null}
              dialects={dialects}
              canAdoptSchema={schema === null}
              adoptingSchema={schemaBusy}
              onAdoptSchema={(ddl) => void saveSchemaText(ddl)}
              onCancel={handleCancel}
              onRetry={handleSubmit}
              resultKey={resultKey}
            />
          </div>

          <div className="order-4 lg:col-start-2 lg:row-start-3">
            <HistoryList items={history} dialects={dialects} onUse={handleUseHistory} onClear={handleClearHistory} />
          </div>
        </div>
      </main>

      <GuideTour open={guideOpen} onClose={() => setGuideOpen(false)} />

      <div className="sr-only" role="status" aria-live="polite">
        {announcement}
      </div>
    </div>
  );
}
