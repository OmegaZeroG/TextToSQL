import pandas as pd
import pytest
from fastapi.testclient import TestClient

from app import history, main
from app.schema_introspection import ColumnInfo, TableInfo
from tests.helpers import FakeLLM


@pytest.fixture(autouse=True)
def reset_history():
    history._history.clear()
    history._next_id = 1


@pytest.fixture
def tables():
    """Same shape as the seeded e-commerce schema."""
    def col(name, type_="INTEGER", samples=None):
        return ColumnInfo(name=name, type=type_, sample_values=samples or [])

    return [
        TableInfo("categories", [col("category_id"), col("name", "VARCHAR")], []),
        TableInfo(
            "products",
            [col("product_id"), col("name", "VARCHAR"), col("category_id"), col("price", "NUMERIC(10, 2)")],
            [("category_id", "categories", "category_id")],
        ),
        TableInfo(
            "customers",
            [col("customer_id"), col("first_name", "VARCHAR"), col("city", "VARCHAR", ["Austin", "Seattle"])],
            [],
        ),
        TableInfo(
            "orders",
            [col("order_id"), col("customer_id"), col("order_date", "DATE"),
             col("status", "VARCHAR", ["completed", "processing"])],
            [("customer_id", "customers", "customer_id")],
        ),
        TableInfo(
            "order_items",
            [col("order_item_id"), col("order_id"), col("product_id"), col("quantity"), col("unit_price", "NUMERIC(10, 2)")],
            [("order_id", "orders", "order_id"), ("product_id", "products", "product_id")],
        ),
    ]


class ApiHarness:
    def __init__(self):
        self.client = TestClient(main.app)
        self.llm = None
        self.executed_sql = []
        self._result = pd.DataFrame({"n": [1]})

    def script(self, *responses):
        self.llm = FakeLLM(responses)
        return self.llm

    def returns(self, result):
        """A DataFrame to return from the (fake) database, or an Exception to raise."""
        self._result = result


@pytest.fixture
def api(monkeypatch, tables):
    """FastAPI client with the LLM, schema introspection and DB execution
    replaced by fakes, so the whole request pipeline runs with no network."""
    harness = ApiHarness()

    def fake_run_query(sql, row_limit):
        harness.executed_sql.append(sql)
        if isinstance(harness._result, Exception):
            raise harness._result
        return harness._result

    monkeypatch.setattr(main, "get_llm_provider", lambda: harness.llm)
    monkeypatch.setattr(main, "introspect_schema", lambda: tables)
    monkeypatch.setattr(main, "run_query", fake_run_query)
    return harness
