import type { ReactNode } from "react";

import { cn } from "../../lib/cn";

interface Props {
  open: boolean;
  /** Keep it expanded at the desktop breakpoint regardless of `open`. */
  openOnDesktop?: boolean;
  className?: string;
  children: ReactNode;
}

/**
 * Animated expand/collapse without measuring heights: a grid row transitions
 * between 0fr and 1fr. Collapsed content is also made `invisible` (after the
 * animation) so it can't be tabbed into or read by a screen reader.
 */
export default function Collapsible({ open, openOnDesktop = false, className, children }: Props) {
  return (
    <div
      className={cn(
        "grid [transition-property:grid-template-rows,visibility] [transition-duration:300ms,0s] ease-out",
        open ? "visible grid-rows-[1fr]" : "invisible grid-rows-[0fr] [transition-delay:0s,300ms]",
        openOnDesktop && "lg:visible lg:grid-rows-[1fr]",
        className,
      )}
    >
      <div className="min-h-0 overflow-hidden">{children}</div>
    </div>
  );
}
