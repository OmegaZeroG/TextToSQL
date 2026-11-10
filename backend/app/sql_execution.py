"""Runs generated SQL against a throwaway database built from the user's schema.

Parsing proves a query is well formed; running it proves it can run. The user's
real data is never involved (this service has none). Instead the schema is turned
into an in-memory SQLite database filled with small deterministic data chosen to
exercise the edges that break SQL: dates that cross year boundaries, repeated
dates, NULLs, zeros, parents with no children.

SQLite is the engine for every dialect, so for MySQL/PostgreSQL/etc. the query is
first transpiled by sqlglot. That means only failures that are the query's fault
are reported (a column that doesn't exist, a bad aggregate), never things SQLite
merely lacks (a function it doesn't implement). For SQLite itself every error counts.
"""
import re
import sqlite3
import time
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta

import sqlglot

from app.schema_parser import Column, ParsedSchema, Table
from app.sql_checks import Issue

ROWS_PER_TABLE = 12
TIME_LIMIT_SECONDS = 2.0
MAX_RESULT_ROWS = 500
MAX_VALUE_BYTES = 1_000_000
_FIRST_DATE = date(2024, 11, 10)  # 34-day steps cross a year end and cover Dec and Jan

# Errors that are the query's own fault even after translation to SQLite. Missing
# tables/columns are deliberately not here: translation can leave behind unit names
# like MONTH that SQLite reads as columns, and real missing columns are already
# caught against the schema.
_STRUCTURAL = re.compile(
    r"ambiguous column name|misuse of (aggregate|window)|aggregate functions are not allowed",
    re.IGNORECASE,
)


@dataclass
class ExecutionResult:
    ran: bool
    issues: list[Issue] = field(default_factory=list)
    columns: list[str] = field(default_factory=list)
    rows: list[tuple] = field(default_factory=list)
    note: str | None = None  # why it wasn't run, when it wasn't


def _quote(name: str) -> str:
    return '"' + name.replace('"', '""') + '"'


def _affinity(sql_type: str) -> str:
    t = (sql_type or "").upper()
    if "BOOL" in t or "INT" in t or "SERIAL" in t:
        return "INTEGER"
    if any(k in t for k in ("DEC", "NUM", "FLOAT", "DOUBLE", "REAL", "MONEY")):
        return "REAL"
    return "TEXT"


def _is_date(sql_type: str) -> bool:
    t = (sql_type or "").upper()
    return "DATE" in t or "TIME" in t


def _is_timestamp(sql_type: str) -> bool:
    t = (sql_type or "").upper()
    return "TIMESTAMP" in t or "DATETIME" in t


def _parent(column: Column) -> tuple[str, str | None] | None:
    if not column.foreign_key:
        return None
    table, _, col = column.foreign_key.lower().partition(".")
    return table, (col or None)


def _table_order(schema: ParsedSchema) -> list[Table]:
    """Parents before children, so foreign keys can point at real rows."""
    by_name = {t.name.lower(): t for t in schema.tables}
    ordered: list[Table] = []
    state: dict[str, int] = {}

    def visit(table: Table) -> None:
        key = table.name.lower()
        if state.get(key):
            return
        state[key] = 1
        for column in table.columns:
            parent = _parent(column)
            if parent and parent[0] in by_name and parent[0] != key:
                visit(by_name[parent[0]])
        ordered.append(table)

    for table in schema.tables:
        visit(table)
    return ordered


_CYCLES = {
    "status": ["active", "pending", "cancelled", "completed"],
    "city": ["Austin", "Seattle", "Boston"],
    "country": ["US", "CA", "GB"],
    "type": ["standard", "premium"],
    "category": ["alpha", "beta", "gamma"],
}


def _cell(column: Column, table: str, index: int, parents: dict[str, dict[str, list]]) -> object:
    name = column.name.lower()
    parent = _parent(column)
    last_row = index == ROWS_PER_TABLE - 1

    if parent is not None:
        values = parents.get(parent[0], {}).get(parent[1] or "", None)
        if values is None:  # parent column unknown: fall back to its first column
            columns = parents.get(parent[0], {})
            values = next(iter(columns.values()), None)
        if values:
            # Pile children onto the first half of the parents so some parents have none.
            return values[index % max(1, (len(values) + 1) // 2)]
        return index + 1

    sql_type = column.type or ""
    affinity = _affinity(sql_type)

    if column.primary_key:
        return index + 1 if affinity != "TEXT" else f"{name}_{index + 1}"
    if last_row:
        return None  # every non-key column gets a NULL somewhere

    if _is_date(sql_type):
        day = _FIRST_DATE + timedelta(days=34 * index - (7 if index % 4 == 3 else 0))  # a few repeats per month
        if _is_timestamp(sql_type):
            return datetime.combine(day, datetime.min.time()).replace(hour=9 + index % 8).strftime("%Y-%m-%d %H:%M:%S")
        return day.isoformat()
    if affinity == "INTEGER":
        return index % 2 if "BOOL" in sql_type.upper() else (index * 7) % 50
    if affinity == "REAL":
        return 0.0 if index == 0 else round(10 + index * 12.5, 2)  # a zero for division checks
    for key, cycle in _CYCLES.items():
        if key in name:
            return cycle[index % len(cycle)]
    if "email" in name:
        return f"user{index + 1}@example.com"
    return f"{name}_{index + 1}"


def build_test_database(schema: ParsedSchema) -> sqlite3.Connection:
    """In-memory database with the schema's tables and deterministic data. Read-only on return."""
    conn = sqlite3.connect(":memory:")
    # The SQL being tried was written by a model from a user's prompt. It is already limited
    # to a single SELECT; this stops one from asking for a gigabyte blob (randomblob(1e9)).
    conn.setlimit(sqlite3.SQLITE_LIMIT_LENGTH, MAX_VALUE_BYTES)
    parents: dict[str, dict[str, list]] = {}

    for table in _table_order(schema):
        columns = ", ".join(f"{_quote(c.name)} {_affinity(c.type)}" for c in table.columns)
        conn.execute(f"CREATE TABLE {_quote(table.name)} ({columns})")
        rows = [
            tuple(_cell(c, table.name, i, parents) for c in table.columns) for i in range(ROWS_PER_TABLE)
        ]
        placeholders = ", ".join("?" for _ in table.columns)
        conn.executemany(f"INSERT OR IGNORE INTO {_quote(table.name)} VALUES ({placeholders})", rows)
        parents[table.name.lower()] = {
            c.name.lower(): [r[pos] for r in rows if r[pos] is not None] for pos, c in enumerate(table.columns)
        }
    conn.commit()
    conn.execute("PRAGMA query_only = ON")
    return conn


_DATE_TEXT = re.compile(r"^(\d{4})-(\d{1,2})(?:-(\d{1,2}))?(?:[ T].*)?$")
_MONTH_COLUMN = re.compile(r"^(month|mon|month_of_year|month_number|month_num_of_year)$", re.IGNORECASE)


def check_result_values(columns: list[str], rows: list[tuple]) -> list[Issue]:
    """Sanity-check what a query returned: a date that can't exist, or a month number outside 1-12."""
    issues: list[Issue] = []
    seen: set[str] = set()

    for row in rows:
        for name, value in zip(columns, row):
            if isinstance(value, str):
                match = _DATE_TEXT.match(value)
                if match and (not 1 <= int(match.group(2)) <= 12) and value not in seen:
                    seen.add(value)
                    issues.append(
                        Issue(
                            "invalid_date_output",
                            f"The query returned '{value}' in column `{name}`, which isn't a real date. "
                            "Derive dates from the original date column with native date functions "
                            "instead of rebuilding them from numbers.",
                        )
                    )
            elif isinstance(value, int) and _MONTH_COLUMN.match(name) and not 1 <= value <= 12 and name not in seen:
                seen.add(name)
                issues.append(
                    Issue(
                        "invalid_month_output",
                        f"Column `{name}` returned {value}, which isn't a month number (1-12).",
                    )
                )
    return issues


def run_on_connection(conn: sqlite3.Connection, sql: str, dialect: str) -> ExecutionResult:
    """Transpile (if needed), run with a time limit, and check the result."""
    to_run = sql
    if dialect != "sqlite":
        try:
            to_run = sqlglot.transpile(sql, read=dialect, write="sqlite")[0]
        except Exception as exc:
            return ExecutionResult(False, note=f"couldn't be translated for the test run: {exc}")

    deadline = time.monotonic() + TIME_LIMIT_SECONDS
    conn.set_progress_handler(lambda: 1 if time.monotonic() > deadline else 0, 20_000)
    try:
        cursor = conn.execute(to_run)
        columns = [d[0] for d in cursor.description or []]
        rows = cursor.fetchmany(MAX_RESULT_ROWS)
    except sqlite3.Error as exc:
        message = str(exc)
        if "interrupted" in message.lower():
            return ExecutionResult(False, note="the test run took too long and was stopped")
        if dialect == "sqlite" or _STRUCTURAL.search(message):
            return ExecutionResult(True, [Issue("execution_error", f"The query failed when run against test data: {message}.")])
        return ExecutionResult(False, note=f"couldn't be run on the test engine ({message})")
    finally:
        conn.set_progress_handler(None, 0)

    return ExecutionResult(True, check_result_values(columns, rows), columns, rows)


def verify_by_execution(sql: str, schema: ParsedSchema | None, dialect: str) -> ExecutionResult:
    if schema is None or not schema.tables:
        return ExecutionResult(False, note="no schema to build test data from")
    try:
        conn = build_test_database(schema)
    except Exception as exc:  # an exotic schema must never break generation
        return ExecutionResult(False, note=f"test data couldn't be built: {exc}")
    try:
        return run_on_connection(conn, sql, dialect)
    finally:
        conn.close()
