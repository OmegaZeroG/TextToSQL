export interface ConfidenceBreakdown {
  syntax_valid: boolean;
  back_translation_alignment: number;
  result_sanity_passed: boolean;
  overall: number;
}

export interface QueryResponse {
  question: string;
  sql: string;
  explanation: string;
  columns: string[];
  rows: unknown[][];
  row_count: number;
  execution_time_ms: number;
  confidence: ConfidenceBreakdown;
  warnings: string[];
  guardrail_blocked: boolean;
  block_reason: string | null;
}

export interface ClarificationDetail {
  message: string;
  interpretations: string[];
}

export interface HistoryEntry {
  id: number;
  question: string;
  sql: string;
  row_count: number;
  confidence: number;
  created_at: string;
}

export interface SchemaResponse {
  schema: string;
  tables: string[];
}

export type QueryOutcome =
  | { kind: "success"; data: QueryResponse }
  | { kind: "clarification"; data: ClarificationDetail }
  | { kind: "error"; message: string };
