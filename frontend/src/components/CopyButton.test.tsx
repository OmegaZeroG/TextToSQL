import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import CopyButton from "./CopyButton";

describe("CopyButton", () => {
  it("copies the text and confirms it", async () => {
    const user = userEvent.setup(); // installs a working clipboard
    render(<CopyButton text="SELECT 1" label="Copy SQL" />);

    await user.click(screen.getByRole("button", { name: "Copy SQL" }));

    expect(await navigator.clipboard.readText()).toBe("SELECT 1");
    expect(screen.getByRole("button", { name: "Copied" })).toBeInTheDocument();
  });

  it("goes back to its label after a moment", async () => {
    const user = userEvent.setup();
    render(<CopyButton text="x" />);
    await user.click(screen.getByRole("button", { name: "Copy" }));
    expect(screen.getByRole("button", { name: "Copied" })).toBeInTheDocument();
    await waitFor(() => expect(screen.getByRole("button", { name: "Copy" })).toBeInTheDocument(), { timeout: 3000 });
  });

  it("says so when the browser blocks clipboard access", async () => {
    const user = userEvent.setup();
    vi.spyOn(navigator.clipboard, "writeText").mockRejectedValue(new Error("denied"));
    render(<CopyButton text="x" />);
    await user.click(screen.getByRole("button", { name: "Copy" }));
    expect(screen.getByRole("button", { name: "Copy failed" })).toBeInTheDocument();
  });
});
