import { useState } from "react";
import type { FormEvent } from "react";

interface Props {
  value: string;
  onChange: (value: string) => void;
  onSubmit: (question: string) => void;
  loading: boolean;
}

export default function QueryForm({ value, onChange, onSubmit, loading }: Props) {
  const [touched, setTouched] = useState(false);

  function handleSubmit(e: FormEvent) {
    e.preventDefault();
    setTouched(true);
    if (value.trim()) onSubmit(value.trim());
  }

  return (
    <form onSubmit={handleSubmit} className="flex gap-2">
      <input
        value={value}
        onChange={(e) => onChange(e.target.value)}
        placeholder="e.g. What are the top 5 best-selling products?"
        className="flex-1 rounded-lg border border-slate-700 bg-slate-900 px-4 py-2.5 text-sm text-slate-100 placeholder:text-slate-500 focus:border-indigo-500 focus:outline-none"
      />
      <button
        type="submit"
        disabled={loading}
        className="shrink-0 rounded-lg bg-indigo-600 px-5 py-2.5 text-sm font-medium text-white transition hover:bg-indigo-500 disabled:cursor-not-allowed disabled:opacity-50"
      >
        {loading ? "Thinking…" : "Ask"}
      </button>
      {touched && !value.trim() && (
        <span className="self-center text-xs text-red-400">Enter a question</span>
      )}
    </form>
  );
}
