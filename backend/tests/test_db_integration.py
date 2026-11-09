"""Runs against a real Postgres (whatever DATABASE_URL points at).
Skipped automatically when none is reachable, so `pytest` stays green offline."""
import pytest
from sqlalchemy.exc import DBAPIError

from app.db import run_query
from app.schema_introspection import introspect_schema

pytestmark = pytest.mark.integration


@pytest.fixture(scope="module", autouse=True)
def require_database():
    try:
        run_query("SELECT 1", 1)
    except Exception as exc:
        pytest.skip(f"database not reachable ({type(exc).__name__})")


def test_row_limit_truncates_results():
    assert len(run_query("SELECT generate_series(1, 10) AS n", 3)) == 3


def test_result_columns_are_preserved():
    assert list(run_query("SELECT 1 AS answer", 10).columns) == ["answer"]


def test_database_itself_rejects_writes_even_if_the_guardrail_were_bypassed():
    """Defense in depth: this calls run_query directly, skipping check_sql entirely."""
    with pytest.raises(DBAPIError) as excinfo:
        run_query("CREATE TABLE guardrail_probe (x INT)", 10)
    assert "read-only transaction" in str(excinfo.value).lower()

    leftover = run_query("SELECT to_regclass('public.guardrail_probe') AS t", 1)
    assert leftover["t"].iloc[0] is None


def test_introspection_finds_seeded_tables_and_foreign_keys():
    tables = {t.name: t for t in introspect_schema()}
    if "order_items" not in tables:
        pytest.skip("database is reachable but not seeded (run data/seed.py)")
    assert {"customers", "orders", "order_items", "products", "categories"} <= set(tables)
    assert ("order_id", "orders", "order_id") in tables["order_items"].foreign_keys
