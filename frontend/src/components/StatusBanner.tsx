import { cn } from "../lib/cn";
import type { Status } from "../types";
import Icon from "./ui/Icon";

interface Props {
  status: Status;
  onDismiss: () => void;
}

export default function StatusBanner({ status, onDismiss }: Props) {
  const isError = status.kind === "error";

  return (
    <div
      role={isError ? "alert" : "status"}
      className={cn(
        "flex animate-scale-in items-start gap-2.5 rounded-lg border p-3 text-sm",
        isError ? "border-destructive/30 bg-destructive/10" : "border-primary/25 bg-accent text-accent-foreground",
      )}
    >
      <Icon name={isError ? "alert" : "check"} className={cn("mt-0.5", isError && "text-destructive")} />
      <div className="min-w-0 flex-1">
        <p className="font-medium">
          <span className="sr-only">{isError ? "Failed: " : "Success: "}</span>
          {status.message}
        </p>
        {status.details && status.details.length > 0 && (
          <ul className="mt-1.5 list-inside list-disc space-y-0.5 text-xs opacity-90">
            {status.details.map((detail) => (
              <li key={detail}>{detail}</li>
            ))}
          </ul>
        )}
      </div>
      <button
        type="button"
        onClick={onDismiss}
        aria-label="Dismiss message"
        className="-m-1.5 grid size-9 shrink-0 place-items-center rounded-md opacity-60 transition hover:bg-foreground/5 hover:opacity-100"
      >
        <Icon name="x" />
      </button>
    </div>
  );
}
