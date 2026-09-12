"""In-memory query history for the demo session.

Deliberately not persisted to disk: this is a portfolio demo, not a
multi-user product, and keeping it in-process avoids needing a second
stateful service alongside the read-only analytical DuckDB file.
"""
from datetime import datetime, timezone

_history: list[dict] = []
_next_id = 1


def record(question: str, sql: str, row_count: int, confidence: float) -> None:
    global _next_id
    _history.append({
        "id": _next_id,
        "question": question,
        "sql": sql,
        "row_count": row_count,
        "confidence": confidence,
        "created_at": datetime.now(timezone.utc).isoformat(),
    })
    _next_id += 1


def get_all(limit: int = 50) -> list[dict]:
    return list(reversed(_history))[:limit]
