import { describe, expect, it } from "vitest";

import { tokenizeSql } from "./sqlHighlight";

/** Tokens that carry meaning, as [kind, text] pairs (plain whitespace is dropped). */
function meaningful(sql: string) {
  return tokenizeSql(sql)
    .filter((t) => t.kind !== "plain" || t.text.trim() !== "")
    .map((t) => [t.kind, t.text.trim() === t.text ? t.text : t.text.trim()]);
}

const rebuild = (sql: string) => tokenizeSql(sql).map((t) => t.text).join("");

describe("tokenizeSql", () => {
  it("classifies keywords, functions, numbers and identifiers", () => {
    expect(meaningful("SELECT COUNT(*) FROM t WHERE x IN (1, 2)")).toEqual([
      ["keyword", "SELECT"],
      ["function", "COUNT"],
      ["plain", "(*)"],
      ["keyword", "FROM"],
      ["plain", "t"],
      ["keyword", "WHERE"],
      ["plain", "x"],
      ["keyword", "IN"],
      ["plain", "("],
      ["number", "1"],
      ["plain", ","],
      ["number", "2"],
      ["plain", ")"],
    ]);
  });

  it("matches keywords case-insensitively", () => {
    expect(meaningful("select * from t")[0]).toEqual(["keyword", "select"]);
    expect(meaningful("Select * From t")[0]).toEqual(["keyword", "Select"]);
  });

  it("does not call a keyword followed by a bracket a function", () => {
    const kinds = Object.fromEntries(meaningful("x IN (1) AND y OVER (PARTITION BY z)").map(([k, t]) => [t, k]));
    expect(kinds["IN"]).toBe("keyword");
    expect(kinds["OVER"]).toBe("keyword");
  });

  it("recognises a function even with a space before the bracket", () => {
    expect(meaningful("SUM (x)")[0]).toEqual(["function", "SUM"]);
  });

  it("treats a bare word that is not a keyword as plain", () => {
    expect(meaningful("name")).toEqual([["plain", "name"]]);
  });

  it("reads strings, including escaped quotes", () => {
    expect(meaningful("WHERE n = 'it''s ok'")).toContainEqual(["string", "'it''s ok'"]);
  });

  it("does not highlight keywords inside strings", () => {
    const tokens = tokenizeSql("SELECT 'select from where'");
    expect(tokens.filter((t) => t.kind === "keyword").map((t) => t.text)).toEqual(["SELECT"]);
  });

  it("reads line and block comments", () => {
    expect(meaningful("SELECT 1 -- pick one")).toContainEqual(["comment", "-- pick one"]);
    expect(meaningful("SELECT /* all */ 1")).toContainEqual(["comment", "/* all */"]);
  });

  it("does not highlight keywords inside comments", () => {
    const tokens = tokenizeSql("-- DROP TABLE x");
    expect(tokens).toEqual([{ kind: "comment", text: "-- DROP TABLE x" }]);
  });

  it("runs an unterminated block comment to the end", () => {
    expect(meaningful("SELECT 1 /* never closed")).toContainEqual(["comment", "/* never closed"]);
  });

  it("reads decimals as one number", () => {
    expect(meaningful("LIMIT 10.5")).toContainEqual(["number", "10.5"]);
  });

  it("keeps digits inside identifiers as part of the identifier", () => {
    expect(meaningful("t1")).toEqual([["plain", "t1"]]);
  });

  it("leaves quoted identifiers plain, whatever they contain", () => {
    expect(meaningful('"select" `from` [where]').every(([kind]) => kind === "plain")).toBe(true);
  });

  it("never loses or changes any text", () => {
    const samples = [
      "SELECT c.id,\n       c.name\nFROM customers c\nWHERE c.n = 'a' -- hi\n  AND x > 1.5;",
      "",
      "   ",
      "'",
      '"',
      "/*",
      "--",
      "`",
      "[",
      "((((",
      "SELECT 'unterminated",
      "é ñ 日本語 SELECT",
      "a".repeat(5000),
    ];
    for (const sql of samples) expect(rebuild(sql)).toBe(sql);
  });

  it("treats markup as inert text", () => {
    const html = "<script>alert(1)</script> SELECT 1";
    expect(rebuild(html)).toBe(html);
    expect(tokenizeSql(html).some((t) => t.kind === "keyword" && t.text === "SELECT")).toBe(true);
  });

  it("handles a large input quickly", () => {
    const sql = "SELECT a, b, c FROM t WHERE x = 1 AND y = 'z';\n".repeat(2000);
    const started = performance.now();
    expect(rebuild(sql)).toBe(sql);
    expect(performance.now() - started).toBeLessThan(1000);
  });
});
