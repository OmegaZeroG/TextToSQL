import { useEffect, useId, useRef, useState } from "react";
import type { DragEvent } from "react";

import { cn } from "../lib/cn";
import { downloadText } from "../lib/download";
import { plural } from "../lib/format";
import { MAX_SCHEMA_CHARS } from "../lib/limits";
import type { SavedSchema, SchemaTable, Status } from "../types";
import CopyButton from "./CopyButton";
import SqlBlock from "./SqlBlock";
import StatusBanner from "./StatusBanner";
import Badge from "./ui/Badge";
import Button from "./ui/Button";
import Collapsible from "./ui/Collapsible";
import Icon from "./ui/Icon";
import Skeleton from "./ui/Skeleton";
import Spinner from "./ui/Spinner";

interface Props {
  schema: SavedSchema | null;
  dialectLabel: string;
  draft: string;
  onDraftChange: (value: string) => void;
  busy: boolean;
  status: Status | null;
  onSave: () => void;
  onApplyChange: (text: string) => Promise<boolean>;
  onReset: () => void;
  onDismissStatus: () => void;
  onFileError: (message: string) => void;
  className?: string;
}

const DRAFT_PLACEHOLDER = `Describe your tables in plain English, paste CREATE TABLE statements, or list them like this:

customers(id, name, email)
orders(id, customer_id, total, created_at)`;

const CHANGE_PLACEHOLDER = `e.g. customers should also have a phone number
or: CREATE TABLE invoices (id INT, amount DECIMAL(10,2))
or: ALTER TABLE orders ADD COLUMN status VARCHAR(20)`;

const MAX_FILE_BYTES = 200_000;

const fieldClass =
  "w-full resize-y rounded-md border border-input bg-background p-3.5 font-mono text-base leading-relaxed transition-shadow " +
  "placeholder:text-muted-foreground/70 focus:border-ring focus:outline-none focus:ring-2 focus:ring-ring/30 sm:text-[13px]";

function TableCard({ table, index }: { table: SchemaTable; index: number }) {
  return (
    <li
      className="animate-rise-in overflow-hidden rounded-md border border-border bg-background/60"
      style={{ animationDelay: `${Math.min(index, 8) * 60}ms` }}
    >
      <div className="flex items-center justify-between gap-2 border-b border-border/70 px-3 py-2">
        <span className="flex min-w-0 items-center gap-2 font-mono text-[13px] font-medium">
          <Icon name="table" className="size-3.5 text-primary" />
          <span className="truncate">{table.name}</span>
        </span>
        <span className="shrink-0 text-[11px] text-muted-foreground">{plural(table.columns.length, "field")}</span>
      </div>
      <ul className="divide-y divide-border/50">
        {table.columns.map((column) => (
          <li key={column.name} className="flex items-center justify-between gap-3 px-3 py-1.5 text-xs">
            <span className="flex min-w-0 items-center gap-1.5">
              <span className="truncate font-mono">{column.name}</span>
              {column.primary_key && <Badge tone="primary" title="Primary key">PK</Badge>}
              {column.foreign_key && (
                <Badge tone="muted" title={`References ${column.foreign_key}`}>
                  FK
                </Badge>
              )}
            </span>
            <span className="shrink-0 font-mono text-[11px] text-muted-foreground">{column.type || "-"}</span>
          </li>
        ))}
      </ul>
    </li>
  );
}

function SchemaSkeleton() {
  return (
    <div className="space-y-3" role="status" aria-busy="true">
      <p className="flex items-center gap-2 text-xs text-muted-foreground">
        <Spinner className="text-primary" />
        Reading your schema…
      </p>
      {[0, 1].map((i) => (
        <div key={i} className="space-y-2.5 rounded-md border border-border p-3" aria-hidden="true">
          <Skeleton className="h-3.5 w-1/3" />
          <Skeleton className="h-3 w-full" />
          <Skeleton className="h-3 w-5/6" />
          <Skeleton className="h-3 w-2/3" />
        </div>
      ))}
    </div>
  );
}

export default function SchemaCard({
  schema,
  dialectLabel,
  draft,
  onDraftChange,
  busy,
  status,
  onSave,
  onApplyChange,
  onReset,
  onDismissStatus,
  onFileError,
  className,
}: Props) {
  const [open, setOpen] = useState(false); // phones only: the card collapses to one row
  const [editing, setEditing] = useState(false);
  const [changeText, setChangeText] = useState("");
  const [confirmingReset, setConfirmingReset] = useState(false);
  const [showDdl, setShowDdl] = useState(false);
  const [dragging, setDragging] = useState(false);
  const fileInput = useRef<HTMLInputElement>(null);
  const changeField = useRef<HTMLTextAreaElement>(null);
  const bodyId = useId();

  // On a phone the card may be collapsed: open it so progress and results are seen.
  useEffect(() => {
    if (status || busy) setOpen(true);
  }, [status, busy]);

  useEffect(() => {
    if (editing) changeField.current?.focus({ preventScroll: true });
  }, [editing]);

  const columnCount = schema?.tables.reduce((sum, t) => sum + t.columns.length, 0) ?? 0;
  const summary = schema
    ? `${plural(schema.tables.length, "table")}, ${plural(columnCount, "column")}`
    : "Add yours for answers checked against your tables";
  const title = schema ? "Your schema" : "Your schema (optional)";

  async function readFile(file: File) {
    if (file.size > MAX_FILE_BYTES) {
      onFileError(`That file is too large. Schemas can be up to ${MAX_SCHEMA_CHARS.toLocaleString()} characters.`);
      return;
    }
    const text = await file.text();
    if (text.includes("\u0000")) {
      onFileError("That doesn't look like a text file.");
      return;
    }
    if (text.length > MAX_SCHEMA_CHARS) {
      onFileError(
        `That file has ${text.length.toLocaleString()} characters; the limit is ${MAX_SCHEMA_CHARS.toLocaleString()}.`,
      );
      return;
    }
    onDraftChange(text);
  }

  function handleDrop(event: DragEvent<HTMLDivElement>) {
    event.preventDefault();
    setDragging(false);
    const file = event.dataTransfer.files?.[0];
    if (file) void readFile(file);
  }

  async function applyChange() {
    const text = changeText.trim();
    if (!text) return;
    if (await onApplyChange(text)) {
      setEditing(false);
      setChangeText("");
    }
  }

  function cancelEditing() {
    setEditing(false);
    onDismissStatus();
  }

  function confirmReset() {
    setConfirmingReset(false);
    setEditing(false);
    setShowDdl(false);
    onReset();
  }

  const headerContent = (
    <>
      <Icon name="table" className="size-[18px] text-primary" />
      <span className="min-w-0 flex-1">
        <span className="block text-sm font-semibold">{title}</span>
        <span className="block truncate text-xs text-muted-foreground lg:whitespace-normal">{summary}</span>
      </span>
      {schema && <Badge>{dialectLabel}</Badge>}
    </>
  );

  return (
    <aside
      aria-label="Schema"
      className={cn("overflow-hidden rounded-lg border border-border bg-card shadow-card", className)}
    >
      {/* Phones: a tappable summary row that expands the card. */}
      <button
        type="button"
        onClick={() => setOpen((value) => !value)}
        aria-expanded={open}
        aria-controls={bodyId}
        className="flex min-h-[3.5rem] w-full items-center gap-3 px-4 py-3 text-left transition-colors hover:bg-muted/50 lg:hidden"
      >
        {headerContent}
        <Icon name="chevronDown" className={cn("transition-transform duration-300", open && "rotate-180")} />
      </button>
      {/* Desktop: the same header, always open and not interactive. */}
      <div className="hidden items-center gap-3 px-5 py-3.5 lg:flex">{headerContent}</div>

      <Collapsible open={open} openOnDesktop className="border-t border-border">
        <div id={bodyId} className="space-y-4 p-4 sm:p-5">
          {status && <StatusBanner status={status} onDismiss={onDismissStatus} />}

          {!schema && busy && <SchemaSkeleton />}

          {!schema && !busy && (
            <div className="space-y-3">
              <div
                className={cn("relative rounded-md transition-shadow", dragging && "ring-2 ring-ring/50")}
                onDragOver={(event) => {
                  event.preventDefault();
                  setDragging(true);
                }}
                onDragLeave={() => setDragging(false)}
                onDrop={handleDrop}
              >
                <label htmlFor={`${bodyId}-draft`} className="sr-only">
                  Describe or paste your schema
                </label>
                <textarea
                  id={`${bodyId}-draft`}
                  value={draft}
                  onChange={(event) => onDraftChange(event.target.value)}
                  maxLength={MAX_SCHEMA_CHARS}
                  rows={8}
                  placeholder={DRAFT_PLACEHOLDER}
                  className={cn(fieldClass, "min-h-[10rem]")}
                />
              </div>
              <div className="flex flex-wrap items-center justify-between gap-2">
                <Button size="sm" onClick={() => fileInput.current?.click()}>
                  <Icon name="upload" />
                  Upload .sql
                </Button>
                <input
                  ref={fileInput}
                  type="file"
                  hidden
                  accept=".sql,.ddl,.txt,text/plain"
                  onChange={(event) => {
                    const file = event.target.files?.[0];
                    event.target.value = "";
                    if (file) void readFile(file);
                  }}
                />
                <Button variant="primary" onClick={onSave} disabled={!draft.trim()}>
                  Save schema
                </Button>
              </div>
              <p className="text-xs text-muted-foreground">
                English, SQL, or a plain list all work. You can also drop a file onto the box.
              </p>
            </div>
          )}

          {schema && (
            <>
              <ul aria-label="Tables" className="scrollbar-thin max-h-[55vh] space-y-3 overflow-y-auto pr-0.5">
                {schema.tables.map((table, index) => (
                  <TableCard key={table.name} table={table} index={index} />
                ))}
              </ul>

              <div className="rounded-md border border-border">
                <button
                  type="button"
                  onClick={() => setShowDdl((value) => !value)}
                  aria-expanded={showDdl}
                  className="flex min-h-11 w-full items-center gap-2 px-3 py-2 text-left text-xs text-muted-foreground transition-colors hover:text-foreground"
                >
                  <Icon name="fileCode" />
                  View schema as SQL
                  <Icon name="chevronDown" className={cn("ml-auto transition-transform duration-300", showDdl && "rotate-180")} />
                </button>
                <Collapsible open={showDdl}>
                  <div className="border-t border-border">
                    <div className="flex justify-end gap-2 p-2">
                      <CopyButton text={schema.ddl} />
                      <Button size="sm" onClick={() => downloadText("schema.sql", `${schema.ddl}\n`)} aria-label="Download schema as a .sql file">
                        <Icon name="download" />
                        .sql
                      </Button>
                    </div>
                    <SqlBlock sql={schema.ddl} label="Schema as SQL" className="max-h-64 rounded-b-md" />
                  </div>
                </Collapsible>
              </div>

              <Collapsible open={editing}>
                <div className="space-y-2 rounded-md border border-border bg-muted/40 p-3">
                  <label htmlFor={`${bodyId}-change`} className="text-xs font-medium">
                    Describe what to add or change
                  </label>
                  <textarea
                    id={`${bodyId}-change`}
                    ref={changeField}
                    value={changeText}
                    onChange={(event) => setChangeText(event.target.value)}
                    maxLength={MAX_SCHEMA_CHARS}
                    rows={4}
                    placeholder={CHANGE_PLACEHOLDER}
                    className={fieldClass}
                  />
                  <div className="flex gap-2">
                    <Button variant="primary" size="sm" loading={busy} disabled={!changeText.trim()} onClick={applyChange}>
                      Apply change
                    </Button>
                    <Button size="sm" onClick={cancelEditing} disabled={busy}>
                      Cancel
                    </Button>
                  </div>
                  <p className="text-xs text-muted-foreground">If it can't be applied, your schema stays exactly as it is.</p>
                </div>
              </Collapsible>

              {!editing && !confirmingReset && (
                <div className="flex flex-wrap gap-2">
                  <Button size="sm" onClick={() => setEditing(true)}>
                    <Icon name="plus" />
                    Add / edit
                  </Button>
                  <Button variant="ghost" size="sm" onClick={() => setConfirmingReset(true)}>
                    <Icon name="reset" />
                    Reset
                  </Button>
                </div>
              )}

              {confirmingReset && (
                <div role="alertdialog" aria-label="Reset schema" className="animate-scale-in space-y-2.5 rounded-md border border-destructive/30 bg-destructive/10 p-3">
                  <p className="text-sm">Reset your schema? It's removed from this browser and can't be recovered.</p>
                  <div className="flex gap-2">
                    <Button variant="danger" size="sm" onClick={confirmReset}>
                      Yes, reset
                    </Button>
                    <Button size="sm" onClick={() => setConfirmingReset(false)}>
                      Keep it
                    </Button>
                  </div>
                </div>
              )}
            </>
          )}
        </div>
      </Collapsible>
    </aside>
  );
}
