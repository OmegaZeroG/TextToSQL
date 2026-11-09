"""Checks generated SQL against the user's schema without a database.

This is the hallucination check for the bring-your-own-schema mode: a query
that invents a table or column, or uses syntax from the wrong dialect, is
caught statically.
"""
import re
from dataclasses import dataclass, field

import sqlglot
from sqlglot import exp
from sqlglot.errors import OptimizeError, ParseError
from sqlglot.optimizer.qualify import qualify

from app.schema_parser import DIALECTS, ParsedSchema


LIMIT_UNSUPPORTED = {
    "tsql": "TOP or OFFSET ... FETCH",
    "oracle": "FETCH FIRST n ROWS ONLY",
}


def _strip_string_literals(sql: str) -> str:
    return re.sub(r"'(?:[^']|'')*'", "''", sql)


@dataclass
class SqlCheck:
    syntax_valid: bool
    schema_ok: bool
    problems: list[str] = field(default_factory=list)
    tables_used: list[str] = field(default_factory=list)


def check_sql_against_schema(sql: str, schema: ParsedSchema | None, dialect: str) -> SqlCheck:
    """With schema=None only the syntax and dialect are checked."""
    label = DIALECTS[dialect]

    try:
        tree = sqlglot.parse_one(sql, read=dialect)
    except ParseError as exc:
        first_line = str(exc).splitlines()[0]
        return SqlCheck(False, False, [f"This isn't valid {label} syntax: {first_line}"])

    # sqlglot's parser is permissive across dialects, so it accepts some foreign
    # constructs. LIMIT in SQL Server / Oracle is the most common such mistake, so
    # it gets an explicit check.
    if dialect in LIMIT_UNSUPPORTED and re.search(r"\blimit\s+\d+", _strip_string_literals(sql), re.IGNORECASE):
        return SqlCheck(False, False, [f"LIMIT isn't valid in {label}; use {LIMIT_UNSUPPORTED[dialect]} instead."])

    if schema is None:
        return SqlCheck(True, True)

    known = schema.table_names()
    cte_names = {cte.alias.lower() for cte in tree.find_all(exp.CTE)}

    tables_used, unknown_tables = [], []
    for table in tree.find_all(exp.Table):
        name = table.name.lower()
        if not name or name in cte_names:
            continue
        if name in known:
            if known[name] not in tables_used:
                tables_used.append(known[name])
        elif table.name not in unknown_tables:
            unknown_tables.append(table.name)

    if unknown_tables:
        names = ", ".join(f"'{t}'" for t in unknown_tables)
        return SqlCheck(True, False, [f"Uses table(s) that aren't in your schema: {names}."], tables_used)

    # qualify() resolves every column against the schema and raises on unknown or
    # ambiguous ones. It does not flag unknown tables, which is why they're
    # checked above.
    try:
        qualify(tree.copy(), schema=schema.as_sqlglot_schema(), dialect=dialect, validate_qualify_columns=True)
    except OptimizeError as exc:
        return SqlCheck(True, False, [f"Column problem: {exc}"], tables_used)
    except Exception:
        # An exotic construct the optimizer can't handle isn't evidence of a
        # hallucination, so it shouldn't count against the query.
        return SqlCheck(True, True, ["Couldn't fully verify column names for this query."], tables_used)

    return SqlCheck(True, True, [], tables_used)
