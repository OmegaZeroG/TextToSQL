import { act, render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import { FALLBACK_DIALECTS } from "../api";
import { downloadText } from "../lib/download";
import { makeResponse } from "../test/factories";
import type { GenerateOutcome } from "../types";
import ResultCard from "./ResultCard";

vi.mock("../lib/download", () => ({ downloadText: vi.fn() }));

function setup(outcome: GenerateOutcome | null, overrides: Partial<React.ComponentProps<typeof ResultCard>> = {}) {
  const props: React.ComponentProps<typeof ResultCard> = {
    outcome,
    loading: false,
    hasSchema: true,
    dialects: FALLBACK_DIALECTS,
    canAdoptSchema: true,
    adoptingSchema: false,
    onAdoptSchema: vi.fn(),
    onCancel: vi.fn(),
    onRetry: vi.fn(),
    resultKey: 1,
    ...overrides,
  };
  render(<ResultCard {...props} />);
  return { props, user: userEvent.setup() };
}

const success = (overrides = {}): GenerateOutcome => ({ kind: "success", data: makeResponse(overrides) });

describe("ResultCard, empty", () => {
  it.each([
    ["no outcome yet", null],
    ["a cancelled request", { kind: "cancelled" } as GenerateOutcome],
  ])("shows the placeholder for %s", (_label, outcome) => {
    setup(outcome);
    expect(screen.getByText("Your query will appear here")).toBeInTheDocument();
  });
});

describe("ResultCard, loading", () => {
  it("shows the steps and a Stop button", async () => {
    const { props, user } = setup(null, { loading: true });
    expect(screen.getByText("Reading your schema")).toBeInTheDocument();
    expect(screen.getByText("Writing the SQL")).toBeInTheDocument();
    expect(screen.getByText("Checking it against your question")).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: /stop/i }));
    expect(props.onCancel).toHaveBeenCalled();
  });

  it("says it is assuming a schema when there isn't one", () => {
    setup(null, { loading: true, hasSchema: false });
    expect(screen.getByText("Assuming a sensible schema")).toBeInTheDocument();
  });

  it("is marked busy for assistive technology", () => {
    setup(null, { loading: true });
    expect(document.querySelector('[aria-busy="true"]')).not.toBeNull();
  });

  it("warns that a sleeping free server can be slow, but only after a while", () => {
    vi.useFakeTimers({ toFake: ["setInterval", "clearInterval", "setTimeout", "clearTimeout", "Date", "performance"] });
    setup(null, { loading: true });
    expect(screen.queryByText(/free server may be waking up/i)).not.toBeInTheDocument();
    act(() => {
      vi.advanceTimersByTime(9000);
    });
    expect(screen.getByText(/free server may be waking up/i)).toBeInTheDocument();
  });
});

describe("ResultCard, failures", () => {
  it("shows an error with a way to retry", async () => {
    const { props, user } = setup({ kind: "error", message: "Couldn't reach the API" });
    expect(screen.getByRole("alert")).toHaveTextContent("Couldn't reach the API");
    await user.click(screen.getByRole("button", { name: /try again/i }));
    expect(props.onRetry).toHaveBeenCalledTimes(1);
  });

  it("lists the readings of an ambiguous question and says to rephrase", () => {
    setup({
      kind: "clarification",
      data: { kind: "ambiguous", message: "Several readings.", interpretations: ["gross", "net"] },
    });
    expect(screen.getByText("gross")).toBeInTheDocument();
    expect(screen.getByText("net")).toBeInTheDocument();
    expect(screen.getByText(/Rephrase the question/)).toBeInTheDocument();
  });

  it("says what is missing for an unanswerable question and points to Add / edit", () => {
    setup({
      kind: "clarification",
      data: { kind: "unanswerable", message: "Not in your schema.", interpretations: ["no shoe size column"] },
    });
    expect(screen.getByText("no shoe size column")).toBeInTheDocument();
    expect(screen.getByText(/Use Add \/ edit/)).toBeInTheDocument();
  });

  it("shows why SQL was blocked, shows the SQL, and offers no copy button", () => {
    setup(success({ guardrail_blocked: true, block_reason: "Blocked keyword 'DELETE'", sql: "DELETE FROM t" }));
    expect(screen.getByRole("alert")).toHaveTextContent("Blocked by guardrails");
    expect(screen.getByRole("alert")).toHaveTextContent("Blocked keyword 'DELETE'");
    expect(screen.getByLabelText("Blocked SQL")).toHaveTextContent("DELETE FROM t");
    expect(screen.queryByRole("button", { name: /copy sql/i })).not.toBeInTheDocument();
  });
});

describe("ResultCard, success", () => {
  it("shows the SQL, the explanation and the tables used", () => {
    setup(success({ sql: "SELECT 1", explanation: "Returns one.", tables_used: ["customers", "orders"] }));
    expect(screen.getByLabelText("SQL")).toHaveTextContent("SELECT 1");
    expect(screen.getByText("Returns one.")).toBeInTheDocument();
    expect(screen.getByText("customers")).toBeInTheDocument();
    expect(screen.getByText("orders")).toBeInTheDocument();
  });

  it("names the dialect", () => {
    setup(success({ dialect: "tsql" }));
    expect(screen.getByText("SQL Server")).toBeInTheDocument();
  });

  it("lists warnings", () => {
    setup(success({ warnings: ["Uses table(s) that aren't in your schema: 'ghost'."] }));
    expect(screen.getByText(/aren't in your schema/)).toBeInTheDocument();
  });

  it("downloads the SQL as a file", async () => {
    const { user } = setup(success({ sql: "SELECT 1" }));
    await user.click(screen.getByRole("button", { name: "Download as a .sql file" }));
    expect(downloadText).toHaveBeenCalledWith("query.sql", "SELECT 1\n");
  });

  it("does not show an assumed schema when a real one was used", () => {
    setup(success({ schema_provided: true }));
    expect(screen.queryByText("The schema I assumed")).not.toBeInTheDocument();
  });

  it("always carries the review disclaimer", () => {
    setup(success());
    expect(screen.getByText(/should be reviewed before running against production data/)).toBeInTheDocument();
  });
});

describe("ResultCard, assumed schema", () => {
  const assumed = {
    schema_provided: false,
    assumed_schema: "CREATE TABLE customers (id INT PRIMARY KEY);",
    assumptions: ["Assumed a customers table."],
  };

  it("shows the assumed schema and what was assumed", () => {
    setup(success(assumed));
    expect(screen.getByText("The schema I assumed")).toBeInTheDocument();
    expect(screen.getByText("Assumed a customers table.")).toBeInTheDocument();
    expect(screen.getByLabelText("Assumed schema")).toHaveTextContent("CREATE TABLE customers");
  });

  it("lets the user adopt it as their schema", async () => {
    const { props, user } = setup(success(assumed));
    await user.click(screen.getByRole("button", { name: "Use this as my schema" }));
    expect(props.onAdoptSchema).toHaveBeenCalledWith("CREATE TABLE customers (id INT PRIMARY KEY);");
  });

  it("does not offer to adopt it when a schema is already saved", () => {
    setup(success(assumed), { canAdoptSchema: false });
    expect(screen.queryByRole("button", { name: "Use this as my schema" })).not.toBeInTheDocument();
    expect(screen.getByText("You already have a saved schema.")).toBeInTheDocument();
  });

  it("shows progress while the schema is being saved", () => {
    setup(success(assumed), { adoptingSchema: true });
    const button = screen.getByRole("button", { name: "Use this as my schema" });
    expect(button).toBeDisabled();
    expect(button).toHaveAttribute("aria-busy", "true");
  });

  it("explains the confidence cap", () => {
    setup(success(assumed));
    expect(within(screen.getByRole("region", { name: "Confidence" })).getByText(/Capped at 60%/)).toBeInTheDocument();
  });
});
