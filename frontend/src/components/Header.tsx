import type { Theme } from "../hooks/useTheme";
import { cn } from "../lib/cn";
import type { ServerState } from "../types";
import Button from "./ui/Button";
import Icon from "./ui/Icon";

interface Props {
  server: ServerState;
  onRetry: () => void;
  theme: Theme;
  onToggleTheme: () => void;
}

const STATUS: Record<ServerState, { label: string; dot: string; showOnPhone: boolean }> = {
  online: { label: "Your schema stays in this browser", dot: "bg-primary", showOnPhone: false },
  checking: { label: "Connecting…", dot: "bg-muted-foreground animate-soft-pulse", showOnPhone: false },
  waking: { label: "Waking the server…", dot: "bg-warning animate-soft-pulse", showOnPhone: true },
  offline: { label: "Can't reach the server", dot: "bg-destructive", showOnPhone: true },
};

export default function Header({ server, onRetry, theme, onToggleTheme }: Props) {
  const status = STATUS[server];
  const dark = theme === "dark";

  return (
    <header className="sticky top-0 z-30 border-b border-border bg-card/85 pt-[env(safe-area-inset-top)] backdrop-blur supports-[backdrop-filter]:bg-card/70">
      <div className="mx-auto flex h-14 max-w-6xl items-center justify-between gap-3 px-4 sm:px-6">
        <div className="flex items-center gap-2.5">
          <span className="grid size-8 place-items-center rounded-lg bg-primary text-primary-foreground">
            <Icon name="database" className="size-[18px]" />
          </span>
          <span className="text-[15px] font-semibold tracking-tight">plainquery</span>
        </div>

        <div className="flex min-w-0 items-center gap-1.5">
          <p
            role="status"
            className="flex min-w-0 items-center gap-2 text-xs text-muted-foreground"
            aria-label={status.label}
          >
            <span className={cn("size-2 shrink-0 rounded-full", status.dot)} />
            <span className={cn("truncate", !status.showOnPhone && "hidden sm:inline")}>{status.label}</span>
          </p>
          {server === "offline" && (
            <Button variant="ghost" size="sm" onClick={onRetry}>
              <Icon name="refresh" />
              Retry
            </Button>
          )}
          <Button
            variant="ghost"
            size="icon"
            onClick={onToggleTheme}
            aria-label={dark ? "Switch to light theme" : "Switch to dark theme"}
          >
            <Icon key={theme} name={dark ? "sun" : "moon"} className="size-[18px] animate-scale-in" />
          </Button>
        </div>
      </div>
    </header>
  );
}
