import { useState } from "react";

import { cn } from "../lib/cn";
import { percent, timeAgo } from "../lib/format";
import type { Dialect, HistoryEntry } from "../types";
import CopyButton from "./CopyButton";
import SqlBlock from "./SqlBlock";
import Badge from "./ui/Badge";
import Button from "./ui/Button";
import Collapsible from "./ui/Collapsible";
import Icon from "./ui/Icon";

interface Props {
  items: HistoryEntry[];
  dialects: Dialect[];
  onUse: (entry: HistoryEntry) => void;
  onClear: () => void;
}

export default function HistoryList({ items, dialects, onUse, onClear }: Props) {
  const [openId, setOpenId] = useState<string | null>(null);

  if (items.length === 0) return null;

  return (
    <section aria-label="Recent questions" className="animate-fade-in">
      <div className="mb-2.5 flex items-center justify-between">
        <h2 className="flex items-center gap-2 text-xs font-semibold uppercase tracking-wider text-muted-foreground">
          <Icon name="history" />
          Recent
        </h2>
        <Button variant="ghost" size="sm" onClick={onClear}>
          Clear
        </Button>
      </div>

      <ul className="space-y-2">
        {items.map((item) => {
          const open = openId === item.id;
          const dialectLabel = dialects.find((d) => d.id === item.dialect)?.label ?? item.dialect;
          return (
            <li key={item.id} className="overflow-hidden rounded-lg border border-border bg-card">
              <button
                type="button"
                onClick={() => setOpenId(open ? null : item.id)}
                aria-expanded={open}
                className="flex w-full items-start gap-3 px-4 py-3 text-left transition-colors hover:bg-muted/50"
              >
                <span className="min-w-0 flex-1">
                  <span className="line-clamp-2 text-sm">{item.question}</span>
                  <span className="mt-1.5 flex flex-wrap items-center gap-1.5 text-[11px] text-muted-foreground">
                    <span>{timeAgo(item.createdAt)}</span>
                    <Badge>{dialectLabel}</Badge>
                    <Badge tone={item.confidence >= 0.75 ? "primary" : "neutral"}>{percent(item.confidence)}</Badge>
                    {!item.schemaProvided && <Badge tone="muted">assumed schema</Badge>}
                  </span>
                </span>
                <Icon name="chevronDown" className={cn("mt-1 transition-transform duration-300", open && "rotate-180")} />
              </button>
              <Collapsible open={open}>
                <div className="border-t border-border">
                  <SqlBlock sql={item.sql} label="Saved SQL" />
                  <div className="flex flex-wrap gap-2 p-3">
                    <CopyButton text={item.sql} label="Copy SQL" />
                    <Button size="sm" onClick={() => onUse(item)}>
                      <Icon name="refresh" />
                      Ask again
                    </Button>
                  </div>
                </div>
              </Collapsible>
            </li>
          );
        })}
      </ul>
    </section>
  );
}
