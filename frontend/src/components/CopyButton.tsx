import { useEffect, useRef, useState } from "react";

import Button from "./ui/Button";
import Icon from "./ui/Icon";

type State = "idle" | "copied" | "failed";

export default function CopyButton({ text, label = "Copy" }: { text: string; label?: string }) {
  const [state, setState] = useState<State>("idle");
  const timer = useRef<number | undefined>(undefined);

  useEffect(() => () => window.clearTimeout(timer.current), []);

  async function copy() {
    let next: State = "copied";
    try {
      await navigator.clipboard.writeText(text);
    } catch {
      next = "failed";
    }
    setState(next);
    window.clearTimeout(timer.current);
    timer.current = window.setTimeout(() => setState("idle"), 1600);
  }

  const caption = state === "copied" ? "Copied" : state === "failed" ? "Copy failed" : label;

  return (
    <Button size="sm" onClick={copy} aria-live="polite">
      <Icon
        name={state === "copied" ? "check" : "copy"}
        className={state === "copied" ? "animate-pop-check text-primary" : undefined}
      />
      {caption}
    </Button>
  );
}
