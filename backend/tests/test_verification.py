"""verify_sql: the post-generation pipeline (syntax -> schema -> logic -> trial run)."""
from app.schema_parser import parse_ddl
from app.verification import verify_sql

DDL = """
CREATE TABLE customers (customer_id INT PRIMARY KEY, name VARCHAR(50), manager_id INT);
CREATE TABLE orders (order_id INT PRIMARY KEY, customer_id INT REFERENCES customers(customer_id), order_date DATE, amount DECIMAL(10, 2), quantity INT);
"""


def verdict(sql, dialect="postgres", with_schema=True):
    return verify_sql(sql, parse_ddl(DDL, dialect) if with_schema else None, dialect)


def test_a_correct_query_is_clean_and_was_trial_run():
    result = verdict("SELECT customer_id, COUNT(*) AS n FROM orders GROUP BY customer_id")
    assert result.clean and result.syntax_valid and result.schema_ok and result.logic_ok
    assert result.errors == [] and result.executed
    assert result.tables_used == ["orders"]


def test_invalid_syntax_stops_everything_else():
    result = verdict("SELEC name FROM customers")
    assert not result.syntax_valid and not result.clean and not result.executed


def test_unparseable_foreign_syntax_comes_with_advice_on_what_to_write():
    result = verdict("SELECT TOP 5 name FROM customers", "mysql")
    assert not result.syntax_valid
    assert any("use LIMIT" in e for e in result.errors)


def test_wrong_dialect_limit_is_a_syntax_error_with_the_fix():
    result = verdict("SELECT name FROM customers LIMIT 5", "tsql")
    assert not result.syntax_valid
    assert any("TOP" in e for e in result.errors)


def test_an_invented_column_is_a_schema_failure_and_is_not_trial_run():
    result = verdict("SELECT phone FROM customers")
    assert result.syntax_valid and not result.schema_ok and not result.executed
    assert any("phone" in e for e in result.errors)


def test_an_invented_table_is_a_schema_failure():
    result = verdict("SELECT * FROM invoices")
    assert not result.schema_ok and any("invoices" in e for e in result.errors)


def test_a_logic_error_fails_the_logic_check_but_not_the_schema_check():
    result = verdict("SELECT name FROM customers WHERE manager_id = NULL")
    assert result.syntax_valid and result.schema_ok and not result.logic_ok
    assert any("IS NULL" in e for e in result.errors)


def test_a_trial_run_failure_counts_as_a_logic_failure():
    result = verdict("SELECT STRFTIME('%Y', order_date) FROM orders", "sqlite")
    assert result.executed is True and result.logic_ok is True
    result = verdict("SELECT YEAR(order_date) FROM orders", "sqlite")
    assert not result.logic_ok and any("YEAR" in e for e in result.errors)


def test_warnings_are_reported_but_do_not_make_the_verdict_unclean():
    result = verdict("SELECT * FROM orders o JOIN customers c ON o.order_id = c.customer_id")
    assert result.clean and result.logic_ok
    assert any("joins" in w for w in result.warnings)


def test_without_a_schema_logic_still_runs_but_nothing_is_trial_run():
    result = verdict("SELECT a / b FROM t WHERE c = NULL", with_schema=False)
    assert not result.logic_ok and not result.executed
    assert len(result.errors) == 2


def test_the_same_problem_is_not_listed_twice():
    result = verdict("SELECT YEAR(order_date) FROM orders", "sqlite")
    assert len(result.errors) == len(set(result.errors))


def test_every_error_is_a_plain_sentence_the_model_can_act_on():
    result = verdict("SELECT amount / quantity FROM orders WHERE amount = NULL")
    assert all(isinstance(e, str) and len(e) > 20 for e in result.errors)
