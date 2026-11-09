import { cn } from "../../lib/cn";

/** A shimmering placeholder block. Decorative, so hidden from assistive tech. */
export default function Skeleton({ className }: { className?: string }) {
  return <div aria-hidden="true" className={cn("skeleton rounded-md", className)} />;
}
