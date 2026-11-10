import { act, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("./api", async (importOriginal) => {
  const actual = await importOriginal<typeof import("./api")>();
  return {
    ...actual,
    checkHealth: vi.fn(),
    fetchDialects: vi.fn(),
    analyzeSchema: vi.fn(),
    updateSchema: vi.fn(),
    generateSql: vi.fn(),
  };
});

import * as api from "./api";
import App from "./App";
import { GUIDE_STEPS } from "./lib/guideSteps";
import { loadHistory, loadSchema, storeHistory, storeSchema } from "./storage";
import { CUSTOMERS_AND_ORDERS, CUSTOMERS_AND_ORDERS_DDL, makeResponse, makeSchema } from "./test/factories";
import type { GenerateOutcome, HistoryEntry } from "./types";

const analyzed = {
  ok: true as const,
  data: { dialect: "postgres", source: "ddl" as const, ddl: CUSTOMERS_AND_ORDERS_DDL, tables: CUSTOMERS_AND_ORDERS },
};

const generated = (overrides = {}): GenerateOutcome => ({ kind: "success", data: makeResponse(overrides) });

beforeEach(() => {
  vi.mocked(api.checkHealth).mockResolvedValue(true);
  vi.mocked(api.fetchDialects).mockResolvedValue(api.FALLBACK_DIALECTS);
  vi.mocked(api.generateSql).mockResolvedValue(generated());
  vi.mocked(api.analyzeSchema).mockResolvedValue(analyzed);
  vi.mocked(api.updateSchema).mockResolvedValue({ ok: false, message: "not expected" });
});

function setup() {
  const user = userEvent.setup();
  render(<App />);
  return { user };
}

const questionBox = () => screen.getByLabelText("Your question");
const questionCard = () => within(screen.getByRole("region", { name: "Question" }));
const schemaCard = () => within(screen.getByRole("complementary", { name: "Schema" }));

async function ask(user: ReturnType<typeof userEvent.setup>, text: string) {
  await user.type(questionBox(), text);
  await user.click(questionCard().getByRole("button", { name: /generate sql/i }));
}

/** A promise the test resolves by hand, to control when "the server" answers. */
function deferred<T>() {
  let resolve!: (value: T) => void;
  const promise = new Promise<T>((r) => {
    resolve = r;
  });
  return { promise, resolve };
}

describe("asking a question with no schema", () => {
  it("sends no schema and shows the SQL, the assumed schema and the cap", async () => {
    vi.mocked(api.generateSql).mockResolvedValue(
      generated({
        sql: "SELECT id FROM customers",
        schema_provided: false,
        assumed_schema: "CREATE TABLE customers (id INT PRIMARY KEY);",
        assumptions: ["Assumed a customers table."],
        warnings: ["No schema was provided, so table and column names are assumed."],
      }),
    );
    const { user } = setup();

    await ask(user, "all customers");

    expect(await screen.findByLabelText("SQL")).toHaveTextContent("SELECT id FROM customers");
    expect(api.generateSql).toHaveBeenCalledWith("all customers", null, "postgres", expect.any(AbortSignal));
    expect(screen.getByText("The schema I assumed")).toBeInTheDocument();
    expect(screen.getByText(/No schema was provided/)).toBeInTheDocument();
  });

  it("can adopt the assumed schema as the saved one in a single click", async () => {
    vi.mocked(api.generateSql).mockResolvedValue(
      generated({ schema_provided: false, assumed_schema: CUSTOMERS_AND_ORDERS_DDL }),
    );
    const { user } = setup();
    await ask(user, "all customers");

    await user.click(await screen.findByRole("button", { name: "Use this as my schema" }));

    expect(api.analyzeSchema).toHaveBeenCalledWith(CUSTOMERS_AND_ORDERS_DDL, "postgres");
    expect(await schemaCard().findByText(/Schema saved: 2 tables, 5 columns/)).toBeInTheDocument();
    expect(loadSchema()?.ddl).toBe(CUSTOMERS_AND_ORDERS_DDL);
    expect(screen.queryByRole("button", { name: "Use this as my schema" })).not.toBeInTheDocument();
  });

  it("remembers the dialect the user picks", async () => {
    const { user } = setup();
    await user.selectOptions(screen.getByLabelText("SQL dialect"), "tsql");
    await ask(user, "q");
    await waitFor(() => expect(api.generateSql).toHaveBeenCalledWith("q", null, "tsql", expect.any(AbortSignal)));
    expect(localStorage.getItem("text-to-sql:dialect")).toBe("tsql");
  });
});

describe("asking with a saved schema", () => {
  beforeEach(() => {
    storeSchema(makeSchema());
  });

  it("sends the saved schema and locks the dialect to it", async () => {
    const { user } = setup();
    expect(screen.getByLabelText("SQL dialect")).toBeDisabled();

    await ask(user, "orders per customer");

    await waitFor(() =>
      expect(api.generateSql).toHaveBeenCalledWith(
        "orders per customer",
        CUSTOMERS_AND_ORDERS_DDL,
        "postgres",
        expect.any(AbortSignal),
      ),
    );
  });

  it("offers example questions built from the saved tables", () => {
    setup();
    expect(questionCard().getByRole("button", { name: "How many rows are in customers?" })).toBeInTheDocument();
    expect(questionCard().getByRole("button", { name: "Top 5 orders by total" })).toBeInTheDocument();
  });

  it("shows the saved tables with their keys", () => {
    setup();
    expect(schemaCard().getByRole("list", { name: "Tables" })).toBeInTheDocument();
    expect(schemaCard().getAllByText("PK")).toHaveLength(2);
    expect(schemaCard().getByText("FK")).toBeInTheDocument();
  });
});

describe("saving a schema", () => {
  it("saves it first when a schema and a question are given together, then asks", async () => {
    const { user } = setup();
    await user.type(screen.getByLabelText("Describe or paste your schema"), "customers(id, name)");
    await ask(user, "how many customers");

    await waitFor(() => expect(api.generateSql).toHaveBeenCalled());
    expect(api.analyzeSchema).toHaveBeenCalledWith("customers(id, name)", "postgres");
    expect(vi.mocked(api.analyzeSchema).mock.invocationCallOrder[0]).toBeLessThan(
      vi.mocked(api.generateSql).mock.invocationCallOrder[0],
    );
    expect(api.generateSql).toHaveBeenCalledWith(
      "how many customers",
      CUSTOMERS_AND_ORDERS_DDL,
      "postgres",
      expect.any(AbortSignal),
    );
    expect(loadSchema()).not.toBeNull();
  });

  it("only saves when no question was asked, and does not generate", async () => {
    const { user } = setup();
    await user.type(screen.getByLabelText("Describe or paste your schema"), "customers(id, name)");

    await user.click(questionCard().getByRole("button", { name: /save schema/i }));

    expect(await schemaCard().findByText(/Schema saved: 2 tables, 5 columns/)).toBeInTheDocument();
    expect(api.generateSql).not.toHaveBeenCalled();
    expect(loadSchema()?.tables).toHaveLength(2);
  });

  it("notes when a plain-English schema was interpreted", async () => {
    vi.mocked(api.analyzeSchema).mockResolvedValue({ ...analyzed, data: { ...analyzed.data, source: "text" } });
    const { user } = setup();
    await user.type(screen.getByLabelText("Describe or paste your schema"), "a shop with customers");
    await user.click(questionCard().getByRole("button", { name: /save schema/i }));

    expect(await schemaCard().findByText(/Read from your description/)).toBeInTheDocument();
  });

  it("does not ask the question, and keeps the draft, when the schema can't be read", async () => {
    vi.mocked(api.analyzeSchema).mockResolvedValue({ ok: false, message: "Couldn't read that schema: nope" });
    const { user } = setup();
    await user.type(screen.getByLabelText("Describe or paste your schema"), "gibberish");
    await ask(user, "a question");

    expect(await screen.findByRole("alert")).toHaveTextContent("Couldn't read that schema: nope");
    expect(api.generateSql).not.toHaveBeenCalled();
    expect(screen.getByLabelText("Describe or paste your schema")).toHaveValue("gibberish");
    expect(loadSchema()).toBeNull();
  });

  it("warns when the browser won't store the schema", async () => {
    vi.spyOn(Storage.prototype, "setItem").mockImplementation(() => {
      throw new Error("blocked");
    });
    const { user } = setup();
    await user.type(screen.getByLabelText("Describe or paste your schema"), "customers(id)");
    await user.click(questionCard().getByRole("button", { name: /save schema/i }));

    expect(await schemaCard().findByText(/forgotten when you refresh/)).toBeInTheDocument();
  });
});

describe("changing a saved schema", () => {
  beforeEach(() => {
    storeSchema(makeSchema());
  });

  async function openEditor(user: ReturnType<typeof userEvent.setup>, change: string) {
    await user.click(schemaCard().getByRole("button", { name: /add \/ edit/i }));
    await user.type(schemaCard().getByLabelText("Describe what to add or change"), change);
    await user.click(schemaCard().getByRole("button", { name: "Apply change" }));
  }

  it("applies a change, reports exactly what changed, and saves the new schema", async () => {
    const updatedTables = CUSTOMERS_AND_ORDERS.map((t) =>
      t.name === "customers" ? { ...t, columns: [...t.columns, { name: "phone", type: "TEXT" }] } : t,
    );
    vi.mocked(api.updateSchema).mockResolvedValue({
      ok: true,
      data: {
        dialect: "postgres",
        source: "text",
        ddl: "CREATE TABLE customers (id INT PRIMARY KEY, name TEXT, phone TEXT);",
        tables: updatedTables,
        changes: ["Added column customers.phone (TEXT)"],
      },
    });
    const { user } = setup();

    await openEditor(user, "customers have a phone number");

    expect(api.updateSchema).toHaveBeenCalledWith(CUSTOMERS_AND_ORDERS_DDL, "customers have a phone number", "postgres");
    const banner = await schemaCard().findByRole("status");
    expect(banner).toHaveTextContent("Schema updated.");
    expect(banner).toHaveTextContent("Added column customers.phone (TEXT)");
    expect(schemaCard().getByText("phone")).toBeInTheDocument();
    expect(loadSchema()?.ddl).toContain("phone TEXT");
  });

  it("reports a failure and leaves the saved schema exactly as it was", async () => {
    vi.mocked(api.updateSchema).mockResolvedValue({
      ok: false,
      message: "Schema not changed: that doesn't change anything",
    });
    const { user } = setup();

    await openEditor(user, "qwerty zzz");

    expect(await schemaCard().findByRole("alert")).toHaveTextContent("Schema not changed");
    expect(loadSchema()).toEqual(makeSchema());
    expect(schemaCard().getByLabelText("Describe what to add or change")).toHaveValue("qwerty zzz");
  });

  it("resets the schema only after confirmation, and clears it from storage", async () => {
    const { user } = setup();
    await user.click(schemaCard().getByRole("button", { name: "Reset" }));
    expect(loadSchema()).not.toBeNull();

    await user.click(schemaCard().getByRole("button", { name: "Yes, reset" }));

    expect(loadSchema()).toBeNull();
    expect(await schemaCard().findByText(/Schema reset/)).toBeInTheDocument();
    expect(screen.getByLabelText("Describe or paste your schema")).toBeInTheDocument();
    expect(screen.getByLabelText("SQL dialect")).toBeEnabled();
  });
});

describe("stopping and racing requests", () => {
  it("Stop cancels the request, and a late reply from it is ignored", async () => {
    const slow = deferred<GenerateOutcome>();
    vi.mocked(api.generateSql).mockReturnValue(slow.promise);
    const { user } = setup();

    await ask(user, "slow question");
    // Stop appears twice by design: beside Generate, and in the result card.
    await user.click((await screen.findAllByRole("button", { name: "Stop" }))[0]);

    expect(screen.getByText("Your query will appear here")).toBeInTheDocument();
    await act(async () => slow.resolve(generated({ sql: "SELECT 'stale'" })));

    expect(screen.getByText("Your query will appear here")).toBeInTheDocument();
    expect(screen.queryByLabelText("SQL")).not.toBeInTheDocument();
    expect(loadHistory()).toEqual([]);
  });

  it("aborts the in-flight request when Stop is pressed", async () => {
    let signal: AbortSignal | undefined;
    vi.mocked(api.generateSql).mockImplementation((_q, _s, _d, s) => {
      signal = s;
      return new Promise<GenerateOutcome>(() => {});
    });
    const { user } = setup();

    await ask(user, "q");
    await waitFor(() => expect(signal).toBeDefined());
    expect(signal?.aborted).toBe(false);
    await user.click(screen.getAllByRole("button", { name: "Stop" })[0]);
    expect(signal?.aborted).toBe(true);
  });

  it("does not start a second request while one is running", async () => {
    vi.mocked(api.generateSql).mockReturnValue(deferred<GenerateOutcome>().promise);
    const { user } = setup();

    await ask(user, "q");
    await user.click(questionBox());
    await user.keyboard("{Control>}{Enter}{/Control}");

    expect(api.generateSql).toHaveBeenCalledTimes(1);
  });
});

describe("failures and clarifications", () => {
  it("shows an error and retries the same question", async () => {
    vi.mocked(api.generateSql)
      .mockResolvedValueOnce({ kind: "error", message: "Couldn't reach the API" })
      .mockResolvedValueOnce(generated({ sql: "SELECT 2" }));
    const { user } = setup();

    await ask(user, "q");
    const alert = await screen.findByRole("alert");
    expect(alert).toHaveTextContent("Couldn't reach the API");

    await user.click(within(alert).getByRole("button", { name: /try again/i }));

    expect(await screen.findByLabelText("SQL")).toHaveTextContent("SELECT 2");
    expect(api.generateSql).toHaveBeenCalledTimes(2);
  });

  it("shows what a guardrail blocked and keeps it out of the history", async () => {
    vi.mocked(api.generateSql).mockResolvedValue(
      generated({ guardrail_blocked: true, block_reason: "Blocked keyword 'DELETE'", sql: "DELETE FROM t" }),
    );
    const { user } = setup();
    await ask(user, "delete everything");

    expect(await screen.findByText("Blocked by guardrails")).toBeInTheDocument();
    expect(loadHistory()).toEqual([]);
  });

  it("shows an unanswerable question's reason", async () => {
    vi.mocked(api.generateSql).mockResolvedValue({
      kind: "clarification",
      data: { kind: "unanswerable", message: "Not in your schema.", interpretations: ["no shoe size"] },
    });
    const { user } = setup();
    await ask(user, "shoe size?");
    expect(await screen.findByText("no shoe size")).toBeInTheDocument();
  });
});

describe("history", () => {
  it("records each answer and shows it", async () => {
    vi.mocked(api.generateSql).mockResolvedValue(generated({ question: "how many customers" }));
    const { user } = setup();
    await ask(user, "how many customers");

    const history = await screen.findByRole("region", { name: "Recent questions" });
    expect(within(history).getByText("how many customers")).toBeInTheDocument();
    expect(loadHistory()).toHaveLength(1);
  });

  it("is still there after a reload", async () => {
    const saved: HistoryEntry = {
      id: "a",
      question: "an old question",
      sql: "SELECT 1",
      dialect: "postgres",
      confidence: 0.9,
      schemaProvided: true,
      createdAt: Date.now() - 3600_000,
    };
    storeHistory([saved]);
    setup();
    const history = screen.getByRole("region", { name: "Recent questions" });
    expect(within(history).getByText("an old question")).toBeInTheDocument();
    expect(within(history).getByText("1 h ago")).toBeInTheDocument();
  });

  it("can be cleared", async () => {
    storeHistory([
      { id: "a", question: "q", sql: "SELECT 1", dialect: "postgres", confidence: 1, schemaProvided: true, createdAt: 1 },
    ]);
    const { user } = setup();
    await user.click(within(screen.getByRole("region", { name: "Recent questions" })).getByRole("button", { name: "Clear" }));
    expect(screen.queryByRole("region", { name: "Recent questions" })).not.toBeInTheDocument();
    expect(loadHistory()).toEqual([]);
  });

  it("can ask a past question again", async () => {
    storeHistory([
      { id: "a", question: "an old question", sql: "SELECT 1", dialect: "postgres", confidence: 1, schemaProvided: true, createdAt: 1 },
    ]);
    const { user } = setup();
    const history = within(screen.getByRole("region", { name: "Recent questions" }));
    await user.click(history.getByText("an old question"));
    await user.click(history.getByRole("button", { name: /ask again/i }));
    expect(questionBox()).toHaveValue("an old question");
  });
});

describe("server status and theme", () => {
  it("says so when the server can't be reached, and recovers on Retry", async () => {
    vi.mocked(api.checkHealth).mockResolvedValueOnce(false).mockResolvedValueOnce(true);
    const { user } = setup();

    expect(await screen.findByText("Can't reach the server")).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Retry" }));

    expect(await screen.findByText("Your schema stays in this browser")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Retry" })).not.toBeInTheDocument();
  });

  it("switches theme and remembers it", async () => {
    const { user } = setup();
    await user.click(screen.getByRole("button", { name: "Switch to dark theme" }));
    expect(document.documentElement.classList.contains("dark")).toBe(true);
    expect(localStorage.getItem("text-to-sql:theme")).toBe("dark");
    expect(screen.getByRole("button", { name: "Switch to light theme" })).toBeInTheDocument();
  });
});

describe("guided tour", () => {
  const guideButton = () => screen.getByRole("button", { name: "Start the guided tour" });

  it("opens from the Guide button, walks the steps and closes", async () => {
    const { user } = setup();
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();

    await user.click(guideButton());
    expect(screen.getByRole("dialog")).toHaveAccessibleName("Add your schema");

    await user.click(screen.getByRole("button", { name: /next/i }));
    expect(screen.getByRole("dialog")).toHaveAccessibleName("Ask in plain English");

    await user.keyboard("{Escape}");
    await waitFor(() => expect(screen.queryByRole("dialog")).not.toBeInTheDocument());
    expect(guideButton()).toHaveFocus();
  });

  it("shows a new-hint dot until the guide has been opened once", async () => {
    const { user } = setup();
    expect(guideButton().querySelector(".animate-soft-pulse")).not.toBeNull();

    await user.click(guideButton());
    expect(guideButton().querySelector(".animate-soft-pulse")).toBeNull();
    expect(localStorage.getItem("text-to-sql:guide-seen")).toBe("1");
  });

  it("has no hint for a returning visitor", () => {
    localStorage.setItem("text-to-sql:guide-seen", "1");
    setup();
    expect(guideButton().querySelector(".animate-soft-pulse")).toBeNull();
  });

  it("every step points at an element that exists on the page", () => {
    setup();
    for (const step of GUIDE_STEPS) {
      if (step.target) expect(document.querySelector(`[data-guide="${step.target}"]`), step.target).not.toBeNull();
    }
  });
});

describe("resilience", () => {
  it("starts cleanly with corrupted saved data", () => {
    localStorage.setItem("text-to-sql:schema:v1", "{not json");
    localStorage.setItem("text-to-sql:history:v1", "[[[");
    setup();
    expect(screen.getByLabelText("Describe or paste your schema")).toBeInTheDocument();
    expect(screen.queryByRole("region", { name: "Recent questions" })).not.toBeInTheDocument();
  });

  it("announces results for screen readers", async () => {
    const { user } = setup();
    await ask(user, "q");
    await waitFor(() => expect(screen.getAllByRole("status").some((el) => /SQL generated/.test(el.textContent ?? ""))).toBe(true));
  });

  it("has a skip link to the main content", () => {
    setup();
    expect(screen.getByRole("link", { name: "Skip to content" })).toHaveAttribute("href", "#main");
  });
});
