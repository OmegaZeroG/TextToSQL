"""Extracts a structured, LLM-friendly description of the database schema:
tables, columns with types, foreign keys, and sample values for
low-cardinality columns (helps the model disambiguate e.g. status strings)."""
from dataclasses import dataclass, field

from sqlalchemy import inspect, text

from app.db import get_engine


@dataclass
class ColumnInfo:
    name: str
    type: str
    sample_values: list = field(default_factory=list)


@dataclass
class TableInfo:
    name: str
    columns: list[ColumnInfo]
    foreign_keys: list[tuple[str, str, str]]  # (column, ref_table, ref_column)


SAMPLEABLE_TYPES = ("VARCHAR", "CHAR", "TEXT", "BOOLEAN", "ENUM")


def introspect_schema() -> list[TableInfo]:
    engine = get_engine()
    inspector = inspect(engine)

    result = []
    with engine.connect() as conn:
        for table in inspector.get_table_names(schema="public"):
            columns = []
            for col in inspector.get_columns(table, schema="public"):
                col_type = str(col["type"]).upper()
                sample_values = []
                if any(t in col_type for t in SAMPLEABLE_TYPES):
                    try:
                        rows = conn.execute(text(
                            f'SELECT DISTINCT "{col["name"]}" FROM "{table}" '
                            f'WHERE "{col["name"]}" IS NOT NULL LIMIT 5'
                        )).fetchall()
                        sample_values = [r[0] for r in rows]
                    except Exception:
                        pass
                columns.append(ColumnInfo(name=col["name"], type=col_type, sample_values=sample_values))

            foreign_keys = []
            for fk in inspector.get_foreign_keys(table, schema="public"):
                ref_table = fk["referred_table"]
                for col_name, ref_col in zip(fk["constrained_columns"], fk["referred_columns"]):
                    foreign_keys.append((col_name, ref_table, ref_col))

            result.append(TableInfo(name=table, columns=columns, foreign_keys=foreign_keys))
    return result


def format_schema_for_prompt(tables: list[TableInfo], relevant_tables: set[str] | None = None) -> str:
    lines = []
    for table in tables:
        if relevant_tables is not None and table.name not in relevant_tables:
            continue
        lines.append(f"TABLE {table.name}")
        for col in table.columns:
            sample = f" (examples: {col.sample_values})" if col.sample_values else ""
            lines.append(f"  - {col.name}: {col.type}{sample}")
        for col, ref_table, ref_col in table.foreign_keys:
            lines.append(f"  FOREIGN KEY {col} -> {ref_table}.{ref_col}")
        lines.append("")
    return "\n".join(lines)


def filter_relevant_tables(question: str, tables: list[TableInfo]) -> set[str]:
    """Lightweight keyword-overlap relevance filter. Good enough at this
    schema size; swap for an embedding-similarity filter for larger schemas."""
    question_lower = question.lower()
    relevant = set()
    for table in tables:
        haystack = table.name.lower() + " " + " ".join(c.name.lower() for c in table.columns)
        table_words = table.name.lower().replace("_", " ").split()
        if any(word in question_lower for word in table_words) or table.name.lower() in question_lower:
            relevant.add(table.name)
        else:
            for col in table.columns:
                if col.name.lower() in question_lower and len(col.name) > 3:
                    relevant.add(table.name)
                    break
    # Always include tables joined via FK to an already-relevant table (one hop)
    expanded = set(relevant)
    for table in tables:
        if table.name in relevant:
            for _, ref_table, _ in table.foreign_keys:
                expanded.add(ref_table)
    return expanded if expanded else {t.name for t in tables}
