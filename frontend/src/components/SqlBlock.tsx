import { useMemo } from "react";

import { cn } from "../lib/cn";
import { tokenizeSql } from "../lib/sqlHighlight";
import type { TokenKind } from "../lib/sqlHighlight";

const TOKEN_CLASS: Record<TokenKind, string> = {
  keyword: "font-medium text-syntax-keyword",
  string: "text-syntax-string",
  number: "text-syntax-number",
  comment: "italic text-syntax-comment",
  function: "text-syntax-function",
  plain: "",
};

export default function SqlBlock({ sql, label = "SQL", className }: { sql: string; label?: string; className?: string }) {
  const tokens = useMemo(() => tokenizeSql(sql), [sql]);

  return (
    // Focusable so keyboard users can scroll a long line.
    <pre
      tabIndex={0}
      aria-label={label}
      className={cn(
        "scrollbar-thin overflow-x-auto whitespace-pre bg-muted/60 p-4 font-mono text-[13px] leading-6",
        className,
      )}
    >
      <code>
        {tokens.map((token, i) => (
          <span key={i} className={TOKEN_CLASS[token.kind]}>
            {token.text}
          </span>
        ))}
      </code>
    </pre>
  );
}
