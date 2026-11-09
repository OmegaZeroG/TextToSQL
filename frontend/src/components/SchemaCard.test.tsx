import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import { makeSchema } from "../test/factories";
import type { SavedSchema, Status } from "../types";
import SchemaCard from "./SchemaCard";

interface Overrides {
  schema?: SavedSchema | null;
  draft?: string;
  busy?: boolean;
  status?: Status | null;
  onApplyChange?: (text: string) => Promise<boolean>;
}

function setup(overrides: Overrides = {}) {
  const props = {
    schema: null as SavedSchema | null,
    dialectLabel: "PostgreSQL",
    draft: "",
    onDraftChange: vi.fn(),
    busy: false,
    status: null as Status | null,
    onSave: vi.fn(),
    onApplyChange: vi.fn().mockResolvedValue(true) as (text: string) => Promise<boolean>,
    onReset: vi.fn(),
    onDismissStatus: vi.fn(),
    onFileError: vi.fn(),
    ...overrides,
  };
  const view = render(<SchemaCard {...props} />);
  return { props, user: userEvent.setup(), ...view };
}

const fileInput = (container: HTMLElement) => container.querySelector('input[type="file"]') as HTMLInputElement;

describe("SchemaCard, no schema yet", () => {
  it("offers the optional schema box", () => {
    setup();
    expect(screen.getByLabelText("Describe or paste your schema")).toBeInTheDocument();
    expect(screen.getAllByText("Your schema (optional)").length).toBeGreaterThan(0);
  });

  it("cannot save an empty draft", () => {
    setup({ draft: "   " });
    expect(screen.getByRole("button", { name: "Save schema" })).toBeDisabled();
  });

  it("saves a non-empty draft", async () => {
    const { props, user } = setup({ draft: "customers(id, name)" });
    await user.click(screen.getByRole("button", { name: "Save schema" }));
    expect(props.onSave).toHaveBeenCalledTimes(1);
  });

  it("reports typing to the parent", async () => {
    const { props, user } = setup();
    await user.type(screen.getByLabelText("Describe or paste your schema"), "a");
    expect(props.onDraftChange).toHaveBeenCalledWith("a");
  });

  it("shows a skeleton instead of the form while the schema is being read", () => {
    setup({ busy: true });
    expect(screen.getByText("Reading your schema…")).toBeInTheDocument();
    expect(screen.queryByLabelText("Describe or paste your schema")).not.toBeInTheDocument();
  });

  it("shows a status message and lets the user dismiss it", async () => {
    const { props, user } = setup({ status: { kind: "error", message: "Couldn't read that schema: nope" } });
    expect(screen.getByRole("alert")).toHaveTextContent("Couldn't read that schema: nope");
    await user.click(screen.getByRole("button", { name: "Dismiss message" }));
    expect(props.onDismissStatus).toHaveBeenCalled();
  });
});

describe("SchemaCard, file upload", () => {
  it("loads a small .sql file into the draft", async () => {
    const { props, user, container } = setup();
    const file = new File(["CREATE TABLE t (id INT);"], "schema.sql", { type: "text/plain" });
    await user.upload(fileInput(container), file);
    await waitFor(() => expect(props.onDraftChange).toHaveBeenCalledWith("CREATE TABLE t (id INT);"));
  });

  it("rejects a file that is too large", async () => {
    const { props, user, container } = setup();
    const file = new File(["x"], "big.sql");
    Object.defineProperty(file, "size", { value: 300_000 });
    await user.upload(fileInput(container), file);
    await waitFor(() => expect(props.onFileError).toHaveBeenCalledWith(expect.stringMatching(/too large/i)));
    expect(props.onDraftChange).not.toHaveBeenCalled();
  });

  it("rejects text over the character limit", async () => {
    const { props, user, container } = setup();
    await user.upload(fileInput(container), new File(["x".repeat(20_001)], "long.sql"));
    await waitFor(() => expect(props.onFileError).toHaveBeenCalledWith(expect.stringMatching(/limit/i)));
  });

  it("rejects a file that is not text", async () => {
    const { props, user, container } = setup();
    await user.upload(fileInput(container), new File(["abc\u0000def"], "image.sql"));
    await waitFor(() => expect(props.onFileError).toHaveBeenCalledWith(expect.stringMatching(/text file/i)));
  });
});

describe("SchemaCard, saved schema", () => {
  it("summarises the tables and columns", () => {
    setup({ schema: makeSchema() });
    expect(screen.getAllByText("Your schema").length).toBeGreaterThan(0);
    expect(screen.getAllByText("2 tables, 5 columns").length).toBeGreaterThan(0);
    expect(screen.getAllByText("PostgreSQL").length).toBeGreaterThan(0);
  });

  it("lists each table with its columns and types", () => {
    setup({ schema: makeSchema() });
    const tables = within(screen.getByRole("list", { name: "Tables" }));
    expect(tables.getByText("customers")).toBeInTheDocument();
    expect(tables.getByText("orders")).toBeInTheDocument();
    expect(tables.getByText("2 fields")).toBeInTheDocument();
    expect(tables.getByText("3 fields")).toBeInTheDocument();
    expect(tables.getByText("DECIMAL(10, 2)")).toBeInTheDocument();
  });

  it("badges primary and foreign keys, and says what a foreign key points at", () => {
    setup({ schema: makeSchema() });
    expect(screen.getAllByText("PK")).toHaveLength(2);
    const fk = screen.getByText("FK");
    expect(fk).toHaveAttribute("title", "References customers.id");
  });

  it("copes with a schema saved before keys were reported", () => {
    const old = makeSchema({
      tables: [{ name: "legacy", columns: [{ name: "a", type: "INT" }] }],
    });
    setup({ schema: old });
    const tables = within(screen.getByRole("list", { name: "Tables" }));
    expect(tables.getByText("legacy")).toBeInTheDocument();
    expect(tables.queryByText("PK")).not.toBeInTheDocument();
  });

  it("can show the schema as SQL", async () => {
    const { user } = setup({ schema: makeSchema() });
    await user.click(screen.getByRole("button", { name: /view schema as sql/i }));
    expect(screen.getByLabelText("Schema as SQL")).toHaveTextContent("CREATE TABLE customers");
    expect(screen.getByRole("button", { name: "Download schema as a .sql file" })).toBeInTheDocument();
  });

  describe("reset", () => {
    it("asks for confirmation before doing anything", async () => {
      const { props, user } = setup({ schema: makeSchema() });
      await user.click(screen.getByRole("button", { name: "Reset" }));
      expect(screen.getByRole("alertdialog")).toHaveTextContent("Reset your schema?");
      expect(props.onReset).not.toHaveBeenCalled();
    });

    it("keeps the schema when the user changes their mind", async () => {
      const { props, user } = setup({ schema: makeSchema() });
      await user.click(screen.getByRole("button", { name: "Reset" }));
      await user.click(screen.getByRole("button", { name: "Keep it" }));
      expect(screen.queryByRole("alertdialog")).not.toBeInTheDocument();
      expect(props.onReset).not.toHaveBeenCalled();
      expect(screen.getByRole("button", { name: "Reset" })).toBeInTheDocument();
    });

    it("resets once confirmed", async () => {
      const { props, user } = setup({ schema: makeSchema() });
      await user.click(screen.getByRole("button", { name: "Reset" }));
      await user.click(screen.getByRole("button", { name: "Yes, reset" }));
      expect(props.onReset).toHaveBeenCalledTimes(1);
    });
  });

  describe("add / edit", () => {
    it("opens an editor with the textarea focused", async () => {
      const { user } = setup({ schema: makeSchema() });
      await user.click(screen.getByRole("button", { name: /add \/ edit/i }));
      expect(screen.getByLabelText("Describe what to add or change")).toHaveFocus();
    });

    it("cannot apply an empty change", async () => {
      const { user } = setup({ schema: makeSchema() });
      await user.click(screen.getByRole("button", { name: /add \/ edit/i }));
      expect(screen.getByRole("button", { name: "Apply change" })).toBeDisabled();
    });

    it("sends the trimmed change, then closes the editor on success", async () => {
      const { props, user } = setup({ schema: makeSchema() });
      await user.click(screen.getByRole("button", { name: /add \/ edit/i }));
      await user.type(screen.getByLabelText("Describe what to add or change"), "  add a phone column  ");
      await user.click(screen.getByRole("button", { name: "Apply change" }));

      expect(props.onApplyChange).toHaveBeenCalledWith("add a phone column");
      await waitFor(() => expect(screen.getByRole("button", { name: /add \/ edit/i })).toBeInTheDocument());
      expect(screen.getByLabelText("Describe what to add or change")).toHaveValue("");
    });

    it("keeps the editor and the text open when the change fails", async () => {
      const onApplyChange = vi.fn().mockResolvedValue(false);
      const { user } = setup({ schema: makeSchema(), onApplyChange });
      await user.click(screen.getByRole("button", { name: /add \/ edit/i }));
      await user.type(screen.getByLabelText("Describe what to add or change"), "gibberish");
      await user.click(screen.getByRole("button", { name: "Apply change" }));

      await waitFor(() => expect(onApplyChange).toHaveBeenCalled());
      expect(screen.getByLabelText("Describe what to add or change")).toHaveValue("gibberish");
      expect(screen.getByRole("button", { name: "Apply change" })).toBeInTheDocument();
    });

    it("clears any lingering failure message when the user cancels", async () => {
      const { props, user } = setup({ schema: makeSchema(), status: { kind: "error", message: "Schema not changed" } });
      await user.click(screen.getByRole("button", { name: /add \/ edit/i }));
      await user.click(screen.getByRole("button", { name: "Cancel" }));
      expect(props.onDismissStatus).toHaveBeenCalled();
    });

    it("shows progress on the apply button while working", async () => {
      const { user } = setup({ schema: makeSchema(), busy: true });
      await user.click(screen.getByRole("button", { name: /add \/ edit/i }));
      const apply = screen.getByRole("button", { name: "Apply change" });
      expect(apply).toBeDisabled();
      expect(apply).toHaveAttribute("aria-busy", "true");
    });
  });

  it("shows details with a success message", () => {
    setup({
      schema: makeSchema(),
      status: { kind: "success", message: "Schema updated.", details: ["Added column customers.phone (TEXT)"] },
    });
    const banner = screen.getByRole("status");
    expect(within(banner).getByText("Added column customers.phone (TEXT)")).toBeInTheDocument();
  });
});
