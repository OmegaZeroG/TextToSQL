import pytest

from app.schema_parser import parse_ddl
from app.schema_validation import check_sql_against_schema

SCHEMA = parse_ddl(
    """
    CREATE TABLE customers (id INT PRIMARY KEY, name TEXT, email TEXT);
    CREATE TABLE orders (id INT PRIMARY KEY, customer_id INT, total DECIMAL(10, 2), created_at DATE);
    """,
    "postgres",
)


def check(sql, dialect="postgres"):
    return check_sql_against_schema(sql, SCHEMA, dialect)


class TestValidQueries:
    @pytest.mark.parametrize("sql", [
        "SELECT name FROM customers",
        "SELECT c.name, SUM(o.total) FROM customers c JOIN orders o ON o.customer_id = c.id GROUP BY c.name",
        "SELECT * FROM customers",
        "SELECT COUNT(*) FROM orders",
        "SELECT 1",
        "SELECT name FROM customers UNION SELECT email FROM customers",
        "SELECT t.name FROM (SELECT name FROM customers) t",
        "SELECT name, ROW_NUMBER() OVER (ORDER BY name) FROM customers",
    ])
    def test_accepts_queries_that_only_use_schema_objects(self, sql):
        result = check(sql)
        assert result.syntax_valid and result.schema_ok, result.problems
        assert result.problems == []

    def test_ctes_are_not_mistaken_for_unknown_tables(self):
        sql = (
            "WITH totals AS (SELECT customer_id, SUM(total) AS s FROM orders GROUP BY customer_id) "
            "SELECT c.name, t.s FROM customers c JOIN totals t ON t.customer_id = c.id"
        )
        result = check(sql)
        assert result.schema_ok, result.problems
        assert set(result.tables_used) == {"orders", "customers"}

    def test_table_names_match_case_insensitively(self):
        assert check("SELECT name FROM CUSTOMERS").schema_ok

    def test_schema_qualified_table_names_resolve(self):
        assert check("SELECT name FROM public.customers").schema_ok

    def test_reports_the_tables_actually_used_in_schema_spelling(self):
        result = check("SELECT c.name FROM CUSTOMERS c JOIN orders o ON o.customer_id = c.id")
        assert result.tables_used == ["customers", "orders"]


class TestHallucinations:
    def test_unknown_table_is_flagged_by_name(self):
        result = check("SELECT * FROM invoices")
        assert result.syntax_valid
        assert not result.schema_ok
        assert "invoices" in result.problems[0]

    def test_unknown_table_in_a_join_is_flagged(self):
        result = check("SELECT c.name FROM customers c JOIN payments p ON p.customer_id = c.id")
        assert not result.schema_ok
        assert "payments" in result.problems[0]

    def test_unknown_column_is_flagged_by_name(self):
        result = check("SELECT c.nme FROM customers c")
        assert not result.schema_ok
        assert "nme" in result.problems[0]

    def test_unknown_unqualified_column_is_flagged(self):
        assert not check("SELECT phone FROM customers").schema_ok

    def test_column_from_the_wrong_table_is_flagged(self):
        assert not check("SELECT c.total FROM customers c").schema_ok

    def test_ambiguous_column_is_flagged(self):
        result = check("SELECT id FROM customers c JOIN orders o ON o.customer_id = c.id")
        assert not result.schema_ok


class TestDialectSyntax:
    def test_syntax_from_another_dialect_is_reported_as_invalid(self):
        result = check("SELECT TOP 5 name FROM customers", "postgres")
        assert not result.syntax_valid
        assert not result.schema_ok
        assert "PostgreSQL" in result.problems[0]

    def test_the_same_syntax_is_valid_in_its_own_dialect(self):
        assert check("SELECT TOP 5 name FROM customers", "tsql").schema_ok

    def test_limit_is_valid_in_postgres_but_not_sql_server(self):
        assert check("SELECT name FROM customers LIMIT 5", "postgres").syntax_valid
        result = check("SELECT name FROM customers LIMIT 5", "tsql")
        assert not result.syntax_valid
        assert "SQL Server" in result.problems[0] and "TOP" in result.problems[0]

    def test_limit_is_not_valid_in_oracle(self):
        result = check("SELECT name FROM customers LIMIT 5", "oracle")
        assert not result.syntax_valid
        assert "FETCH FIRST" in result.problems[0]

    def test_oracle_fetch_first_is_valid(self):
        assert check("SELECT name FROM customers FETCH FIRST 5 ROWS ONLY", "oracle").schema_ok

    def test_the_word_limit_inside_a_string_literal_is_not_flagged(self):
        assert check("SELECT name FROM customers WHERE name = 'limit 5'", "tsql").schema_ok

    def test_garbage_is_a_syntax_error(self):
        assert not check("SELEC name FROM customers").syntax_valid
