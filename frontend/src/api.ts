import type { HistoryEntry, QueryOutcome, QueryResponse, SchemaResponse } from "./types";

const API_URL = import.meta.env.VITE_API_URL ?? "http://localhost:8000";

export async function fetchSchema(): Promise<SchemaResponse> {
  const res = await fetch(`${API_URL}/v1/schema`);
  if (!res.ok) throw new Error(`Failed to load schema (${res.status})`);
  return res.json();
}

export async function fetchHistory(): Promise<HistoryEntry[]> {
  const res = await fetch(`${API_URL}/v1/history`);
  if (!res.ok) throw new Error(`Failed to load history (${res.status})`);
  return res.json();
}

export async function submitQuery(question: string): Promise<QueryOutcome> {
  try {
    const res = await fetch(`${API_URL}/v1/query`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ question }),
    });

    if (res.status === 422) {
      const body = await res.json();
      return { kind: "clarification", data: body.detail };
    }

    if (!res.ok) {
      const body = await res.json().catch(() => ({}));
      const message =
        typeof body.detail === "string" ? body.detail : `Request failed (${res.status})`;
      return { kind: "error", message };
    }

    const data: QueryResponse = await res.json();
    return { kind: "success", data };
  } catch (err) {
    return {
      kind: "error",
      message: err instanceof Error ? err.message : "Network error contacting the backend",
    };
  }
}
