export type TokenKind = "keyword" | "string" | "number" | "comment" | "function" | "plain";

export interface Token {
  kind: TokenKind;
  text: string;
}

const KEYWORDS = new Set(
  (
    "select from where group by order having limit offset join inner left right full outer cross natural " +
    "on using as and or not in is null like ilike between exists distinct union all intersect except case " +
    "when then else end asc desc with top fetch first next rows row only over partition insert into values " +
    "update set delete create table alter drop true false interval cast filter window range unbounded " +
    "preceding following current lateral nulls"
  ).split(" "),
);

// One alternative per token type, tried in order at each position.
const PATTERN = new RegExp(
  [
    "(--[^\\n]*)", // 1: line comment
    "(/\\*[\\s\\S]*?(?:\\*/|$))", // 2: block comment (an unterminated one runs to the end)
    "('(?:[^']|'')*'?)", // 3: string, '' is an escaped quote
    '("(?:[^"]|"")*"?|`[^`]*`?|\\[[^\\]]*\\]?)', // 4: quoted identifier
    "(\\d+(?:\\.\\d+)?)", // 5: number
    "([A-Za-z_][A-Za-z0-9_$]*)", // 6: word
  ].join("|"),
  "g",
);

/**
 * Splits SQL into coloured tokens. Pure text in, plain tokens out: the UI renders
 * them as React text nodes, so nothing here is ever interpreted as HTML.
 */
export function tokenizeSql(sql: string): Token[] {
  const tokens: Token[] = [];
  let cursor = 0;

  const push = (kind: TokenKind, text: string) => {
    if (!text) return;
    const last = tokens[tokens.length - 1];
    if (last && last.kind === kind && kind === "plain") last.text += text;
    else tokens.push({ kind, text });
  };

  PATTERN.lastIndex = 0;
  for (let match = PATTERN.exec(sql); match; match = PATTERN.exec(sql)) {
    if (match[0] === "") {
      PATTERN.lastIndex += 1; // never loop on an empty match
      continue;
    }
    push("plain", sql.slice(cursor, match.index));
    const [text, lineComment, blockComment, string, quotedIdent, number, word] = match;
    cursor = match.index + text.length;

    if (lineComment || blockComment) push("comment", text);
    else if (string) push("string", text);
    else if (quotedIdent) push("plain", text);
    else if (number) push("number", text);
    else if (word) {
      if (KEYWORDS.has(word.toLowerCase())) push("keyword", text);
      else if (/^\s*\(/.test(sql.slice(cursor))) push("function", text);
      else push("plain", text);
    }
  }
  push("plain", sql.slice(cursor));
  return tokens;
}
