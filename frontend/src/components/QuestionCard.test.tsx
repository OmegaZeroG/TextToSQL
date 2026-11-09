import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import { FALLBACK_DIALECTS } from "../api";
import QuestionCard from "./QuestionCard";

function setup(overrides: Partial<React.ComponentProps<typeof QuestionCard>> = {}) {
  const props: React.ComponentProps<typeof QuestionCard> = {
    question: "",
    onQuestionChange: vi.fn(),
    onSubmit: vi.fn(),
    onCancel: vi.fn(),
    generating: false,
    busy: false,
    canSubmit: true,
    hasSchema: false,
    hasSchemaDraft: false,
    dialects: FALLBACK_DIALECTS,
    dialectId: "postgres",
    dialectLocked: false,
    onDialectChange: vi.fn(),
    suggestions: ["Show customers", "Count orders", "Top 5 by total"],
    ...overrides,
  };
  render(<QuestionCard {...props} />);
  return { props, user: userEvent.setup() };
}

const box = () => screen.getByLabelText("Your question");

describe("QuestionCard", () => {
  it("uses the first suggestion as the placeholder", () => {
    setup();
    expect(box()).toHaveAttribute("placeholder", "e.g. Show customers");
  });

  it("limits the question length and shows a counter", () => {
    setup({ question: "hello" });
    expect(box()).toHaveAttribute("maxLength", "1000");
    expect(screen.getByText("5/1000")).toBeInTheDocument();
  });

  it("reports typing", async () => {
    const { props, user } = setup();
    await user.type(box(), "x");
    expect(props.onQuestionChange).toHaveBeenCalledWith("x");
  });

  describe("examples", () => {
    it("fills the question when a chip is chosen", async () => {
      const { props, user } = setup();
      await user.click(screen.getByRole("button", { name: "Count orders" }));
      expect(props.onQuestionChange).toHaveBeenCalledWith("Count orders");
    });

    it("marks the chip that matches the question as pressed", () => {
      setup({ question: "Count orders" });
      expect(screen.getByRole("button", { name: "Count orders" })).toHaveAttribute("aria-pressed", "true");
      expect(screen.getByRole("button", { name: "Show customers" })).toHaveAttribute("aria-pressed", "false");
    });
  });

  describe("submitting", () => {
    it("submits with the button", async () => {
      const { props, user } = setup({ question: "q" });
      await user.click(screen.getByRole("button", { name: /generate sql/i }));
      expect(props.onSubmit).toHaveBeenCalledTimes(1);
    });

    it("submits with Ctrl+Enter", async () => {
      const { props, user } = setup({ question: "q" });
      await user.click(box());
      await user.keyboard("{Control>}{Enter}{/Control}");
      expect(props.onSubmit).toHaveBeenCalledTimes(1);
    });

    it("submits with Cmd+Enter", async () => {
      const { props, user } = setup({ question: "q" });
      await user.click(box());
      await user.keyboard("{Meta>}{Enter}{/Meta}");
      expect(props.onSubmit).toHaveBeenCalledTimes(1);
    });

    it("does not submit on a plain Enter (it adds a new line)", async () => {
      const { props, user } = setup({ question: "q" });
      await user.click(box());
      await user.keyboard("{Enter}");
      expect(props.onSubmit).not.toHaveBeenCalled();
    });

    it("cannot submit when there is nothing to submit", async () => {
      const { props, user } = setup({ canSubmit: false });
      expect(screen.getByRole("button", { name: /generate sql/i })).toBeDisabled();
      await user.click(box());
      await user.keyboard("{Control>}{Enter}{/Control}");
      expect(props.onSubmit).not.toHaveBeenCalled();
    });

    it("ignores Ctrl+Enter while a request is already running", async () => {
      const { props, user } = setup({ question: "q", generating: true });
      await user.click(box());
      await user.keyboard("{Control>}{Enter}{/Control}");
      expect(props.onSubmit).not.toHaveBeenCalled();
    });
  });

  describe("button label", () => {
    it("says Save schema when only a schema was entered", () => {
      setup({ hasSchemaDraft: true, question: "" });
      expect(screen.getByRole("button", { name: /save schema/i })).toBeInTheDocument();
    });

    it("says Generate SQL once there is a question, even with a schema draft", () => {
      setup({ hasSchemaDraft: true, question: "q" });
      expect(screen.getByRole("button", { name: /generate sql/i })).toBeInTheDocument();
    });
  });

  describe("while generating", () => {
    it("shows progress and a Stop button", async () => {
      const { props, user } = setup({ question: "q", generating: true });
      const working = screen.getByRole("button", { name: /generating/i });
      expect(working).toBeDisabled();
      expect(working).toHaveAttribute("aria-busy", "true");
      await user.click(screen.getByRole("button", { name: /stop/i }));
      expect(props.onCancel).toHaveBeenCalledTimes(1);
    });

    it("has no Stop button when idle", () => {
      setup({ question: "q" });
      expect(screen.queryByRole("button", { name: /stop/i })).not.toBeInTheDocument();
    });
  });

  describe("dialect", () => {
    it("lists every dialect and reports a change", async () => {
      const { props, user } = setup();
      const select = screen.getByLabelText("SQL dialect");
      expect(select.querySelectorAll("option")).toHaveLength(FALLBACK_DIALECTS.length);
      await user.selectOptions(select, "tsql");
      expect(props.onDialectChange).toHaveBeenCalledWith("tsql");
    });

    it("is locked to the saved schema's dialect", () => {
      setup({ dialectLocked: true, hasSchema: true });
      expect(screen.getByLabelText("SQL dialect")).toBeDisabled();
    });
  });

  it("explains what happens without a schema", () => {
    setup();
    expect(screen.getByText(/I'll assume sensible tables/)).toBeInTheDocument();
  });

  it("says answers are checked once a schema is saved", () => {
    setup({ hasSchema: true });
    expect(screen.getByText(/checked against your saved schema/)).toBeInTheDocument();
  });
});
