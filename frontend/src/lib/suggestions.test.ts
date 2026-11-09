import { describe, expect, it } from "vitest";

import { CUSTOMERS_AND_ORDERS } from "../test/factories";
import type { SchemaTable } from "../types";
import { DEFAULT_EXAMPLES, suggestQuestions } from "./suggestions";

describe("suggestQuestions", () => {
  it("falls back to the generic examples without a schema", () => {
    expect(suggestQuestions(undefined)).toEqual(DEFAULT_EXAMPLES);
    expect(suggestQuestions([])).toEqual(DEFAULT_EXAMPLES);
  });

  it("builds questions from the user's own tables", () => {
    const suggestions = suggestQuestions(CUSTOMERS_AND_ORDERS);
    expect(suggestions).toContain("How many rows are in customers?");
    expect(suggestions.some((s) => s.includes("orders"))).toBe(true);
  });

  it("suggests a ranking on a numeric column that is not a key", () => {
    expect(suggestQuestions(CUSTOMERS_AND_ORDERS)).toContain("Top 5 orders by total");
  });

  it("uses a foreign key to suggest a join", () => {
    expect(suggestQuestions(CUSTOMERS_AND_ORDERS)).toContain("List each orders with its customers");
  });

  it("never ranks by a primary or foreign key", () => {
    const tables: SchemaTable[] = [
      {
        name: "t",
        columns: [
          { name: "id", type: "INT", primary_key: true },
          { name: "owner_id", type: "INT", foreign_key: "u.id" },
        ],
      },
    ];
    expect(suggestQuestions(tables).some((s) => s.startsWith("Top 5"))).toBe(false);
  });

  it("returns at most three suggestions", () => {
    expect(suggestQuestions(CUSTOMERS_AND_ORDERS).length).toBeLessThanOrEqual(3);
  });

  it("pads a bare schema so there is something to click", () => {
    const tables: SchemaTable[] = [{ name: "notes", columns: [{ name: "body", type: "TEXT" }] }];
    const suggestions = suggestQuestions(tables);
    expect(suggestions).toContain("How many rows are in notes?");
    expect(suggestions.length).toBeGreaterThan(1);
  });

  it("copes with schemas saved before keys were reported", () => {
    const old: SchemaTable[] = [{ name: "t", columns: [{ name: "price", type: "DECIMAL" }] }];
    expect(() => suggestQuestions(old)).not.toThrow();
    expect(suggestQuestions(old)).toContain("Top 5 t by price");
  });
});
