import { describe, expect, it } from "vitest";

import { percent, plural, timeAgo } from "./format";

const NOW = 1_700_000_000_000;
const ago = (seconds: number) => NOW - seconds * 1000;

describe("timeAgo", () => {
  it.each([
    [0, "just now"],
    [30, "just now"],
    [44, "just now"],
    [60, "1 min ago"],
    [20 * 60, "20 min ago"],
    [2 * 3600, "2 h ago"],
    [23 * 3600, "23 h ago"],
    [24 * 3600, "1 day ago"],
    [3 * 24 * 3600, "3 days ago"],
  ])("%is ago reads %s", (seconds, expected) => {
    expect(timeAgo(ago(seconds), NOW)).toBe(expected);
  });

  it("never goes negative for a timestamp slightly in the future", () => {
    expect(timeAgo(NOW + 5000, NOW)).toBe("just now");
  });
});

describe("percent", () => {
  it.each([
    [0, "0%"],
    [0.876, "88%"],
    [1, "100%"],
  ])("%s -> %s", (value, expected) => {
    expect(percent(value)).toBe(expected);
  });
});

describe("plural", () => {
  it("only adds an s when the count is not one", () => {
    expect(plural(1, "table")).toBe("1 table");
    expect(plural(0, "table")).toBe("0 tables");
    expect(plural(2, "column")).toBe("2 columns");
  });
});
