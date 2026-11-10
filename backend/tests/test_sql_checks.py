"""Logic and dialect checks (app/sql_checks.py).

Every rule is tested in both directions: the broken pattern is caught, and the
correct way of writing the same thing is left alone. A check that fires on good
SQL is as much a bug as one that misses bad SQL.
"""
import pytest

from app.dialect_guide import GUIDES
from app.schema_parser import DIALECTS, parse_ddl
from app.sql_checks import check_logic, dialect_issues
from tests.streak_sql import longest_streak_sql, month_number_roundtrip_sql

DDL = """
CREATE TABLE customers (customer_id INT PRIMARY KEY, name VARCHAR(50), city VARCHAR(30), manager_id INT);
CREATE TABLE orders (
    order_id INT PRIMARY KEY,
    customer_id INT REFERENCES customers(customer_id),
    order_date DATE,
    amount DECIMAL(10, 2),
    quantity INT,
    status VARCHAR(20)
);
CREATE TABLE products (product_id INT PRIMARY KEY, name VARCHAR(50), price DECIMAL(10, 2), stock INT);
"""


def schema(dialect="postgres"):
    return parse_ddl(DDL, dialect)


def issues(sql, dialect="postgres", with_schema=True):
    return check_logic(sql, schema(dialect) if with_schema else None, dialect)


def error_codes(sql, dialect="postgres", with_schema=True):
    return {i.code for i in issues(sql, dialect, with_schema) if i.is_error}


def assert_clean(sql, dialect="postgres"):
    found = [(i.code, i.message) for i in issues(sql, dialect) if i.is_error]
    assert not found, found


# ------------------------------------------------------------------ NULL (Test G)


class TestNullComparison:
    @pytest.mark.parametrize("where", [
        "manager_id = NULL",
        "manager_id <> NULL",
        "manager_id != NULL",
        "NULL = manager_id",
        "manager_id > NULL",
    ])
    def test_comparing_to_null_with_an_operator_is_an_error(self, where):
        assert "null_comparison" in error_codes(f"SELECT name FROM customers WHERE {where}")

    def test_the_message_says_what_to_write_instead(self):
        message = issues("SELECT name FROM customers WHERE manager_id = NULL")[0].message
        assert "manager_id IS NULL" in message
        message = issues("SELECT name FROM customers WHERE manager_id <> NULL")[0].message
        assert "IS NOT NULL" in message

    @pytest.mark.parametrize("where", ["manager_id IS NULL", "manager_id IS NOT NULL", "NOT (manager_id IS NULL)"])
    def test_is_null_is_fine(self, where):
        assert_clean(f"SELECT name FROM customers WHERE {where}")

    def test_it_is_found_inside_case_and_join_conditions_too(self):
        assert "null_comparison" in error_codes(
            "SELECT CASE WHEN manager_id = NULL THEN 'top' ELSE 'staff' END AS level FROM customers"
        )
        assert "null_comparison" in error_codes(
            "SELECT c.name FROM customers c JOIN orders o ON o.customer_id = c.customer_id AND c.manager_id = NULL"
        )

    @pytest.mark.parametrize("dialect", sorted(DIALECTS))
    def test_every_dialect(self, dialect):
        assert "null_comparison" in error_codes("SELECT name FROM customers WHERE manager_id = NULL", dialect)


# ------------------------------------------------------------------ division (Test H)


class TestDivision:
    @pytest.mark.parametrize("sql", [
        "SELECT amount / quantity FROM orders",
        "SELECT SUM(amount) / COUNT(*) FROM orders",
        "SELECT 100.0 * SUM(amount) / SUM(quantity) AS pct FROM orders",
        "SELECT COUNT(CASE WHEN status = 'done' THEN 1 END) * 100.0 / COUNT(*) AS pct FROM orders",
        "SELECT city, SUM(amount) / MAX(quantity) FROM orders o JOIN customers c ON c.customer_id = o.customer_id GROUP BY city",
    ])
    def test_unguarded_division_by_a_column_or_aggregate_is_an_error(self, sql):
        assert "division_by_zero" in error_codes(sql)

    def test_the_message_suggests_nullif(self):
        message = issues("SELECT amount / quantity FROM orders")[0].message
        assert "NULLIF(quantity, 0)" in message

    @pytest.mark.parametrize("sql", [
        "SELECT amount / NULLIF(quantity, 0) FROM orders",
        "SELECT 100.0 * SUM(amount) / NULLIF(SUM(quantity), 0) AS pct FROM orders",
        "SELECT CASE WHEN quantity = 0 THEN NULL ELSE amount / quantity END FROM orders",
        "SELECT CASE WHEN quantity <> 0 THEN amount / quantity END FROM orders",
        "SELECT amount / quantity FROM orders WHERE quantity > 0",
        "SELECT amount / quantity FROM orders WHERE quantity <> 0",
        "SELECT amount / 100 FROM orders",
        "SELECT amount / 12.0 FROM orders",
        "SELECT amount / (2 * 3) FROM orders",
        "SELECT status, SUM(amount) / COUNT(*) FROM orders GROUP BY status",
    ])
    def test_guarded_or_constant_denominators_are_fine(self, sql):
        assert "division_by_zero" not in error_codes(sql)

    def test_dividing_by_a_literal_zero_is_an_error(self):
        assert "division_by_zero" in error_codes("SELECT amount / 0 FROM orders")

    def test_bigquery_safe_divide_is_fine(self):
        assert "division_by_zero" not in error_codes("SELECT SAFE_DIVIDE(amount, quantity) FROM orders", "bigquery")

    def test_modulo_by_a_column_is_also_checked(self):
        assert "division_by_zero" in error_codes("SELECT order_id % quantity FROM orders")


# ------------------------------------------------------------------ dates (Tests A/B)


class TestDateLiterals:
    @pytest.mark.parametrize("literal", ["2025-00-01", "2025-13-01", "2025-02-30", "2025-04-31", "2023-02-29", "2025-00"])
    def test_impossible_dates_are_errors(self, literal):
        assert "invalid_date" in error_codes(f"SELECT * FROM orders WHERE order_date >= '{literal}'")

    @pytest.mark.parametrize("literal", ["2025-01-01", "2024-02-29", "2025-12-31", "2025-03", "2025-02-28 10:30:00"])
    def test_real_dates_are_fine(self, literal):
        assert "invalid_date" not in error_codes(f"SELECT * FROM orders WHERE order_date >= '{literal}'")

    def test_leap_years_are_respected(self):
        assert "invalid_date" not in error_codes("SELECT * FROM orders WHERE order_date = '2024-02-29'")
        assert "invalid_date" in error_codes("SELECT * FROM orders WHERE order_date = '2100-02-29'")

    def test_codes_that_look_like_year_month_are_not_dates(self):
        assert "invalid_date" not in error_codes("SELECT * FROM products WHERE name = '1234-56'")

    def test_date_constructors_with_impossible_parts_are_errors(self):
        assert "invalid_date" in error_codes("SELECT DATEFROMPARTS(2025, 13, 1)", "tsql")
        assert "invalid_date" in error_codes("SELECT DATEFROMPARTS(2025, 0, 1)", "tsql")
        assert "invalid_date" in error_codes("SELECT DATEFROMPARTS(2025, 5, 40)", "tsql")
        assert "invalid_date" not in error_codes("SELECT DATEFROMPARTS(2025, 12, 31)", "tsql")


class TestDateConstruction:
    def test_a_month_computed_with_arithmetic_is_an_error(self):
        sql = "SELECT DATEFROMPARTS(2025, (month_num - 1) % 12 + 1, 1) FROM (SELECT 5 AS month_num) t"
        assert "date_from_arithmetic" in error_codes(sql, "tsql")

    def test_native_parts_are_fine(self):
        assert_clean("SELECT DATEFROMPARTS(YEAR(order_date), MONTH(order_date), 1) FROM orders", "tsql")

    def test_a_date_assembled_from_text_is_flagged(self):
        issue = next(i for i in issues("SELECT CAST(CONCAT(2025, '-', 3, '-01') AS DATE) FROM orders", "mysql") if i.code == "date_from_text")
        assert issue.severity == "warning"

    def test_a_date_assembled_from_text_with_arithmetic_is_an_error(self):
        sql = "SELECT CAST(CONCAT(CAST(n / 12 AS CHAR), '-', CAST(n % 12 AS CHAR), '-01') AS DATE) FROM (SELECT 5 AS n) t"
        assert "date_from_text" in error_codes(sql, "mysql")


class TestMonthNumberRoundTrip:
    """The reported bug: months encoded as year*12+month, then decoded with arithmetic."""

    @pytest.mark.parametrize("dialect", ["mysql", "postgres", "sqlite"])
    def test_encoding_then_decoding_is_an_error(self, dialect):
        assert "month_index_roundtrip" in error_codes(month_number_roundtrip_sql(dialect), dialect)

    def test_the_exact_pattern_from_the_report(self):
        sql = """SELECT customer_id,
          FLOOR((start_num - 1) / 12) AS yr, ((start_num - 1) % 12) + 1 AS mo
        FROM (SELECT customer_id, MIN(YEAR(order_date) * 12 + MONTH(order_date)) AS start_num
              FROM orders GROUP BY customer_id) t"""
        assert "month_index_roundtrip" in error_codes(sql, "mysql")

    def test_the_message_points_to_native_date_functions(self):
        message = next(i.message for i in issues(month_number_roundtrip_sql("mysql"), "mysql") if i.code == "month_index_roundtrip")
        assert "native" in message or "DATE_TRUNC" in message
        assert "month 00" in message

    def test_encoding_alone_is_allowed(self):
        """year*12+month is a fine way to group; the bug is decoding it back."""
        sql = """SELECT customer_id, YEAR(order_date) * 12 + MONTH(order_date) AS month_num
                 FROM orders GROUP BY customer_id, YEAR(order_date) * 12 + MONTH(order_date)"""
        assert "month_index_roundtrip" not in error_codes(sql, "mysql")

    def test_dividing_by_twelve_without_a_month_encoding_is_fine(self):
        assert "month_index_roundtrip" not in error_codes("SELECT amount / 12 AS monthly FROM orders")

    def test_yyyymm_integers_break_at_year_boundaries(self):
        sql = """SELECT customer_id, ym - ROW_NUMBER() OVER (PARTITION BY customer_id ORDER BY ym) AS grp
                 FROM (SELECT DISTINCT customer_id, YEAR(order_date) * 100 + MONTH(order_date) AS ym FROM orders) t"""
        assert "yyyymm_sequence" in error_codes(sql, "mysql")

    def test_yyyymm_as_a_plain_label_is_fine(self):
        sql = "SELECT YEAR(order_date) * 100 + MONTH(order_date) AS ym, COUNT(*) FROM orders GROUP BY 1"
        assert "yyyymm_sequence" not in error_codes(sql, "mysql")


class TestReferenceStreakQueryIsClean:
    """The recipe the prompt teaches must itself pass every check, in every dialect."""

    @pytest.mark.parametrize("dialect", sorted(DIALECTS))
    def test_reference_query_has_no_errors(self, dialect):
        assert_clean(longest_streak_sql(dialect), dialect)

    @pytest.mark.parametrize("dialect", sorted(DIALECTS))
    def test_reference_query_has_no_warnings_either(self, dialect):
        assert issues(longest_streak_sql(dialect), dialect) == []


class TestDateArithmetic:
    @pytest.mark.parametrize("dialect", ["mysql", "sqlite", "tsql", "bigquery"])
    def test_adding_a_number_to_a_date_is_an_error_where_it_does_not_mean_days(self, dialect):
        assert "date_arithmetic" in error_codes("SELECT order_date + 30 FROM orders", dialect)

    @pytest.mark.parametrize("dialect", ["postgres", "oracle", "snowflake"])
    def test_it_is_fine_where_it_does(self, dialect):
        assert "date_arithmetic" not in error_codes("SELECT order_date + 30 FROM orders", dialect)

    @pytest.mark.parametrize("dialect", ["mysql", "bigquery"])
    def test_subtracting_dates_with_a_minus_is_an_error(self, dialect):
        assert "date_arithmetic" in error_codes("SELECT CURRENT_DATE - order_date FROM orders", dialect)

    def test_interval_arithmetic_is_fine(self):
        assert "date_arithmetic" not in error_codes("SELECT DATE_ADD(order_date, INTERVAL 30 DAY) FROM orders", "mysql")

    def test_plain_number_arithmetic_is_fine(self):
        assert "date_arithmetic" not in error_codes("SELECT amount + 30 FROM orders", "mysql")


# ------------------------------------------------------------------ dialect syntax


class TestDialectSyntax:
    @pytest.mark.parametrize("dialect,sql", [
        ("mysql", "SELECT DATE_TRUNC('month', order_date) FROM orders"),
        ("mysql", "SELECT name FROM customers WHERE name ILIKE 'a%'"),
        ("mysql", "SELECT order_date::date FROM orders"),
        ("mysql", "SELECT TOP 5 name FROM customers"),
        ("mysql", "SELECT DATE_ADD(order_date, INTERVAL '1 month') FROM orders"),
        ("postgres", "SELECT YEAR(order_date) FROM orders"),
        ("postgres", "SELECT DATE_FORMAT(order_date, '%Y-%m') FROM orders"),
        ("postgres", "SELECT IFNULL(amount, 0) FROM orders"),
        ("postgres", "SELECT order_date + INTERVAL 1 MONTH FROM orders"),
        ("sqlite", "SELECT DATE_TRUNC('month', order_date) FROM orders"),
        ("sqlite", "SELECT EXTRACT(YEAR FROM order_date) FROM orders"),
        ("sqlite", "SELECT NOW()"),
        ("tsql", "SELECT NOW()"),
        ("tsql", "SELECT EXTRACT(YEAR FROM order_date) FROM orders"),
        ("tsql", "SELECT SUBSTR(name, 1, 2) FROM customers"),
        ("tsql", "SELECT name FROM customers WHERE name IS NOT NULL AND TRUE"),
        ("oracle", "SELECT TOP 5 name FROM customers"),
        ("oracle", "SELECT name FROM customers AS c"),
        ("oracle", "SELECT NOW() FROM dual"),
        ("bigquery", "SELECT YEAR(order_date) FROM orders"),
        ("bigquery", "SELECT DATE_TRUNC('month', order_date) FROM orders"),
        ("snowflake", "SELECT GROUP_CONCAT(name) FROM customers"),
    ])
    def test_foreign_syntax_is_an_error(self, dialect, sql):
        assert any(i.code == "dialect_syntax" and i.is_error for i in dialect_issues(sql, dialect)), sql

    @pytest.mark.parametrize("dialect,sql", [
        ("mysql", "SELECT DATE_FORMAT(order_date, '%Y-%m-01') FROM orders"),
        ("mysql", "SELECT YEAR(order_date), MONTH(order_date) FROM orders"),
        ("mysql", "SELECT DATE_SUB(order_date, INTERVAL 1 MONTH) FROM orders"),
        ("postgres", "SELECT DATE_TRUNC('month', order_date) FROM orders"),
        ("postgres", "SELECT order_date + INTERVAL '1 month' FROM orders"),
        ("postgres", "SELECT EXTRACT(YEAR FROM order_date)::int FROM orders"),
        ("sqlite", "SELECT strftime('%Y-%m', order_date) FROM orders"),
        ("sqlite", "SELECT date(order_date, 'start of month') FROM orders"),
        ("tsql", "SELECT TOP 5 name FROM customers"),
        ("tsql", "SELECT DATEADD(month, 1, order_date) FROM orders"),
        ("tsql", "SELECT YEAR(order_date) FROM orders"),
        ("oracle", "SELECT TRUNC(order_date, 'MM') FROM orders"),
        ("oracle", "SELECT name FROM customers c"),
        ("bigquery", "SELECT DATE_TRUNC(order_date, MONTH) FROM orders"),
        ("bigquery", "SELECT EXTRACT(YEAR FROM order_date) FROM orders"),
        ("snowflake", "SELECT DATE_TRUNC('month', order_date) FROM orders"),
        ("snowflake", "SELECT name FROM customers WHERE name ILIKE 'a%'"),
    ])
    def test_native_syntax_is_fine(self, dialect, sql):
        assert dialect_issues(sql, dialect) == [], sql

    def test_keywords_inside_strings_and_comments_do_not_count(self):
        sql = "SELECT 'DATE_TRUNC(x) ILIKE' AS note -- uses ILIKE and ::int in a comment\nFROM customers"
        assert "dialect_syntax" not in error_codes(sql, "mysql")

    def test_the_message_names_the_dialect_and_the_alternative(self):
        message = dialect_issues("SELECT DATE_TRUNC('month', order_date) FROM orders", "mysql")[0].message
        assert "MySQL" in message and "DATE_FORMAT" in message

    @pytest.mark.parametrize("dialect", sorted(DIALECTS))
    def test_each_dialects_own_recipes_are_never_flagged_by_its_own_rules(self, dialect):
        guide = GUIDES[dialect]
        for template in (guide.month("order_date"), guide.back_months("order_date", "2")):
            assert dialect_issues(f"SELECT {template} FROM orders", dialect) == [], template


# ------------------------------------------------------------------ aliases


class TestAliasScope:
    @pytest.mark.parametrize("dialect", ["postgres", "mysql", "tsql", "oracle", "bigquery"])
    def test_an_alias_in_where_is_an_error(self, dialect):
        sql = "SELECT amount * 2 AS doubled FROM orders WHERE doubled > 10"
        assert "alias_scope" in error_codes(sql, dialect)

    @pytest.mark.parametrize("dialect", ["sqlite", "snowflake"])
    def test_where_aliases_are_allowed_in_sqlite_and_snowflake(self, dialect):
        assert "alias_scope" not in error_codes("SELECT amount * 2 AS doubled FROM orders WHERE doubled > 10", dialect)

    def test_an_alias_in_having_depends_on_the_dialect(self):
        sql = "SELECT status, SUM(amount) AS total FROM orders GROUP BY status HAVING total > 10"
        assert "alias_scope" in error_codes(sql, "postgres")
        assert "alias_scope" in error_codes(sql, "tsql")
        assert "alias_scope" not in error_codes(sql, "mysql")

    def test_an_alias_in_group_by_depends_on_the_dialect(self):
        sql = "SELECT UPPER(status) AS s, COUNT(*) FROM orders GROUP BY s"
        assert "alias_scope" in error_codes(sql, "tsql")
        assert "alias_scope" not in error_codes(sql, "postgres")

    def test_order_by_may_always_use_an_alias(self):
        for dialect in sorted(DIALECTS):
            assert "alias_scope" not in error_codes(
                "SELECT status, SUM(amount) AS total FROM orders GROUP BY status ORDER BY total", dialect
            )

    def test_an_alias_that_matches_a_real_column_resolves_to_the_column(self):
        assert "alias_scope" not in error_codes("SELECT amount * 2 AS amount FROM orders WHERE amount > 10")

    def test_one_select_column_cannot_use_another_aliased_one(self):
        sql = "SELECT amount * 2 AS doubled, doubled + 1 AS more FROM orders"
        assert "alias_scope" in error_codes(sql, "postgres")
        assert "alias_scope" not in error_codes(sql, "snowflake")

    def test_using_the_alias_from_an_outer_query_is_correct(self):
        sql = "SELECT * FROM (SELECT amount * 2 AS doubled FROM orders) t WHERE doubled > 10"
        assert_clean(sql)

    def test_cte_columns_count_as_real_columns(self):
        sql = "WITH t AS (SELECT amount AS total FROM orders) SELECT total AS total FROM t WHERE total > 5"
        assert "alias_scope" not in error_codes(sql)


# ------------------------------------------------------------------ grouping and aggregates


class TestGroupBy:
    @pytest.mark.parametrize("sql", [
        "SELECT status, amount, COUNT(*) FROM orders GROUP BY status",
        "SELECT status, COUNT(*) FROM orders",
        "SELECT status, MAX(amount) FROM orders GROUP BY status HAVING quantity > 2",
        "SELECT customer_id, SUM(amount) FROM orders GROUP BY customer_id ORDER BY order_date",
        "SELECT status, amount + 1, COUNT(*) FROM orders GROUP BY status",
    ])
    def test_ungrouped_columns_are_errors(self, sql):
        assert "group_by" in error_codes(sql)

    @pytest.mark.parametrize("sql", [
        "SELECT status, COUNT(*) FROM orders GROUP BY status",
        "SELECT status, SUM(amount) AS total FROM orders GROUP BY status ORDER BY total DESC",
        "SELECT status, SUM(amount) FROM orders GROUP BY 1 HAVING SUM(amount) > 10 ORDER BY 2",
        "SELECT UPPER(status), COUNT(*) FROM orders GROUP BY UPPER(status)",
        "SELECT status, COUNT(*) FROM orders GROUP BY status HAVING COUNT(*) > 1",
        "SELECT o.customer_id, o.amount - AVG(o.amount) OVER (PARTITION BY o.customer_id) AS diff FROM orders o",
        "SELECT COUNT(*), SUM(amount) FROM orders",
        "SELECT DISTINCT status FROM orders",
    ])
    def test_properly_grouped_queries_are_fine(self, sql):
        assert "group_by" not in error_codes(sql)

    def test_columns_depending_on_a_grouped_primary_key_are_fine(self):
        sql = """SELECT c.customer_id, c.name, c.city, COUNT(*) AS orders
                 FROM customers c JOIN orders o ON o.customer_id = c.customer_id
                 GROUP BY c.customer_id"""
        assert "group_by" not in error_codes(sql)

    def test_columns_not_depending_on_the_grouped_key_are_errors(self):
        sql = """SELECT c.name, o.status, COUNT(*) AS n
                 FROM customers c JOIN orders o ON o.customer_id = c.customer_id
                 GROUP BY c.customer_id"""
        assert "group_by" in error_codes(sql)

    def test_a_correlated_subquery_reference_is_not_ungrouped(self):
        sql = """SELECT c.customer_id,
                        (SELECT COUNT(*) FROM orders o WHERE o.customer_id = c.customer_id) AS n
                 FROM customers c"""
        assert "group_by" not in error_codes(sql)

    def test_window_partition_columns_must_be_grouped_too(self):
        sql = "SELECT status, SUM(SUM(amount)) OVER (PARTITION BY city) FROM orders o JOIN customers c ON c.customer_id = o.customer_id GROUP BY status"
        assert "group_by" in error_codes(sql)


class TestAggregates:
    def test_an_aggregate_in_where_is_an_error(self):
        assert "aggregate_in_where" in error_codes("SELECT status FROM orders WHERE COUNT(*) > 1")

    def test_the_same_condition_in_having_is_fine(self):
        assert "aggregate_in_where" not in error_codes("SELECT status FROM orders GROUP BY status HAVING COUNT(*) > 1")

    def test_an_aggregate_in_a_subquery_inside_where_is_fine(self):
        sql = "SELECT * FROM orders WHERE amount > (SELECT AVG(amount) FROM orders)"
        assert "aggregate_in_where" not in error_codes(sql)

    def test_nested_aggregates_are_an_error(self):
        assert "nested_aggregate" in error_codes("SELECT AVG(COUNT(*)) FROM orders GROUP BY status")

    def test_a_windowed_aggregate_over_an_aggregate_is_fine(self):
        sql = "SELECT status, SUM(COUNT(*)) OVER () FROM orders GROUP BY status"
        assert "nested_aggregate" not in error_codes(sql)


class TestWindowFunctions:
    @pytest.mark.parametrize("clause", [
        "WHERE ROW_NUMBER() OVER (ORDER BY amount) = 1",
        "GROUP BY ROW_NUMBER() OVER (ORDER BY amount)",
    ])
    def test_a_window_function_in_where_or_group_by_is_an_error(self, clause):
        assert "window_in_clause" in error_codes(f"SELECT status FROM orders {clause}")

    def test_a_window_function_in_having_is_an_error(self):
        sql = "SELECT status FROM orders GROUP BY status HAVING RANK() OVER (ORDER BY COUNT(*)) = 1"
        assert "window_in_clause" in error_codes(sql)

    def test_filtering_on_a_window_result_in_an_outer_query_is_fine(self):
        sql = """SELECT * FROM (SELECT order_id, ROW_NUMBER() OVER (PARTITION BY customer_id ORDER BY order_date) AS rn FROM orders) t
                 WHERE rn = 1"""
        assert_clean(sql)

    def test_a_window_function_inside_an_aggregate_is_an_error(self):
        assert "window_in_aggregate" in error_codes("SELECT SUM(ROW_NUMBER() OVER (ORDER BY amount)) FROM orders")

    @pytest.mark.parametrize("function", ["ROW_NUMBER()", "RANK()", "DENSE_RANK()", "LAG(amount)", "LEAD(amount)", "NTILE(4)"])
    def test_order_dependent_functions_need_an_order_by(self, function):
        assert "window_without_order" in error_codes(f"SELECT {function} OVER (PARTITION BY customer_id) FROM orders")

    def test_with_an_order_by_they_are_fine(self):
        assert "window_without_order" not in error_codes(
            "SELECT ROW_NUMBER() OVER (PARTITION BY customer_id ORDER BY order_date) FROM orders"
        )

    def test_aggregates_over_a_window_need_no_order(self):
        assert "window_without_order" not in error_codes("SELECT SUM(amount) OVER (PARTITION BY customer_id) FROM orders")


class TestJoins:
    def test_a_join_without_a_condition_is_an_error(self):
        assert "join_without_condition" in error_codes("SELECT * FROM orders o JOIN customers c")

    def test_an_explicit_cross_join_is_fine(self):
        assert "join_without_condition" not in error_codes("SELECT * FROM orders o CROSS JOIN customers c")

    def test_a_join_on_columns_the_schema_does_not_relate_is_a_warning(self):
        found = issues("SELECT * FROM orders o JOIN customers c ON o.order_id = c.customer_id")
        assert any(i.code == "join_mismatch" and not i.is_error for i in found)

    def test_a_join_along_the_foreign_key_is_fine(self):
        assert issues("SELECT * FROM orders o JOIN customers c ON o.customer_id = c.customer_id") == []

    def test_unrelated_tables_are_not_second_guessed(self):
        assert "join_mismatch" not in {i.code for i in issues("SELECT * FROM orders o JOIN products p ON o.quantity = p.stock")}


# ------------------------------------------------------------------ consecutive periods need de-duplication (Test F)


class TestStreakWithoutDedupe:
    def test_numbering_raw_rows_then_using_the_number_as_a_date_offset_is_an_error(self):
        from tests.streak_sql import naive_row_number_sql

        assert "streak_without_dedupe" in error_codes(naive_row_number_sql(), "sqlite")

    def test_deduplicating_first_makes_it_fine(self):
        assert "streak_without_dedupe" not in error_codes(longest_streak_sql("sqlite"), "sqlite")

    def test_ranking_rows_without_any_gaps_logic_is_fine(self):
        sql = "SELECT order_id, ROW_NUMBER() OVER (PARTITION BY customer_id ORDER BY order_date) AS rn FROM orders"
        assert "streak_without_dedupe" not in error_codes(sql)


# ------------------------------------------------------------------ general behaviour


class TestGeneral:
    def test_dialect_advice_works_on_sql_that_does_not_parse(self):
        assert dialect_issues("SELECT TOP 5 name FROM customers", "mysql")[0].message.endswith("use LIMIT.")

    def test_unparseable_sql_returns_nothing_because_the_parser_reports_it(self):
        assert check_logic("SELEC nonsense (", schema(), "postgres") == []

    def test_errors_are_listed_before_warnings(self):
        found = issues("SELECT * FROM orders o JOIN customers c ON o.order_id = c.customer_id WHERE manager_id = NULL")
        severities = [i.is_error for i in found]
        assert severities == sorted(severities, reverse=True)

    def test_identical_problems_are_reported_once(self):
        found = issues("SELECT name FROM customers WHERE manager_id = NULL OR manager_id = NULL")
        assert len([i for i in found if i.code == "null_comparison"]) == 1

    def test_works_without_a_schema(self):
        assert "null_comparison" in error_codes("SELECT name FROM customers WHERE manager_id = NULL", with_schema=False)
        assert "division_by_zero" in error_codes("SELECT a / b FROM t", with_schema=False)

    def test_a_clean_everyday_query_has_no_issues(self):
        sql = """SELECT c.city, COUNT(*) AS orders, ROUND(100.0 * SUM(o.amount) / NULLIF(COUNT(*), 0), 2) AS avg_value
                 FROM customers c
                 JOIN orders o ON o.customer_id = c.customer_id
                 WHERE o.status = 'completed' AND o.order_date >= '2025-01-01'
                 GROUP BY c.city
                 HAVING COUNT(*) > 1
                 ORDER BY orders DESC
                 LIMIT 5"""
        assert issues(sql) == []
