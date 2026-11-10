"""The trial run: a throwaway database built from the user's schema (app/sql_execution.py)."""
import sqlite3

import pytest

from app.schema_parser import parse_ddl
from app.sql_execution import (
    ROWS_PER_TABLE,
    build_test_database,
    check_result_values,
    verify_by_execution,
)

DDL = """
CREATE TABLE categories (category_id INT PRIMARY KEY, name VARCHAR(50));
CREATE TABLE products (
    product_id INT PRIMARY KEY, name VARCHAR(50), category_id INT REFERENCES categories(category_id),
    price DECIMAL(10, 2), in_stock BOOLEAN, added_on DATE
);
CREATE TABLE customers (customer_id INT PRIMARY KEY, name VARCHAR(50), email VARCHAR(80), city VARCHAR(30), manager_id INT);
CREATE TABLE orders (
    order_id INT PRIMARY KEY, customer_id INT REFERENCES customers(customer_id),
    order_date DATE, placed_at TIMESTAMP, amount DECIMAL(10, 2), status VARCHAR(20)
);
CREATE TABLE order_items (
    order_id INT REFERENCES orders(order_id), product_id INT REFERENCES products(product_id),
    quantity INT, PRIMARY KEY (order_id, product_id)
);
"""


@pytest.fixture(scope="module")
def conn():
    connection = build_test_database(parse_ddl(DDL, "postgres"))
    yield connection
    connection.close()


def rows(connection, sql):
    return connection.execute(sql).fetchall()


class TestTestDatabase:
    def test_every_table_is_created_and_populated(self, conn):
        for table in ("categories", "products", "customers", "orders"):
            assert rows(conn, f"SELECT COUNT(*) FROM {table}")[0][0] == ROWS_PER_TABLE

    def test_it_is_deterministic(self):
        schema = parse_ddl(DDL, "postgres")
        first = build_test_database(schema).execute("SELECT * FROM orders ORDER BY order_id").fetchall()
        second = build_test_database(schema).execute("SELECT * FROM orders ORDER BY order_id").fetchall()
        assert first == second

    def test_foreign_keys_point_at_real_parent_rows(self, conn):
        orphaned_orders = rows(
            conn,
            "SELECT COUNT(*) FROM orders WHERE customer_id IS NOT NULL "
            "AND customer_id NOT IN (SELECT customer_id FROM customers)",
        )
        assert orphaned_orders[0][0] == 0
        orphaned_products = rows(
            conn, "SELECT COUNT(*) FROM products WHERE category_id NOT IN (SELECT category_id FROM categories)"
        )
        assert orphaned_products[0][0] == 0

    def test_some_parents_have_no_children_so_anti_joins_are_exercised(self, conn):
        childless = rows(
            conn,
            "SELECT COUNT(*) FROM customers c WHERE NOT EXISTS (SELECT 1 FROM orders o WHERE o.customer_id = c.customer_id)",
        )[0][0]
        assert 0 < childless < ROWS_PER_TABLE

    def test_dates_cross_a_year_boundary(self, conn):
        months = {r[0] for r in rows(conn, "SELECT substr(order_date, 1, 7) FROM orders WHERE order_date IS NOT NULL")}
        assert "2024-12" in months and "2025-01" in months

    def test_timestamps_carry_a_time_of_day(self, conn):
        assert " " in rows(conn, "SELECT placed_at FROM orders WHERE placed_at IS NOT NULL LIMIT 1")[0][0]

    def test_there_are_nulls_and_zeros_to_trip_naive_queries(self, conn):
        assert rows(conn, "SELECT COUNT(*) FROM orders WHERE amount IS NULL")[0][0] >= 1
        assert rows(conn, "SELECT COUNT(*) FROM orders WHERE amount = 0")[0][0] >= 1

    def test_booleans_are_stored_as_zero_and_one(self, conn):
        assert {r[0] for r in rows(conn, "SELECT DISTINCT in_stock FROM products WHERE in_stock IS NOT NULL")} == {0, 1}

    def test_composite_primary_keys_do_not_break_loading(self, conn):
        assert rows(conn, "SELECT COUNT(*) FROM order_items")[0][0] > 0

    def test_it_is_read_only_once_built(self, conn):
        with pytest.raises(sqlite3.OperationalError):
            conn.execute("DELETE FROM orders")

    def test_status_like_columns_get_realistic_values(self, conn):
        statuses = {r[0] for r in rows(conn, "SELECT DISTINCT status FROM orders WHERE status IS NOT NULL")}
        assert statuses >= {"active", "pending"}

    def test_a_cyclic_foreign_key_does_not_hang_or_crash(self):
        schema = parse_ddl(
            "CREATE TABLE a (id INT PRIMARY KEY, b_id INT REFERENCES b(id)); "
            "CREATE TABLE b (id INT PRIMARY KEY, a_id INT REFERENCES a(id));",
            "postgres",
        )
        assert build_test_database(schema).execute("SELECT COUNT(*) FROM a").fetchone()[0] == ROWS_PER_TABLE


class TestRunning:
    schema = parse_ddl(DDL, "postgres")

    def test_a_correct_query_runs_and_returns_rows(self):
        result = verify_by_execution("SELECT city, COUNT(*) AS n FROM customers GROUP BY city", self.schema, "postgres")
        assert result.ran and result.issues == [] and result.rows

    def test_without_a_schema_nothing_runs(self):
        result = verify_by_execution("SELECT 1", None, "postgres")
        assert not result.ran and "no schema" in result.note

    def test_on_sqlite_every_error_counts(self):
        result = verify_by_execution("SELECT nope FROM orders", self.schema, "sqlite")
        assert result.ran and result.issues[0].code == "execution_error" and "nope" in result.issues[0].message

    def test_on_sqlite_a_missing_function_counts(self):
        result = verify_by_execution("SELECT YEAR(order_date) FROM orders", self.schema, "sqlite")
        assert result.issues and "YEAR" in result.issues[0].message

    def test_on_other_dialects_what_the_test_engine_merely_lacks_is_not_blamed_on_the_query(self):
        result = verify_by_execution("SELECT DATE_TRUNC('month', order_date) FROM orders", self.schema, "postgres")
        assert not result.ran and result.issues == []

    def test_on_other_dialects_real_structural_mistakes_still_count(self):
        sql = "SELECT customer_id FROM orders o JOIN customers c ON o.customer_id = c.customer_id"
        result = verify_by_execution(sql, self.schema, "postgres")
        assert result.issues and "ambiguous" in result.issues[0].message

    def test_a_query_that_cannot_be_translated_is_skipped_not_failed(self):
        result = verify_by_execution("SELECT FROM WHERE", self.schema, "mysql")
        assert not result.ran and result.issues == []

    def test_a_runaway_query_is_stopped(self, monkeypatch):
        import app.sql_execution as module

        monkeypatch.setattr(module, "TIME_LIMIT_SECONDS", 0.05)
        sql = """WITH RECURSIVE n(i) AS (SELECT 1 UNION ALL SELECT i + 1 FROM n WHERE i < 100000000)
                 SELECT COUNT(*) FROM n"""
        result = verify_by_execution(sql, self.schema, "sqlite")
        assert not result.ran and "too long" in result.note

    def test_results_are_capped(self):
        result = verify_by_execution("SELECT * FROM orders o1, orders o2, orders o3", self.schema, "sqlite")
        assert len(result.rows) <= 500

    def test_a_query_cannot_allocate_a_huge_value(self):
        result = verify_by_execution("SELECT randomblob(1000000000)", self.schema, "sqlite")
        assert result.issues and "too big" in result.issues[0].message.lower()

    def test_the_test_run_can_never_change_anything(self):
        result = verify_by_execution("DELETE FROM orders", self.schema, "sqlite")
        assert result.issues and "readonly" in result.issues[0].message.lower().replace(" ", "")


class TestNullHandling:
    """Test G: why `= NULL` is wrong, shown on real rows."""

    def test_equals_null_matches_nothing_but_is_null_matches_the_rows(self, conn):
        assert rows(conn, "SELECT COUNT(*) FROM customers WHERE manager_id = NULL")[0][0] == 0
        assert rows(conn, "SELECT COUNT(*) FROM customers WHERE manager_id IS NULL")[0][0] >= 1

    def test_not_equals_null_matches_nothing_but_is_not_null_does(self, conn):
        assert rows(conn, "SELECT COUNT(*) FROM customers WHERE manager_id <> NULL")[0][0] == 0
        assert rows(conn, "SELECT COUNT(*) FROM customers WHERE manager_id IS NOT NULL")[0][0] >= 1

    def test_the_two_forms_partition_the_table(self, conn):
        is_null = rows(conn, "SELECT COUNT(*) FROM customers WHERE manager_id IS NULL")[0][0]
        not_null = rows(conn, "SELECT COUNT(*) FROM customers WHERE manager_id IS NOT NULL")[0][0]
        assert is_null + not_null == ROWS_PER_TABLE


class TestZeroDenominators:
    """Test H: the guarded form returns NULL for a zero denominator instead of an error or a wrong number."""

    def test_the_test_data_includes_a_zero_denominator(self, conn):
        assert rows(conn, "SELECT COUNT(*) FROM orders WHERE amount = 0")[0][0] >= 1

    def test_nullif_turns_division_by_zero_into_null(self, conn):
        assert rows(conn, "SELECT 100.0 * 5 / NULLIF(0, 0)")[0][0] is None

    def test_a_percentage_over_a_zero_total_is_null_not_a_crash(self, conn):
        sql = (
            "SELECT 100.0 * COUNT(*) / NULLIF(SUM(amount), 0) FROM orders WHERE amount = 0"
        )
        assert rows(conn, sql)[0][0] is None

    def test_a_percentage_over_a_real_total_is_a_number(self, conn):
        sql = "SELECT 100.0 * SUM(CASE WHEN status = 'active' THEN 1 ELSE 0 END) / NULLIF(COUNT(*), 0) FROM orders"
        assert 0 < rows(conn, sql)[0][0] <= 100


class TestResultChecks:
    def test_an_impossible_date_is_reported_once(self):
        issues = check_result_values(["m"], [("2025-00-01",), ("2025-00-01",), ("2025-03-01",)])
        assert [i.code for i in issues] == ["invalid_date_output"]

    @pytest.mark.parametrize("value", ["2025-13-01", "2025-00", "2026-00-01 00:00:00"])
    def test_month_zero_and_thirteen_are_caught_in_any_shape(self, value):
        assert check_result_values(["m"], [(value,)])

    @pytest.mark.parametrize("value", ["2025-01-01", "2025-12", "hello", "2025", "12-2025", "2025-12-31 23:59:59"])
    def test_ordinary_values_pass(self, value):
        assert check_result_values(["m"], [(value,)]) == []

    @pytest.mark.parametrize("column", ["month", "Month", "month_of_year"])
    def test_a_month_number_outside_1_to_12_is_caught(self, column):
        assert check_result_values([column], [(0,)])
        assert check_result_values([column], [(13,)])

    def test_months_in_range_pass(self):
        assert check_result_values(["month"], [(1,), (12,)]) == []

    def test_other_integer_columns_are_left_alone(self):
        assert check_result_values(["month_num"], [(24312,)]) == []

    def test_empty_results_are_fine(self):
        assert check_result_values(["a"], []) == []
