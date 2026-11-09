import type { ReactNode } from "react";

import { cn } from "../../lib/cn";

type Tone = "neutral" | "primary" | "muted";

const tones: Record<Tone, string> = {
  neutral: "bg-muted text-muted-foreground",
  primary: "bg-accent text-accent-foreground",
  muted: "bg-secondary text-secondary-foreground",
};

export default function Badge({
  tone = "neutral",
  className,
  title,
  children,
}: {
  tone?: Tone;
  className?: string;
  title?: string;
  children: ReactNode;
}) {
  return (
    <span
      title={title}
      className={cn("inline-flex items-center rounded px-1.5 py-0.5 font-mono text-[11px] leading-none", tones[tone], className)}
    >
      {children}
    </span>
  );
}
