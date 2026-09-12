import type { ConfidenceBreakdown } from "../types";

function tone(score: number) {
  if (score >= 0.75) return { emoji: "🟢", color: "text-emerald-400", label: "High" };
  if (score >= 0.5) return { emoji: "🟡", color: "text-amber-400", label: "Medium" };
  return { emoji: "🔴", color: "text-red-400", label: "Low" };
}

export default function ConfidenceBadge({ confidence }: { confidence: ConfidenceBreakdown }) {
  const { emoji, color, label } = tone(confidence.overall);

  return (
    <div className="rounded-lg border border-slate-800 bg-slate-900/60 p-4">
      <div className="flex items-baseline justify-between">
        <span className="text-xs font-semibold uppercase tracking-wider text-slate-400">
          Confidence
        </span>
        <span className={`text-lg font-semibold ${color}`}>
          {emoji} {Math.round(confidence.overall * 100)}% ({label})
        </span>
      </div>
      <dl className="mt-3 space-y-1 text-xs text-slate-400">
        <div className="flex justify-between">
          <dt>Back-translation alignment</dt>
          <dd>{Math.round(confidence.back_translation_alignment * 100)}%</dd>
        </div>
        <div className="flex justify-between">
          <dt>Result sanity check</dt>
          <dd>{confidence.result_sanity_passed ? "passed" : "flagged"}</dd>
        </div>
        <div className="flex justify-between">
          <dt>SQL syntax</dt>
          <dd>{confidence.syntax_valid ? "valid" : "invalid"}</dd>
        </div>
      </dl>
    </div>
  );
}
