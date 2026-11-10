import { useEffect, useState } from "react";

import { cn } from "../lib/cn";
import { percent } from "../lib/format";
import type { GenerateConfidence } from "../types";
import Icon from "./ui/Icon";

const RADIUS = 26;
const CIRCUMFERENCE = 2 * Math.PI * RADIUS;

function tone(score: number) {
  if (score >= 0.75) return { label: "High", stroke: "stroke-primary", text: "text-primary" };
  if (score >= 0.5) return { label: "Medium", stroke: "stroke-warning", text: "text-warning-foreground" };
  return { label: "Low", stroke: "stroke-destructive", text: "text-destructive" };
}

interface Props {
  confidence: GenerateConfidence;
  schemaProvided: boolean;
  dialectLabel: string;
}

export default function ConfidenceGauge({ confidence, schemaProvided, dialectLabel }: Props) {
  const target = Math.round(confidence.overall * 100);
  const { label, stroke, text } = tone(confidence.overall);

  // Start empty and fill on the next frame so the ring visibly animates in.
  const [shown, setShown] = useState(0);
  useEffect(() => {
    const frame = requestAnimationFrame(() => setShown(target));
    return () => cancelAnimationFrame(frame);
  }, [target]);

  const rows = [
    {
      name: "Matches your question",
      value: percent(confidence.back_translation_alignment),
      ok: confidence.back_translation_alignment >= 0.75,
    },
    {
      name: schemaProvided ? "Uses only your tables and columns" : "Consistent with the assumed schema",
      value: confidence.schema_check_passed ? "Yes" : "Flagged",
      ok: confidence.schema_check_passed,
    },
    {
      name: `Valid ${dialectLabel} syntax`,
      value: confidence.syntax_valid ? "Yes" : "No",
      ok: confidence.syntax_valid,
    },
    // Logic rules (NULL handling, division, GROUP BY, dates, dialect) and a trial run on test data.
    ...(confidence.logic_check_passed === undefined
      ? []
      : [
          {
            name: "Passed logic checks",
            value: confidence.logic_check_passed ? "Yes" : "Flagged",
            ok: confidence.logic_check_passed,
          },
        ]),
  ];

  return (
    <section aria-label="Confidence" className="rounded-lg border border-border bg-card p-4 shadow-card">
      <div className="flex items-center gap-4">
        <div className="relative size-16 shrink-0" role="img" aria-label={`Confidence ${target}% (${label})`}>
          <svg viewBox="0 0 64 64" className="size-full -rotate-90">
            <circle cx="32" cy="32" r={RADIUS} fill="none" strokeWidth="6" className="stroke-muted" />
            <circle
              cx="32"
              cy="32"
              r={RADIUS}
              fill="none"
              strokeWidth="6"
              strokeLinecap="round"
              strokeDasharray={CIRCUMFERENCE}
              strokeDashoffset={CIRCUMFERENCE * (1 - shown / 100)}
              className={cn("transition-[stroke-dashoffset] duration-700 ease-out", stroke)}
            />
          </svg>
          <span className="absolute inset-0 grid place-items-center text-sm font-semibold tabular-nums">{target}%</span>
        </div>
        <div>
          <p className="text-xs font-medium uppercase tracking-wider text-muted-foreground">Confidence</p>
          <p className={cn("text-xl font-semibold", text)}>{label}</p>
        </div>
      </div>

      <dl className="mt-4 space-y-2 border-t border-border pt-3 text-xs">
        {rows.map((row) => (
          <div key={row.name} className="flex items-start justify-between gap-3">
            <dt className="flex items-start gap-1.5 text-muted-foreground">
              <Icon
                name={row.ok ? "check" : "alert"}
                className={cn("mt-px size-3.5", row.ok ? "text-primary" : "text-warning-foreground")}
              />
              {row.name}
            </dt>
            <dd className={cn("font-medium tabular-nums", row.ok ? "text-foreground" : "text-warning-foreground")}>
              {row.value}
            </dd>
          </div>
        ))}
      </dl>

      {!schemaProvided && (
        <p className="mt-3 border-t border-border pt-3 text-xs text-muted-foreground">
          Capped at 60% because no schema was given, so table and column names are guesses.
        </p>
      )}
    </section>
  );
}
