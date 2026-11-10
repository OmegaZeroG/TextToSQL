import type {
  ApiResult,
  Dialect,
  GenerateOutcome,
  GenerateResponse,
  SchemaAnalyzeResponse,
  SchemaUpdateResponse,
} from "./types";

// A trailing slash is easy to paste in (https://x.onrender.com/) and would make every call `//v1/...`.
export const API_URL = (import.meta.env.VITE_API_URL ?? "http://localhost:8000").trim().replace(/\/+$/, "");

export const FALLBACK_DIALECTS: Dialect[] = [
  { id: "postgres", label: "PostgreSQL" },
  { id: "mysql", label: "MySQL" },
  { id: "sqlite", label: "SQLite" },
  { id: "tsql", label: "SQL Server" },
  { id: "oracle", label: "Oracle" },
  { id: "bigquery", label: "BigQuery" },
  { id: "snowflake", label: "Snowflake" },
];

interface RawResponse {
  status: number;
  body: unknown;
}

function isAbort(err: unknown): boolean {
  return err instanceof DOMException && err.name === "AbortError";
}

async function request(path: string, init?: RequestInit): Promise<RawResponse> {
  const res = await fetch(`${API_URL}${path}`, init);
  let body: unknown = null;
  try {
    body = await res.json();
  } catch {
    // an error page or empty body: callers fall back to the status code
  }
  return { status: res.status, body };
}

function postJson(path: string, payload: unknown, signal?: AbortSignal): Promise<RawResponse> {
  return request(path, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
    signal,
  });
}

function detailOf(body: unknown): unknown {
  return (body as { detail?: unknown } | null)?.detail;
}

function messageFromDetail(detail: unknown, status: number): string {
  if (typeof detail === "string") return detail;
  if (Array.isArray(detail)) return "That request was rejected as invalid.";
  return `Request failed (${status}).`;
}

function networkMessage(err: unknown): string {
  const reason = err instanceof Error ? ` (${err.message})` : "";
  return `Couldn't reach the API${reason}. Is the backend running?`;
}

async function postForResult<T>(path: string, payload: unknown, signal?: AbortSignal): Promise<ApiResult<T>> {
  try {
    const { status, body } = await postJson(path, payload, signal);
    if (status >= 200 && status < 300) return { ok: true, data: body as T };
    return { ok: false, message: messageFromDetail(detailOf(body), status) };
  } catch (err) {
    if (isAbort(err)) return { ok: false, message: "Cancelled.", cancelled: true };
    return { ok: false, message: networkMessage(err) };
  }
}

/** True when the API answers /health. Resolves false on any failure or abort. */
export async function checkHealth(signal?: AbortSignal): Promise<boolean> {
  try {
    const { status } = await request("/health", { signal });
    return status === 200;
  } catch {
    return false;
  }
}

export async function fetchDialects(): Promise<Dialect[]> {
  try {
    const { status, body } = await request("/v1/dialects");
    if (status === 200 && Array.isArray(body) && body.length > 0) return body as Dialect[];
  } catch {
    // fall through to the built-in list
  }
  return FALLBACK_DIALECTS;
}

export function analyzeSchema(schemaText: string, dialect: string, signal?: AbortSignal) {
  return postForResult<SchemaAnalyzeResponse>(
    "/v1/schema/analyze",
    { schema_text: schemaText, dialect },
    signal,
  );
}

export function updateSchema(currentDdl: string, changeText: string, dialect: string, signal?: AbortSignal) {
  return postForResult<SchemaUpdateResponse>(
    "/v1/schema/update",
    { current_ddl: currentDdl, change_text: changeText, dialect },
    signal,
  );
}

export async function generateSql(
  question: string,
  schemaDdl: string | null,
  dialect: string,
  signal?: AbortSignal,
): Promise<GenerateOutcome> {
  try {
    const { status, body } = await postJson(
      "/v1/generate",
      { question, schema_ddl: schemaDdl, dialect },
      signal,
    );

    if (status === 200) return { kind: "success", data: body as GenerateResponse };

    const detail = detailOf(body);
    if (status === 422 && detail && typeof detail === "object" && !Array.isArray(detail)) {
      const d = detail as { kind?: string; message?: string; interpretations?: unknown };
      if (Array.isArray(d.interpretations)) {
        return {
          kind: "clarification",
          data: {
            kind: d.kind === "unanswerable" ? "unanswerable" : "ambiguous",
            message: d.message ?? "This question needs clarification.",
            interpretations: d.interpretations.filter((i): i is string => typeof i === "string"),
          },
        };
      }
    }
    return { kind: "error", message: messageFromDetail(detail, status) };
  } catch (err) {
    if (isAbort(err)) return { kind: "cancelled" };
    return { kind: "error", message: networkMessage(err) };
  }
}
