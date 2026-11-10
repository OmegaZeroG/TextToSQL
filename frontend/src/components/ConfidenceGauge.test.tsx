import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { makeResponse } from "../test/factories";
import ConfidenceGauge from "./ConfidenceGauge";

function gauge(overall: number, overrides = {}, schemaProvided = true) {
  const confidence = { ...makeResponse().confidence, overall, ...overrides };
  render(<ConfidenceGauge confidence={confidence} schemaProvided={schemaProvided} dialectLabel="PostgreSQL" />);
}

describe("ConfidenceGauge", () => {
  it.each([
    [0.97, "High"],
    [0.75, "High"],
    [0.6, "Medium"],
    [0.5, "Medium"],
    [0.49, "Low"],
    [0, "Low"],
  ])("rates %s as %s", (overall, label) => {
    gauge(overall);
    expect(screen.getByRole("img", { name: new RegExp(`${label}`) })).toBeInTheDocument();
    expect(screen.getByText(label)).toBeInTheDocument();
  });

  it("exposes the percentage to assistive technology", () => {
    gauge(0.876);
    expect(screen.getByRole("img")).toHaveAttribute("aria-label", "Confidence 88% (High)");
  });

  it("explains each signal in plain words", () => {
    gauge(0.9, { back_translation_alignment: 0.95 });
    expect(screen.getByText("Matches your question")).toBeInTheDocument();
    expect(screen.getByText("95%")).toBeInTheDocument();
    expect(screen.getByText("Uses only your tables and columns")).toBeInTheDocument();
    expect(screen.getByText("Valid PostgreSQL syntax")).toBeInTheDocument();
  });

  it("flags a failed schema check", () => {
    gauge(0.4, { schema_check_passed: false });
    expect(screen.getByText("Flagged")).toBeInTheDocument();
  });

  it("shows the logic check, and flags it when it fails", () => {
    gauge(0.7);
    expect(screen.getByText("Passed logic checks")).toBeInTheDocument();
    expect(screen.queryByText("Flagged")).not.toBeInTheDocument();
  });

  it("flags a failed logic check", () => {
    gauge(0.6, { logic_check_passed: false });
    expect(screen.getByText("Passed logic checks")).toBeInTheDocument();
    expect(screen.getByText("Flagged")).toBeInTheDocument();
  });

  it("hides the logic row when the server is too old to report it", () => {
    gauge(0.9, { logic_check_passed: undefined });
    expect(screen.queryByText("Passed logic checks")).not.toBeInTheDocument();
  });

  it("flags invalid syntax", () => {
    gauge(0.2, { syntax_valid: false });
    expect(screen.getByText("No")).toBeInTheDocument();
  });

  it("talks about the assumed schema, and the 60% cap, only when no schema was given", () => {
    gauge(0.6, {}, false);
    expect(screen.getByText("Consistent with the assumed schema")).toBeInTheDocument();
    expect(screen.getByText(/Capped at 60%/)).toBeInTheDocument();
  });

  it("does not mention the cap when a schema was given", () => {
    gauge(0.9);
    expect(screen.queryByText(/Capped at 60%/)).not.toBeInTheDocument();
  });
});
