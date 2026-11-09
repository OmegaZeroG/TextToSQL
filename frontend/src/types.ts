export interface Dialect {
  id: string;
  label: string;
}

export interface SchemaColumn {
  name: string;
  type: string;
  // Optional: schemas saved before keys were reported don't have them.
  primary_key?: boolean;
  foreign_key?: string | null;
}

export interface SchemaTable {
  name: string;
  columns: SchemaColumn[];
}

export interface SchemaAnalyzeResponse {
  dialect: string;
  source: "ddl" | "text";
  ddl: string;
  tables: SchemaTable[];
}

export interface SchemaUpdateResponse extends SchemaAnalyzeResponse {
  changes: string[];
}

/** What is kept in this browser's localStorage. */
export interface SavedSchema {
  ddl: string;
  dialect: string;
  tables: SchemaTable[];
  savedAt: number;
}

export interface GenerateConfidence {
  syntax_valid: boolean;
  back_translation_alignment: number;
  schema_check_passed: boolean;
  overall: number;
}

export interface GenerateResponse {
  question: string;
  dialect: string;
  sql: string;
  explanation: string;
  tables_used: string[];
  confidence: GenerateConfidence;
  warnings: string[];
  guardrail_blocked: boolean;
  block_reason: string | null;
  schema_provided: boolean;
  assumed_schema: string | null;
  assumptions: string[];
}

export interface Clarification {
  kind: "ambiguous" | "unanswerable";
  message: string;
  interpretations: string[];
}

export interface Status {
  kind: "success" | "error";
  message: string;
  details?: string[];
}

/** A past question, kept in this browser. */
export interface HistoryEntry {
  id: string;
  question: string;
  sql: string;
  dialect: string;
  confidence: number;
  schemaProvided: boolean;
  createdAt: number;
}

export type ApiResult<T> = { ok: true; data: T } | { ok: false; message: string; cancelled?: boolean };

export type GenerateOutcome =
  | { kind: "success"; data: GenerateResponse }
  | { kind: "clarification"; data: Clarification }
  | { kind: "error"; message: string }
  | { kind: "cancelled" };

export type ServerState = "checking" | "online" | "waking" | "offline";
