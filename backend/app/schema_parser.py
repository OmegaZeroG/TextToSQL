"""Turns a user-supplied schema into a structured form.

Accepts either real DDL (CREATE TABLE ...) or free text such as a plain-English
description or a whole pasted problem statement. DDL is parsed deterministically
with sqlglot, so the common case needs no LLM call; anything that doesn't parse
as DDL is converted to DDL by the LLM, then parsed the same way.
"""
import json
import re
from dataclasses import dataclass
from typing import Callable

import sqlglot
from sqlglot import exp
from sqlglot.errors import SqlglotError

from app.llm.base import LLMProvider

DIALECTS = {
    "postgres": "PostgreSQL",
    "mysql": "MySQL",
    "sqlite": "SQLite",
    "tsql": "SQL Server",
    "oracle": "Oracle",
    "bigquery": "BigQuery",
    "snowflake": "Snowflake",
}


class SchemaParseError(ValueError):
    pass


@dataclass
class Column:
    name: str
    type: str
    primary_key: bool = False
    foreign_key: str | None = None  # "table.column" (or just "table") this column references


@dataclass
class Table:
    name: str
    columns: list[Column]


@dataclass
class ParsedSchema:
    tables: list[Table]

    def table_names(self) -> dict[str, str]:
        """lower-case name -> name as written in the schema."""
        return {t.name.lower(): t.name for t in self.tables}

    def as_sqlglot_schema(self) -> dict[str, dict[str, str]]:
        return {t.name: {c.name: c.type or "TEXT" for c in t.columns} for t in self.tables}


@dataclass
class AnalyzedSchema:
    ddl: str
    source: str  # "ddl" if the input already parsed, "text" if the LLM converted it
    parsed: ParsedSchema


def _table_statements(text: str, dialect: str) -> list[exp.Create]:
    """The CREATE TABLE statements (with a column list) found in `text`."""
    try:
        statements = sqlglot.parse(text, read=dialect)
    except SqlglotError as exc:
        raise SchemaParseError(str(exc).splitlines()[0]) from exc

    found = []
    for statement in statements:
        if not isinstance(statement, exp.Create) or str(statement.args.get("kind", "")).upper() != "TABLE":
            continue
        target = statement.this
        if not isinstance(target, exp.Schema):
            continue  # e.g. CREATE TABLE x AS SELECT ... has no column list to learn from
        has_columns = any(isinstance(col, exp.ColumnDef) for col in target.expressions)
        if target.this.name and has_columns:
            found.append(statement)

    if not found:
        raise SchemaParseError("no CREATE TABLE statements with columns were found")
    return found


def _table_name(statement: exp.Create) -> str:
    return statement.this.this.name


def _to_parsed(statements: list[exp.Create], dialect: str) -> ParsedSchema:
    tables = []
    for statement in statements:
        primary_keys, foreign_keys = _key_columns(statement)
        columns = [
            Column(
                name=col.name,
                type=col.args["kind"].sql(dialect=dialect) if col.args.get("kind") else "",
                primary_key=col.name.lower() in primary_keys,
                foreign_key=foreign_keys.get(col.name.lower()),
            )
            for col in statement.this.expressions
            if isinstance(col, exp.ColumnDef)
        ]
        tables.append(Table(name=_table_name(statement), columns=columns))
    return ParsedSchema(tables=tables)


def _reference_target(reference: exp.Reference) -> str:
    """'dept (id)' -> 'dept.id'; 'dept' -> 'dept'."""
    target = reference.this
    if isinstance(target, exp.Schema):
        table, columns = target.this.name, [c.name for c in target.expressions]
        return f"{table}.{columns[0]}" if columns else table
    return target.name


def _key_columns(statement: exp.Create) -> tuple[set[str], dict[str, str]]:
    """Primary-key columns (lower-case) and {foreign-key column: 'table.column'},
    whether declared inline on the column, at table level, or inside a named
    CONSTRAINT."""
    primary_keys: set[str] = set()
    foreign_keys: dict[str, str] = {}

    def table_level(node):
        if isinstance(node, exp.PrimaryKey):
            primary_keys.update(c.name.lower() for c in node.expressions)
        elif isinstance(node, exp.ForeignKey):
            reference = node.args.get("reference")
            if isinstance(reference, exp.Reference):
                target = _reference_target(reference)
                for column in node.expressions:
                    foreign_keys[column.name.lower()] = target

    for node in statement.this.expressions:
        if isinstance(node, exp.ColumnDef):
            for constraint in node.args.get("constraints") or []:
                kind = constraint.args.get("kind")
                if isinstance(kind, exp.PrimaryKeyColumnConstraint):
                    primary_keys.add(node.name.lower())
                elif isinstance(kind, exp.Reference):
                    foreign_keys[node.name.lower()] = _reference_target(kind)
        elif isinstance(node, exp.Constraint):
            for inner in node.expressions:
                table_level(inner)
        else:
            table_level(node)
    return primary_keys, foreign_keys


def parse_ddl(text: str, dialect: str) -> ParsedSchema:
    return _to_parsed(_table_statements(text, dialect), dialect)


def _render(statements: list[exp.Create], dialect: str) -> str:
    text = "\n\n".join(s.sql(dialect=dialect, pretty=True) + ";" for s in statements)
    # sqlglot's pretty printer explodes foreign-key references over three lines.
    return re.sub(
        r"(REFERENCES\s+\S+)\s*\(\s*([^()]*?)\s*\)",
        lambda m: m.group(1) + " (" + re.sub(r"\s+", " ", m.group(2)) + ")",  # no backslash inside an f-string: a SyntaxError before Python 3.12
        text,
    )


def merge_ddl(current: str, additions: str, dialect: str) -> str:
    """Upsert the CREATE TABLE statements in `additions` into `current`: a table
    with an existing name is replaced in place, a new one is appended."""
    merged = {_table_name(s).lower(): s for s in _table_statements(current, dialect)}
    for statement in _table_statements(additions, dialect):
        merged[_table_name(statement).lower()] = statement
    return _render(list(merged.values()), dialect)


def diff_schemas(old: ParsedSchema, new: ParsedSchema) -> list[str]:
    """Human-readable list of what changed between two schemas."""
    old_tables = {t.name.lower(): t for t in old.tables}
    new_tables = {t.name.lower(): t for t in new.tables}
    changes = []

    for key, table in new_tables.items():
        if key not in old_tables:
            changes.append(f"Added table {table.name} ({len(table.columns)} columns)")
    for key, table in old_tables.items():
        if key not in new_tables:
            changes.append(f"Removed table {table.name}")

    for key, new_table in new_tables.items():
        if key not in old_tables:
            continue
        old_cols = {c.name.lower(): c for c in old_tables[key].columns}
        new_cols = {c.name.lower(): c for c in new_table.columns}
        for col_key, col in new_cols.items():
            if col_key not in old_cols:
                changes.append(f"Added column {new_table.name}.{col.name} ({col.type or 'no type'})")
            elif col.type.upper() != old_cols[col_key].type.upper():
                changes.append(
                    f"Changed type of {new_table.name}.{col.name}: {old_cols[col_key].type or 'no type'} -> {col.type or 'no type'}"
                )
        for col_key, col in old_cols.items():
            if col_key not in new_cols:
                changes.append(f"Removed column {new_table.name}.{col.name}")
    return changes


TEXT_TO_DDL_PROMPT = """You convert a description of a database schema into {dialect} DDL.

The input may be plain English, a pasted problem statement, an ASCII table layout, or a mix of \
these. It may also contain a question or instructions about a query: ignore those and extract \
only the schema.

Rules:
1. Output one CREATE TABLE statement per table, in {dialect} syntax.
2. Use only tables and columns that appear in the text or are clearly implied by it. Never \
invent extra ones.
3. If a column's type isn't stated, infer a sensible one from its name and any sample values.
4. Mark primary keys and foreign keys when the text states them or makes them evident.
5. Respond with a single JSON object: {{"ddl": "<all CREATE TABLE statements, separated by newlines>"}}
"""


def _convert_text_to_ddl(llm: LLMProvider, text: str, dialect: str, previous_error: str | None) -> str:
    user = text
    if previous_error:
        user += f"\n\n(Your previous DDL failed to parse as {DIALECTS[dialect]}: {previous_error}. Fix it.)"
    raw = llm.complete(TEXT_TO_DDL_PROMPT.format(dialect=DIALECTS[dialect]), user, json_mode=True)
    raw = re.sub(r"^```(json)?|```$", "", raw.strip(), flags=re.MULTILINE).strip()
    payload = json.loads(raw)
    if not isinstance(payload, dict) or not isinstance(payload.get("ddl"), str):
        raise SchemaParseError("the model did not return a 'ddl' string")
    return payload["ddl"]


def analyze_schema(text: str, dialect: str, get_llm: Callable[[], LLMProvider]) -> AnalyzedSchema:
    """`get_llm` is a factory so the LLM (and its API key) is only needed when
    the input isn't already valid DDL."""
    try:
        return AnalyzedSchema(ddl=text.strip(), source="ddl", parsed=parse_ddl(text, dialect))
    except SchemaParseError:
        pass

    llm = get_llm()
    error = None
    for _ in range(2):
        ddl = _convert_text_to_ddl(llm, text, dialect, error)
        try:
            return AnalyzedSchema(ddl=ddl.strip(), source="text", parsed=parse_ddl(ddl, dialect))
        except SchemaParseError as exc:
            error = str(exc)
    raise SchemaParseError(f"couldn't turn that text into a valid schema ({error})")


class SchemaChangeError(SchemaParseError):
    """The change was understood but must not be applied (nothing is modified)."""


@dataclass
class UpdatedSchema:
    ddl: str
    source: str  # "ddl" if the change was explicit CREATE TABLE statements, "text" if the LLM applied it
    parsed: ParsedSchema
    changes: list[str]


APPLY_CHANGE_PROMPT = """You update a database schema. You are given the CURRENT schema as \
{dialect} DDL and a CHANGE REQUEST written in plain English or SQL (it may be ALTER TABLE \
statements). Return the COMPLETE updated schema as {dialect} DDL: every table, one CREATE TABLE \
statement per table.

Rules:
1. Apply only what the change request asks for. Keep every other table, column, type, key and \
constraint exactly as it is in the current schema.
2. Never drop a table or column unless the request explicitly says to remove, drop, delete or \
rename it.
3. Use only identifiers from the current schema or the change request. Never invent extras.
4. Respond with a single JSON object: {{"ddl": "<the complete updated DDL>"}}
"""

REMOVAL_WORDS = re.compile(
    r"\b(remove|drop|delete|rename|replace|get rid|without|instead|no longer|merge|split)\b", re.IGNORECASE
)


def _llm_apply_change(
    llm: LLMProvider, current_ddl: str, change_text: str, dialect: str, previous_error: str | None
) -> str:
    user = f"CURRENT SCHEMA:\n{current_ddl}\n\nCHANGE REQUEST:\n{change_text}"
    if previous_error:
        user += f"\n\n(Your previous DDL failed to parse as {DIALECTS[dialect]}: {previous_error}. Fix it.)"
    raw = llm.complete(APPLY_CHANGE_PROMPT.format(dialect=DIALECTS[dialect]), user, json_mode=True)
    raw = re.sub(r"^```(json)?|```$", "", raw.strip(), flags=re.MULTILINE).strip()
    payload = json.loads(raw)
    if not isinstance(payload, dict) or not isinstance(payload.get("ddl"), str):
        raise SchemaParseError("the model did not return a 'ddl' string")
    return payload["ddl"]


def apply_schema_change(
    current_ddl: str, change_text: str, dialect: str, get_llm: Callable[[], LLMProvider]
) -> UpdatedSchema:
    """Apply a change to a saved schema. Atomic: either returns the full updated
    schema plus a list of exactly what changed, or raises and changes nothing."""
    try:
        old = parse_ddl(current_ddl, dialect)
    except SchemaParseError as exc:
        raise SchemaChangeError(f"your saved schema can't be read ({exc})") from exc

    try:
        new_ddl, source = merge_ddl(current_ddl, change_text, dialect), "ddl"
    except SchemaParseError:
        llm, error = get_llm(), None
        for _ in range(2):
            candidate = _llm_apply_change(llm, current_ddl, change_text, dialect, error)
            try:
                parse_ddl(candidate, dialect)
                new_ddl, source = candidate.strip(), "text"
                break
            except SchemaParseError as exc:
                error = str(exc)
        else:
            raise SchemaChangeError(f"couldn't turn that change into a valid schema ({error})")

    new = parse_ddl(new_ddl, dialect)
    changes = diff_schemas(old, new)

    if not changes:
        raise SchemaChangeError(
            "that doesn't change anything: either the schema already matches, "
            "or the text didn't describe a schema change"
        )
    removals = [c for c in changes if c.startswith("Removed")]
    if source == "text" and removals and not REMOVAL_WORDS.search(change_text):
        raise SchemaChangeError(
            "the update would also have removed things you didn't ask to remove "
            f"({'; '.join(removals)}), so nothing was changed"
        )
    return UpdatedSchema(ddl=new_ddl, source=source, parsed=new, changes=changes)
