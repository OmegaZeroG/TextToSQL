import pytest

from app.guardrails import check_sql


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


def test_strips_the_trailing_semicolon():
    assert check_sql("SELECT 1;").sql == "SELECT 1"


def test_never_adds_or_changes_a_limit():
    # Nothing is executed, so the SQL is handed back exactly as written.
    assert check_sql("SELECT * FROM orders").sql == "SELECT * FROM orders"
    assert check_sql("SELECT * FROM orders LIMIT 50000").sql == "SELECT * FROM orders LIMIT 50000"


def test_deep_nesting_is_allowed():
    assert check_sql("SELECT * FROM (SELECT * FROM (SELECT * FROM (SELECT * FROM (SELECT 1) a) b) c) d").allowed


def test_blocked_result_carries_no_sql():
    assert check_sql("DROP TABLE orders").sql is None
