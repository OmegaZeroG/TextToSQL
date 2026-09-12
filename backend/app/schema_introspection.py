"""Extracts a structured, LLM-friendly description of the database schema:
tables, columns with types, foreign keys, and sample values for
low-cardinality columns (helps the model disambiguate e.g. status strings)."""
from dataclasses import dataclass, field

from app.db import get_read_only_connection


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


def introspect_schema() -> list[TableInfo]:
    con = get_read_only_connection()
    try:
        tables = [row[0] for row in con.execute(
            "SELECT table_name FROM information_schema.tables WHERE table_schema = 'main'"
        ).fetchall()]

        result = []
        for table in tables:
            columns_raw = con.execute(
                "SELECT column_name, data_type FROM information_schema.columns "
                "WHERE table_name = ?", [table]
            ).fetchall()

            columns = []
            for col_name, col_type in columns_raw:
                sample_values = []
                if col_type in ("VARCHAR", "BOOLEAN") :
                    try:
                        rows = con.execute(
                            f'SELECT DISTINCT "{col_name}" FROM "{table}" '
                            f'WHERE "{col_name}" IS NOT NULL LIMIT 5'
                        ).fetchall()
                        sample_values = [r[0] for r in rows]
                    except Exception:
                        pass
                columns.append(ColumnInfo(name=col_name, type=col_type, sample_values=sample_values))

            fk_rows = con.execute("""
                SELECT constraint_column_names, referenced_table, referenced_column_names
                FROM duckdb_constraints()
                WHERE table_name = ? AND constraint_type = 'FOREIGN KEY'
            """, [table]).fetchall()

            foreign_keys = []
            for col_names, ref_table, ref_col_names in fk_rows:
                for c, rc in zip(col_names, ref_col_names):
                    foreign_keys.append((c, ref_table, rc))

            result.append(TableInfo(name=table, columns=columns, foreign_keys=foreign_keys))
        return result
    finally:
        con.close()


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
