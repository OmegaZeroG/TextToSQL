"""Static safety check for a generated SQL statement.

This app never executes the SQL it generates, so this is not what stands between
a user and their data. It exists because a text-to-SQL tool should never hand
out a destructive statement as its answer: someone will paste it into a console
without reading it. Anything that is not a single read-only SELECT is refused.
"""
from dataclasses import dataclass

import sqlparse
from sqlparse.tokens import DDL, DML

BLOCKED_DML_KEYWORDS = {"INSERT", "UPDATE", "DELETE", "MERGE", "REPLACE"}
BLOCKED_DDL_KEYWORDS = {"CREATE", "ALTER", "DROP", "TRUNCATE", "ATTACH", "COPY", "EXPORT", "IMPORT", "INSTALL", "LOAD"}
BLOCKED_KEYWORDS = BLOCKED_DML_KEYWORDS | BLOCKED_DDL_KEYWORDS


@dataclass
class GuardrailResult:
    allowed: bool
    reason: str | None = None
    sql: str | None = None  # the statement without its trailing semicolon


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

    return GuardrailResult(allowed=True, sql=stripped)
