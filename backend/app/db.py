import pandas as pd
from sqlalchemy import create_engine, text
from sqlalchemy.engine import Engine

from app.config import DATABASE_URL

_engine: Engine = create_engine(DATABASE_URL, pool_pre_ping=True)


def get_engine() -> Engine:
    return _engine


def run_query(sql: str, row_limit: int) -> pd.DataFrame:
    """SET TRANSACTION READ ONLY is the sandboxing boundary: even if a
    write statement slips past the guardrail layer, Postgres itself
    rejects it before anything is committed."""
    with _engine.connect() as conn:
        with conn.begin():
            conn.execute(text("SET TRANSACTION READ ONLY"))
            result = conn.execute(text(sql))
            rows = result.fetchmany(row_limit)
            columns = list(result.keys())
    return pd.DataFrame(rows, columns=columns)


def explain(sql: str) -> str:
    with _engine.connect() as conn:
        result = conn.execute(text(f"EXPLAIN {sql}"))
        return "\n".join(str(row[0]) for row in result.fetchall())
