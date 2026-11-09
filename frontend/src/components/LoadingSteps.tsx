import { cn } from "../lib/cn";
import Icon from "./ui/Icon";
import Spinner from "./ui/Spinner";

// When each step is shown as "in progress". The three stages mirror what the API
// really does, but the timings are an estimate: the API replies once, not per step.
const STEP_STARTS_MS = [0, 2200, 4800];
const SLOW_AFTER_MS = 8000;

interface Props {
  steps: string[];
  elapsedMs: number;
}

export default function LoadingSteps({ steps, elapsedMs }: Props) {
  const active = STEP_STARTS_MS.reduce((index, start, i) => (elapsedMs >= start ? i : index), 0);

  return (
    <div role="status" aria-live="polite">
      <ol className="space-y-2.5">
        {steps.map((step, i) => {
          const done = i < active;
          const current = i === active;
          return (
            <li
              key={step}
              className={cn(
                "flex items-center gap-2.5 text-sm transition-colors duration-300",
                done ? "text-muted-foreground" : current ? "font-medium text-foreground" : "text-muted-foreground/60",
              )}
            >
              <span className="grid size-5 place-items-center">
                {done ? (
                  <span className="grid size-5 animate-pop-check place-items-center rounded-full bg-accent text-primary">
                    <Icon name="check" className="size-3" />
                  </span>
                ) : current ? (
                  <Spinner className="text-primary" />
                ) : (
                  <span className="size-2 rounded-full bg-border" />
                )}
              </span>
              {step}
            </li>
          );
        })}
      </ol>

      {elapsedMs > SLOW_AFTER_MS && (
        <p className="mt-4 flex animate-fade-in items-start gap-2 rounded-md bg-warning/10 p-2.5 text-xs text-warning-foreground">
          <Icon name="clock" className="mt-px size-3.5" />
          Still working. The free server may be waking up from sleep, which can take up to a minute the first time.
        </p>
      )}
    </div>
  );
}
