"""Static safety checks a generated SQL statement must pass before execution.

Layered defense: even if a check here has a gap, DuckDB is opened
read_only=True (see db.py), so a write statement fails at the engine level
regardless of what slips past this layer.
"""
import re
from dataclasses import dataclass

import sqlparse
from sqlparse.sql import Parenthesis
from sqlparse.tokens import DDL, DML

from app.config import MAX_ROW_LIMIT, MAX_SUBQUERY_DEPTH

BLOCKED_DML_KEYWORDS = {"INSERT", "UPDATE", "DELETE", "MERGE", "REPLACE"}
BLOCKED_DDL_KEYWORDS = {"CREATE", "ALTER", "DROP", "TRUNCATE", "ATTACH", "COPY", "EXPORT", "IMPORT", "INSTALL", "LOAD"}
BLOCKED_KEYWORDS = BLOCKED_DML_KEYWORDS | BLOCKED_DDL_KEYWORDS


@dataclass
class GuardrailResult:
    allowed: bool
    reason: str | None = None
    sql: str | None = None  # possibly rewritten (e.g. LIMIT injected)


def _max_parenthesis_depth(tokens, depth=0) -> int:
    deepest = depth
    for token in tokens:
        if isinstance(token, Parenthesis):
            deepest = max(deepest, _max_parenthesis_depth(token.tokens, depth + 1))
        elif token.is_group:
            deepest = max(deepest, _max_parenthesis_depth(token.tokens, depth))
    return deepest


def check_sql(sql: str) -> GuardrailResult:
    if not sql or not sql.strip():
        return GuardrailResult(allowed=False, reason="Empty SQL statement.")

    statements = sqlparse.parse(sql)
    if len(statements) != 1:
        return GuardrailResult(allowed=False, reason="Only a single SQL statement is allowed per request.")

    statement = statements[0]

    for token in statement.flatten():
        if token.ttype in (DDL, DML):
            keyword = token.value.upper()
            if keyword in BLOCKED_KEYWORDS:
                return GuardrailResult(
                    allowed=False,
                    reason=f"Blocked keyword '{keyword}': only read-only SELECT queries are permitted.",
                )

    stripped = statement.value.strip().rstrip(";")
    first_word = stripped.split(None, 1)[0].upper() if stripped else ""
    if first_word not in ("SELECT", "WITH"):
        return GuardrailResult(allowed=False, reason=f"Only SELECT/WITH queries are permitted, got '{first_word}'.")

    depth = _max_parenthesis_depth(statement.tokens)
    if depth > MAX_SUBQUERY_DEPTH:
        return GuardrailResult(
            allowed=False,
            reason=f"Query nesting depth {depth} exceeds the maximum allowed ({MAX_SUBQUERY_DEPTH}).",
        )

    if not re.search(r"\blimit\s+\d+", stripped, re.IGNORECASE):
        stripped = f"{stripped} LIMIT {MAX_ROW_LIMIT}"
    else:
        def cap_limit(match):
            n = int(match.group(1))
            return f"LIMIT {min(n, MAX_ROW_LIMIT)}"
        stripped = re.sub(r"\blimit\s+(\d+)", cap_limit, stripped, flags=re.IGNORECASE)

    return GuardrailResult(allowed=True, sql=stripped)
