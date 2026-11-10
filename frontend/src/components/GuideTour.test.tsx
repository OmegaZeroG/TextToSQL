import { act, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import { GUIDE_STEPS } from "../lib/guideSteps";
import GuideTour from "./GuideTour";

function setup(open = true) {
  const onClose = vi.fn();
  const user = userEvent.setup();
  const view = render(<GuideTour open={open} onClose={onClose} />);
  return { user, onClose, ...view };
}

const dialog = () => screen.getByRole("dialog");

describe("GuideTour", () => {
  it("renders nothing while closed", () => {
    setup(false);
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
  });

  it("opens on the first step as a labelled modal dialog", () => {
    setup();
    expect(dialog()).toHaveAttribute("aria-modal", "true");
    expect(dialog()).toHaveAccessibleName(GUIDE_STEPS[0].title);
    expect(dialog()).toHaveAccessibleDescription(GUIDE_STEPS[0].body);
    expect(screen.getByText(`Step 1 of ${GUIDE_STEPS.length}`)).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /back/i })).not.toBeInTheDocument();
  });

  it("moves forward and back through every step", async () => {
    const { user } = setup();
    for (let i = 1; i < GUIDE_STEPS.length; i++) {
      await user.click(screen.getByRole("button", { name: /next/i }));
      expect(dialog()).toHaveAccessibleName(GUIDE_STEPS[i].title);
      expect(screen.getByText(`Step ${i + 1} of ${GUIDE_STEPS.length}`)).toBeInTheDocument();
    }
    await user.click(screen.getByRole("button", { name: /back/i }));
    expect(dialog()).toHaveAccessibleName(GUIDE_STEPS[GUIDE_STEPS.length - 2].title);
  });

  it("finishes with Done on the last step", async () => {
    const { user, onClose } = setup();
    for (let i = 1; i < GUIDE_STEPS.length; i++) await user.click(screen.getByRole("button", { name: /next/i }));

    expect(screen.queryByRole("button", { name: /next/i })).not.toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Done" }));
    expect(onClose).toHaveBeenCalledTimes(1);
  });

  it("closes from the X button and on Escape", async () => {
    const { user, onClose } = setup();
    await user.click(screen.getByRole("button", { name: "Close guide" }));
    await user.keyboard("{Escape}");
    expect(onClose).toHaveBeenCalledTimes(2);
  });

  it("can be driven with the arrow keys", async () => {
    const { user } = setup();
    await user.keyboard("{ArrowRight}");
    expect(dialog()).toHaveAccessibleName(GUIDE_STEPS[1].title);
    await user.keyboard("{ArrowLeft}");
    expect(dialog()).toHaveAccessibleName(GUIDE_STEPS[0].title);
    await user.keyboard("{ArrowLeft}"); // already on the first step
    expect(dialog()).toHaveAccessibleName(GUIDE_STEPS[0].title);
  });

  it("puts focus on the primary button, keeps Tab inside, and gives focus back", async () => {
    const trigger = document.createElement("button");
    document.body.append(trigger);
    trigger.focus();

    const onClose = vi.fn();
    const user = userEvent.setup();
    const { rerender } = render(<GuideTour open onClose={onClose} />);
    const next = screen.getByRole("button", { name: /next/i });
    expect(next).toHaveFocus();

    // Next -> (wraps) close -> next: focus never leaves the dialog.
    await user.tab();
    expect(screen.getByRole("button", { name: "Close guide" })).toHaveFocus();
    await user.tab({ shift: true });
    expect(next).toHaveFocus();

    vi.useFakeTimers();
    rerender(<GuideTour open={false} onClose={onClose} />);
    expect(trigger).toHaveFocus();
    trigger.remove();
  });

  it("fades out before it unmounts", () => {
    vi.useFakeTimers();
    const onClose = vi.fn();
    const { rerender } = render(<GuideTour open onClose={onClose} />);

    rerender(<GuideTour open={false} onClose={onClose} />);
    expect(screen.getByRole("dialog")).toBeInTheDocument(); // still fading

    act(() => {
      vi.advanceTimersByTime(250);
    });
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
  });

  it("starts from the first step each time it is reopened", async () => {
    const onClose = vi.fn();
    const user = userEvent.setup();
    const { rerender } = render(<GuideTour open onClose={onClose} />);
    await user.click(screen.getByRole("button", { name: /next/i }));

    vi.useFakeTimers();
    rerender(<GuideTour open={false} onClose={onClose} />);
    act(() => {
      vi.advanceTimersByTime(250);
    });
    rerender(<GuideTour open onClose={onClose} />);
    expect(dialog()).toHaveAccessibleName(GUIDE_STEPS[0].title);
  });

  it("falls back to a centred card when a step's target is not on the page", () => {
    render(
      <GuideTour open onClose={() => {}} steps={[{ target: "does-not-exist", title: "Orphan", body: "No target here." }]} />,
    );
    expect(dialog()).toHaveAccessibleName("Orphan");
    expect(screen.getByRole("button", { name: "Done" })).toBeInTheDocument();
  });
});
