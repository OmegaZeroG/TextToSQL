import { useEffect } from "react";

import { cn } from "../lib/cn";
import { MAX_QUESTION_CHARS } from "../lib/limits";
import type { Dialect } from "../types";
import Button from "./ui/Button";
import Icon from "./ui/Icon";

interface Props {
  question: string;
  onQuestionChange: (value: string) => void;
  onSubmit: () => void;
  onCancel: () => void;
  generating: boolean;
  busy: boolean;
  canSubmit: boolean;
  hasSchema: boolean;
  hasSchemaDraft: boolean;
  dialects: Dialect[];
  dialectId: string;
  dialectLocked: boolean;
  onDialectChange: (id: string) => void;
  suggestions: string[];
  className?: string;
}

export default function QuestionCard({
  question,
  onQuestionChange,
  onSubmit,
  onCancel,
  generating,
  busy,
  canSubmit,
  hasSchema,
  hasSchemaDraft,
  dialects,
  dialectId,
  dialectLocked,
  onDialectChange,
  suggestions,
  className,
}: Props) {
  const schemaOnly = !question.trim() && hasSchemaDraft;
  const nearLimit = question.length >= MAX_QUESTION_CHARS * 0.9;

  // Listens on the window so the shortcut works wherever focus is (the dialect select,
  // a guide button), not only inside the textarea.
  const ready = canSubmit && !busy && !generating;
  useEffect(() => {
    function onKeyDown(event: globalThis.KeyboardEvent) {
      if (event.key === "Enter" && (event.ctrlKey || event.metaKey)) {
        event.preventDefault(); // also stops a focused button from being "clicked" by it
        if (ready) onSubmit();
      }
    }
    window.addEventListener("keydown", onKeyDown);
    return () => window.removeEventListener("keydown", onKeyDown);
  }, [ready, onSubmit]);

  const hint = hasSchema
    ? "Answers are checked against your saved schema."
    : hasSchemaDraft
      ? "Your schema will be saved first, then used for this question."
      : "No schema? I'll assume sensible tables and tell you exactly what I assumed.";

  return (
    <section
      aria-label="Question"
      className={cn("overflow-hidden rounded-lg border border-border bg-card shadow-card", className)}
    >
      <header className="border-b border-border px-4 py-3.5 sm:px-5">
        <h2 className="flex items-center gap-2 text-sm font-semibold">
          <Icon name="sparkles" className="text-primary" />
          What would you like to know?
        </h2>
        <p className="mt-1 text-xs text-muted-foreground">Describe the result you're looking for in plain English.</p>
      </header>

      <div className="space-y-4 p-4 sm:p-5">
        <div className="relative" data-guide="question">
          <label htmlFor="question" className="sr-only">
            Your question
          </label>
          <textarea
            id="question"
            value={question}
            onChange={(event) => onQuestionChange(event.target.value)}
            maxLength={MAX_QUESTION_CHARS}
            rows={4}
            placeholder={`e.g. ${suggestions[0] ?? "Top 5 customers by total spend last month"}`}
            className="min-h-[7.5rem] w-full resize-y rounded-md border border-input bg-background p-4 pb-8 leading-relaxed transition-shadow placeholder:text-muted-foreground/70 focus:border-ring focus:outline-none focus:ring-2 focus:ring-ring/30"
          />
          <span
            className={cn(
              "pointer-events-none absolute bottom-2.5 right-3 text-[11px] tabular-nums",
              nearLimit ? "text-warning-foreground" : "text-muted-foreground/70",
            )}
            aria-hidden="true"
          >
            {question.length}/{MAX_QUESTION_CHARS}
          </span>
        </div>

        <div className="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
          <div className="flex items-center gap-2.5">
            <label htmlFor="dialect" className="text-xs text-muted-foreground">
              SQL dialect
            </label>
            <div className="relative" data-guide="dialect">
              <select
                id="dialect"
                value={dialectId}
                disabled={dialectLocked}
                onChange={(event) => onDialectChange(event.target.value)}
                title={dialectLocked ? "Set by your saved schema. Reset the schema to change it." : undefined}
                className="h-11 min-w-[9rem] cursor-pointer appearance-none rounded-md border border-input bg-background pl-3 pr-9 text-sm transition-colors hover:bg-muted focus:border-ring focus:outline-none focus:ring-2 focus:ring-ring/30 disabled:cursor-not-allowed disabled:opacity-60 sm:h-10"
              >
                {dialects.map((dialect) => (
                  <option key={dialect.id} value={dialect.id}>
                    {dialect.label}
                  </option>
                ))}
              </select>
              <Icon name="chevronDown" className="pointer-events-none absolute right-3 top-1/2 -translate-y-1/2 text-muted-foreground" />
            </div>
          </div>

          <div className="flex items-center gap-2">
            {generating && (
              <Button onClick={onCancel} className="flex-1 sm:flex-none">
                <Icon name="stop" className="size-3.5" />
                Stop
              </Button>
            )}
            <Button
              variant="primary"
              onClick={onSubmit}
              loading={generating || busy}
              disabled={!canSubmit}
              data-guide="generate"
              className="flex-1 sm:flex-none sm:min-w-[9.5rem]"
            >
              {generating ? "Generating" : busy ? "Working" : schemaOnly ? "Save schema" : "Generate SQL"}
              {!generating && !busy && <Icon name="arrowRight" />}
            </Button>
          </div>
        </div>

        <p className="text-xs text-muted-foreground">
          {hint}
          <span className="hidden md:inline">
            {" "}
            <kbd className="rounded border border-border bg-muted px-1 py-0.5 font-mono text-[10px]">Ctrl</kbd>
            {" + "}
            <kbd className="rounded border border-border bg-muted px-1 py-0.5 font-mono text-[10px]">Enter</kbd> to submit.
          </span>
        </p>

        <div className="border-t border-border pt-4">
          <p className="mb-2.5 text-xs text-muted-foreground">Try an example</p>
          <div className="scrollbar-thin -mx-4 flex snap-x gap-2 overflow-x-auto px-4 pb-1 max-sm:[-ms-overflow-style:none] max-sm:[scrollbar-width:none] max-sm:[&::-webkit-scrollbar]:hidden sm:mx-0 sm:flex-wrap sm:px-0">
            {suggestions.map((example) => {
              const selected = example === question;
              return (
                <button
                  key={example}
                  type="button"
                  onClick={() => onQuestionChange(example)}
                  aria-pressed={selected}
                  className={cn(
                    "shrink-0 snap-start touch-manipulation rounded-full border px-3.5 py-2 text-xs transition-colors duration-150 active:scale-[0.98]",
                    selected
                      ? "border-primary/40 bg-accent text-accent-foreground"
                      : "border-border bg-card text-muted-foreground hover:bg-muted hover:text-foreground",
                  )}
                >
                  {example}
                </button>
              );
            })}
          </div>
        </div>
      </div>
    </section>
  );
}
