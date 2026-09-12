import duckdb
import pandas as pd

from app.config import DB_PATH


def get_read_only_connection() -> duckdb.DuckDBPyConnection:
    """DuckDB has no user-level GRANTs; read_only=True is the sandboxing
    boundary — any write statement raises before touching the file."""
    return duckdb.connect(DB_PATH, read_only=True)


def run_query(sql: str, row_limit: int) -> pd.DataFrame:
    con = get_read_only_connection()
    try:
        result = con.execute(sql).fetch_df()
        return result.head(row_limit)
    finally:
        con.close()


def explain(sql: str) -> str:
    con = get_read_only_connection()
    try:
        plan_rows = con.execute(f"EXPLAIN {sql}").fetchall()
        return "\n".join(str(row) for row in plan_rows)
    finally:
        con.close()
