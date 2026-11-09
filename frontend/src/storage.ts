import type { HistoryEntry, SavedSchema } from "./types";

const SCHEMA_KEY = "text-to-sql:schema:v1";
const DIALECT_KEY = "text-to-sql:dialect";
const THEME_KEY = "text-to-sql:theme";
const HISTORY_KEY = "text-to-sql:history:v1";

export const MAX_HISTORY = 15;

// Every access is wrapped: storage can throw (private windows, blocked site data)
// and the app must keep working without it.

export function loadSchema(): SavedSchema | null {
  try {
    const raw = localStorage.getItem(SCHEMA_KEY);
    if (!raw) return null;
    const value = JSON.parse(raw);
    if (value && typeof value.ddl === "string" && typeof value.dialect === "string" && Array.isArray(value.tables)) {
      return value as SavedSchema;
    }
  } catch {
    // corrupted or unavailable: behave as if nothing was saved
  }
  return null;
}

/** Returns false when the browser refused to store it. */
export function storeSchema(schema: SavedSchema): boolean {
  try {
    localStorage.setItem(SCHEMA_KEY, JSON.stringify(schema));
    return true;
  } catch {
    return false;
  }
}

export function clearStoredSchema(): void {
  try {
    localStorage.removeItem(SCHEMA_KEY);
  } catch {
    // nothing to clear
  }
}

export function loadDialect(): string | null {
  try {
    return localStorage.getItem(DIALECT_KEY);
  } catch {
    return null;
  }
}

export function storeDialect(dialect: string): void {
  try {
    localStorage.setItem(DIALECT_KEY, dialect);
  } catch {
    // preference simply won't persist
  }
}

export function loadTheme(): "light" | "dark" | null {
  try {
    const value = localStorage.getItem(THEME_KEY);
    return value === "light" || value === "dark" ? value : null;
  } catch {
    return null;
  }
}

export function storeTheme(theme: "light" | "dark"): void {
  try {
    localStorage.setItem(THEME_KEY, theme);
  } catch {
    // the choice simply won't persist
  }
}

function isHistoryEntry(value: unknown): value is HistoryEntry {
  const e = value as Partial<HistoryEntry> | null;
  return (
    !!e &&
    typeof e.id === "string" &&
    typeof e.question === "string" &&
    typeof e.sql === "string" &&
    typeof e.dialect === "string" &&
    typeof e.confidence === "number" &&
    typeof e.schemaProvided === "boolean" &&
    typeof e.createdAt === "number"
  );
}

export function loadHistory(): HistoryEntry[] {
  try {
    const raw = localStorage.getItem(HISTORY_KEY);
    if (!raw) return [];
    const value = JSON.parse(raw);
    return Array.isArray(value) ? value.filter(isHistoryEntry).slice(0, MAX_HISTORY) : [];
  } catch {
    return [];
  }
}

export function storeHistory(entries: HistoryEntry[]): void {
  try {
    localStorage.setItem(HISTORY_KEY, JSON.stringify(entries.slice(0, MAX_HISTORY)));
  } catch {
    // history simply won't persist
  }
}

export function clearStoredHistory(): void {
  try {
    localStorage.removeItem(HISTORY_KEY);
  } catch {
    // nothing to clear
  }
}
