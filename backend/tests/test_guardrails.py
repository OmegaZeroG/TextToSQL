import pytest

from app import guardrails
from app.guardrails import check_sql


@pytest.fixture(autouse=True)
def default_limits(monkeypatch):
    monkeypatch.setattr(guardrails, "MAX_ROW_LIMIT", 1000)
    monkeypatch.setattr(guardrails, "MAX_SUBQUERY_DEPTH", 3)


@pytest.mark.parametrize("sql", [
    "SELECT * FROM orders",
    "select count(*) from orders",
    "SELECT * FROM orders;",
    "WITH recent AS (SELECT * FROM orders) SELECT * FROM recent",
    "SELECT c.city, COUNT(*) FROM customers c GROUP BY c.city",
    "SELECT * FROM products WHERE name = 'DROP TABLE'",
    "SELECT updated_at, deleted FROM audit_log",
])
def test_allows_read_only_queries(sql):
    result = check_sql(sql)
    assert result.allowed, result.reason


@pytest.mark.parametrize("sql", [
    "DELETE FROM orders WHERE status = 'cancelled'",
    "UPDATE orders SET status = 'x'",
    "INSERT INTO orders VALUES (1)",
    "DROP TABLE orders",
    "drop table orders",
    "ALTER TABLE orders ADD COLUMN x INT",
    "CREATE TABLE t (x INT)",
    "TRUNCATE orders",
    "EXPLAIN SELECT 1",
    "SET statement_timeout = 0",
    "GRANT ALL ON orders TO public",
    "COPY orders TO '/tmp/orders.csv'",
])
def test_blocks_writes_ddl_and_non_select_statements(sql):
    result = check_sql(sql)
    assert not result.allowed
    assert result.reason


def test_blocks_write_hidden_inside_a_cte():
    result = check_sql("WITH d AS (DELETE FROM orders RETURNING *) SELECT * FROM d")
    assert not result.allowed
    assert "DELETE" in result.reason


def test_blocks_stacked_statements():
    result = check_sql("SELECT 1; DROP TABLE orders")
    assert not result.allowed
    assert "single" in result.reason.lower()


@pytest.mark.parametrize("sql", ["", "   ", "\n\t"])
def test_blocks_empty_input(sql):
    assert not check_sql(sql).allowed


def test_injects_row_limit_when_missing():
    assert check_sql("SELECT * FROM orders").sql == "SELECT * FROM orders LIMIT 1000"


def test_strips_trailing_semicolon_before_adding_limit():
    assert check_sql("SELECT 1;").sql == "SELECT 1 LIMIT 1000"


def test_keeps_a_smaller_existing_limit():
    assert check_sql("SELECT * FROM orders LIMIT 5").sql == "SELECT * FROM orders LIMIT 5"


def test_limit_match_is_case_insensitive():
    assert "LIMIT 7" in check_sql("select * from orders limit 7").sql


def test_caps_an_oversized_limit():
    assert check_sql("SELECT * FROM orders LIMIT 50000").sql == "SELECT * FROM orders LIMIT 1000"


def test_row_limit_is_configurable(monkeypatch):
    monkeypatch.setattr(guardrails, "MAX_ROW_LIMIT", 25)
    assert check_sql("SELECT * FROM orders").sql.endswith("LIMIT 25")


class TestWhenNotExecuting:
    """for_execution=False: SQL is only generated for display, so the cost limits
    (row cap, nesting depth) don't apply, but the safety rules must."""

    def test_no_row_limit_is_injected(self):
        assert check_sql("SELECT * FROM orders;", for_execution=False).sql == "SELECT * FROM orders"

    def test_an_existing_limit_is_left_alone(self):
        assert check_sql("SELECT * FROM orders LIMIT 50000", for_execution=False).sql == "SELECT * FROM orders LIMIT 50000"

    def test_deep_nesting_is_allowed(self):
        assert check_sql("SELECT * FROM (SELECT * FROM (SELECT * FROM (SELECT * FROM (SELECT 1) a) b) c) d", for_execution=False).allowed

    @pytest.mark.parametrize("sql", [
        "DELETE FROM orders",
        "DROP TABLE orders",
        "UPDATE orders SET status = 'x'",
        "SELECT 1; DROP TABLE orders",
        "WITH d AS (DELETE FROM orders RETURNING *) SELECT * FROM d",
        "",
    ])
    def test_safety_rules_still_apply(self, sql):
        assert not check_sql(sql, for_execution=False).allowed


DEPTH_3 ="SELECT * FROM (SELECT * FROM (SELECT * FROM (SELECT 1) a) b) c"
DEPTH_4 = "SELECT * FROM (SELECT * FROM (SELECT * FROM (SELECT * FROM (SELECT 1) a) b) c) d"


def test_allows_nesting_at_the_limit():
    assert check_sql(DEPTH_3).allowed


def test_blocks_nesting_beyond_the_limit():
    result = check_sql(DEPTH_4)
    assert not result.allowed
    assert "nesting depth" in result.reason


def test_nesting_limit_is_configurable(monkeypatch):
    monkeypatch.setattr(guardrails, "MAX_SUBQUERY_DEPTH", 1)
    assert not check_sql("SELECT * FROM (SELECT * FROM (SELECT 1) a) b").allowed
