import { describe, expect, it, vi } from "vitest";

import {
  MAX_HISTORY,
  clearStoredHistory,
  clearStoredSchema,
  loadDialect,
  loadGuideSeen,
  loadHistory,
  loadSchema,
  loadTheme,
  storeDialect,
  storeGuideSeen,
  storeHistory,
  storeSchema,
  storeTheme,
} from "./storage";
import { makeSchema } from "./test/factories";
import type { HistoryEntry } from "./types";

function entry(n: number): HistoryEntry {
  return {
    id: `id-${n}`,
    question: `question ${n}`,
    sql: "SELECT 1",
    dialect: "postgres",
    confidence: 0.9,
    schemaProvided: true,
    createdAt: n,
  };
}

describe("schema storage", () => {
  it("round-trips a schema", () => {
    const schema = makeSchema();
    expect(storeSchema(schema)).toBe(true);
    expect(loadSchema()).toEqual(schema);
  });

  it("returns null when nothing is saved", () => {
    expect(loadSchema()).toBeNull();
  });

  it("clears a saved schema", () => {
    storeSchema(makeSchema());
    clearStoredSchema();
    expect(loadSchema()).toBeNull();
  });

  it.each([
    ["not json", "{oops"],
    ["wrong shape", JSON.stringify({ ddl: 5 })],
    ["null", "null"],
    ["missing tables", JSON.stringify({ ddl: "x", dialect: "postgres" })],
  ])("ignores a corrupted value (%s)", (_label, raw) => {
    localStorage.setItem("text-to-sql:schema:v1", raw);
    expect(loadSchema()).toBeNull();
  });

  it("reports failure instead of throwing when storage refuses the write", () => {
    vi.spyOn(Storage.prototype, "setItem").mockImplementation(() => {
      throw new DOMException("quota", "QuotaExceededError");
    });
    expect(storeSchema(makeSchema())).toBe(false);
  });

  it("behaves as empty when storage cannot be read at all", () => {
    vi.spyOn(Storage.prototype, "getItem").mockImplementation(() => {
      throw new Error("blocked");
    });
    expect(loadSchema()).toBeNull();
    expect(loadDialect()).toBeNull();
    expect(loadTheme()).toBeNull();
    expect(loadHistory()).toEqual([]);
  });
});

describe("preferences", () => {
  it("round-trips the dialect", () => {
    storeDialect("tsql");
    expect(loadDialect()).toBe("tsql");
  });

  it("only accepts light or dark as a theme", () => {
    storeTheme("dark");
    expect(loadTheme()).toBe("dark");
    localStorage.setItem("text-to-sql:theme", "purple");
    expect(loadTheme()).toBeNull();
  });
});

describe("history storage", () => {
  it("round-trips entries in order", () => {
    storeHistory([entry(2), entry(1)]);
    expect(loadHistory().map((e) => e.id)).toEqual(["id-2", "id-1"]);
  });

  it(`keeps only the newest ${MAX_HISTORY}`, () => {
    storeHistory(Array.from({ length: MAX_HISTORY + 5 }, (_, i) => entry(i)));
    expect(loadHistory()).toHaveLength(MAX_HISTORY);
  });

  it("drops malformed entries but keeps the good ones", () => {
    localStorage.setItem(
      "text-to-sql:history:v1",
      JSON.stringify([entry(1), { id: 1 }, null, "x", { ...entry(2), confidence: "high" }]),
    );
    expect(loadHistory().map((e) => e.id)).toEqual(["id-1"]);
  });

  it("returns an empty list for non-array or invalid JSON", () => {
    localStorage.setItem("text-to-sql:history:v1", JSON.stringify({ a: 1 }));
    expect(loadHistory()).toEqual([]);
    localStorage.setItem("text-to-sql:history:v1", "{nope");
    expect(loadHistory()).toEqual([]);
  });

  it("can be cleared", () => {
    storeHistory([entry(1)]);
    clearStoredHistory();
    expect(loadHistory()).toEqual([]);
  });

  it("does not throw when storage refuses the write", () => {
    vi.spyOn(Storage.prototype, "setItem").mockImplementation(() => {
      throw new Error("full");
    });
    expect(() => storeHistory([entry(1)])).not.toThrow();
  });
});

describe("guide storage", () => {
  it("remembers that the guide was opened", () => {
    expect(loadGuideSeen()).toBe(false);
    storeGuideSeen();
    expect(loadGuideSeen()).toBe(true);
  });

  it("survives storage being blocked", () => {
    const blocked = vi.spyOn(Storage.prototype, "getItem").mockImplementation(() => {
      throw new Error("blocked");
    });
    const blockedSet = vi.spyOn(Storage.prototype, "setItem").mockImplementation(() => {
      throw new Error("blocked");
    });
    expect(loadGuideSeen()).toBe(false);
    expect(() => storeGuideSeen()).not.toThrow();
    blocked.mockRestore();
    blockedSet.mockRestore();
  });
});
