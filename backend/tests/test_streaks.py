"""Consecutive-month scenarios, checked against results rather than syntax.

Each customer below is one scenario. The reference query (built from the same
dialect templates the model is prompted with) is executed against real rows in
SQLite and the answer is compared with what a person would work out by hand.
The broken patterns the validator exists for are run on the same data to show
they really are wrong, and that the checks catch them.
"""
import sqlite3

import pytest

from app.dialect_guide import GUIDES
from app.schema_parser import DIALECTS, parse_ddl
from app.sql_checks import check_logic
from app.sql_execution import check_result_values, run_on_connection, verify_by_execution
from tests.streak_sql import longest_streak_sql, month_number_roundtrip_sql, naive_row_number_sql

SCENARIOS = {
    # customer: (order dates, expected (first_month, last_month, consecutive_months))
    1: (["2025-01-15", "2025-02-10", "2025-03-20"], ("2025-01-01", "2025-03-01", 3)),  # A: Jan, Feb, Mar
    3: (["2025-01-05", "2025-02-17", "2025-04-02"], ("2025-01-01", "2025-02-01", 2)),  # C: a gap breaks the run
    4: (  # D: two runs, the longer one wins
        ["2025-01-10", "2025-02-10", "2025-03-10", "2025-06-10", "2025-07-10", "2025-08-10", "2025-09-10"],
        ("2025-06-01", "2025-09-01", 4),
    ),
    5: (  # E: equal runs, the earliest wins
        ["2025-01-10", "2025-02-10", "2025-03-10", "2025-06-10", "2025-07-10", "2025-08-10"],
        ("2025-01-01", "2025-03-01", 3),
    ),
    6: (  # F: ten January orders are still one month
        ["2025-01-02", "2025-01-03", "2025-01-05", "2025-01-09", "2025-01-12", "2025-01-15", "2025-01-20",
         "2025-01-22", "2025-01-28", "2025-01-31", "2025-02-14", "2025-03-14"],
        ("2025-01-01", "2025-03-01", 3),
    ),
    7: (["2025-11-30", "2025-12-31", "2026-01-01"], ("2025-11-01", "2026-01-01", 3)),  # runs across a year end
    8: (["2024-01-31", "2024-02-29", "2024-03-31"], ("2024-01-01", "2024-03-01", 3)),  # leap year, month-end dates
    9: (["2025-05-05"], ("2025-05-01", "2025-05-01", 1)),  # a single month
    10: (["2025-12-24", "2026-01-03"], ("2025-12-01", "2026-01-01", 2)),  # a run that STARTS in December
    12: (  # duplicates in the MIDDLE month: Jan, Feb x3, Mar
        ["2025-01-10", "2025-02-03", "2025-02-12", "2025-02-20", "2025-03-09"],
        ("2025-01-01", "2025-03-01", 3),
    ),
    11: (  # the same month in different years is not consecutive
        ["2024-12-01", "2025-12-01"],
        ("2024-12-01", "2024-12-01", 1),
    ),
}


@pytest.fixture
def conn():
    connection = sqlite3.connect(":memory:")
    connection.execute("CREATE TABLE orders (order_id INTEGER PRIMARY KEY, customer_id INTEGER, order_date TEXT)")
    order_id = 0
    for customer, (dates, _) in SCENARIOS.items():
        for day in dates:
            order_id += 1
            connection.execute("INSERT INTO orders VALUES (?, ?, ?)", (order_id, customer, day))
    connection.commit()
    yield connection
    connection.close()


def streaks(connection, sql=None) -> dict[int, tuple]:
    rows = connection.execute(sql or longest_streak_sql("sqlite")).fetchall()
    return {row[0]: tuple(row[1:]) for row in rows}


class TestLongestStreak:
    def test_a_consecutive_months(self, conn):
        assert streaks(conn)[1] == ("2025-01-01", "2025-03-01", 3)

    def test_b_january_never_produces_month_zero(self, conn):
        """Reported bug: the arithmetic decode produced 2025-00-01."""
        result = streaks(conn)
        flat = [str(value) for row in result.values() for value in row]
        assert not any(value.endswith("-00") or "-00-" in value for value in flat)
        assert check_result_values(["customer_id", "first_month", "last_month", "consecutive_months"], [(k, *v) for k, v in result.items()]) == []
        assert result[1][0] == "2025-01-01"

    def test_c_a_missing_month_breaks_the_streak(self, conn):
        first, last, length = streaks(conn)[3]
        assert length == 2, "January, February, April must not count as three consecutive months"
        assert (first, last) == ("2025-01-01", "2025-02-01")

    def test_d_the_longest_of_several_streaks_wins(self, conn):
        assert streaks(conn)[4] == ("2025-06-01", "2025-09-01", 4)

    def test_e_equal_streaks_go_to_the_earliest(self, conn):
        assert streaks(conn)[5] == ("2025-01-01", "2025-03-01", 3)

    def test_f_duplicate_orders_in_a_month_count_once(self, conn):
        assert streaks(conn)[6] == ("2025-01-01", "2025-03-01", 3)

    def test_a_run_crossing_a_year_end(self, conn):
        assert streaks(conn)[7] == ("2025-11-01", "2026-01-01", 3)

    def test_a_run_starting_in_december(self, conn):
        assert streaks(conn)[10] == ("2025-12-01", "2026-01-01", 2)

    def test_leap_year_and_month_end_dates(self, conn):
        assert streaks(conn)[8] == ("2024-01-01", "2024-03-01", 3)

    def test_the_same_month_in_different_years_is_not_a_run(self, conn):
        assert streaks(conn)[11][2] == 1

    def test_a_single_month_is_a_run_of_one(self, conn):
        assert streaks(conn)[9] == ("2025-05-01", "2025-05-01", 1)

    @pytest.mark.parametrize("customer", sorted(SCENARIOS))
    def test_every_scenario_matches_the_hand_worked_answer(self, conn, customer):
        assert streaks(conn)[customer] == SCENARIOS[customer][1]


class TestBrokenPatternsReallyAreWrong:
    """The bad patterns, run on the same data, give wrong answers. That is why the checks exist."""

    def test_numbering_raw_rows_gets_duplicates_in_a_middle_month_wrong(self, conn):
        rows = conn.execute(naive_row_number_sql()).fetchall()
        lengths = [row[3] for row in rows if row[0] == 12]
        assert max(lengths) < 3, "Feb x3 shifts the numbering, so Jan-Feb-Mar is no longer seen as one run"

    def test_and_the_validator_flags_it_before_it_runs(self):
        schema = parse_ddl("CREATE TABLE orders (order_id INT PRIMARY KEY, customer_id INT, order_date DATE);", "sqlite")
        assert "streak_without_dedupe" in {i.code for i in check_logic(naive_row_number_sql(), schema, "sqlite")}

    def test_decoding_a_month_number_produces_month_zero(self, conn):
        rows = conn.execute(month_number_roundtrip_sql("sqlite")).fetchall()
        by_customer = {row[0]: row for row in rows}
        # Customer 10's run starts in December: 2025*12 + 12 = 24312; 24312 % 12 is 0.
        assert by_customer[10][3] == "2026-00-01"

    def test_the_result_check_catches_that_invalid_date(self, conn):
        result = run_on_connection(conn, month_number_roundtrip_sql("sqlite"), "sqlite")
        assert result.ran
        assert any(i.code == "invalid_date_output" and "2026-00-01" in i.message for i in result.issues)

    def test_and_the_static_check_catches_it_without_running_anything(self):
        schema = parse_ddl("CREATE TABLE orders (order_id INT PRIMARY KEY, customer_id INT, order_date DATE);", "sqlite")
        codes = {i.code for i in check_logic(month_number_roundtrip_sql("sqlite"), schema, "sqlite")}
        assert "month_index_roundtrip" in codes


class TestTrialRunIsASecondLayer:
    """If a variation slips past the pattern rule, running the query on test data still catches it."""

    DODGES_THE_PATTERN = """WITH m AS (
        SELECT customer_id, CAST(strftime('%Y', order_date) AS INTEGER) * 12 + CAST(strftime('%m', order_date) AS INTEGER) AS n
        FROM orders GROUP BY customer_id, 2
    )
    SELECT customer_id, (n / (3 * 4)) || '-' || printf('%02d', n % (3 * 4)) || '-01' AS first_month FROM m"""

    SCHEMA = "CREATE TABLE orders (order_id INT PRIMARY KEY, customer_id INT, order_date DATE);"

    def test_the_static_rule_does_not_see_it(self):
        schema = parse_ddl(self.SCHEMA, "sqlite")
        assert "month_index_roundtrip" not in {i.code for i in check_logic(self.DODGES_THE_PATTERN, schema, "sqlite")}

    def test_the_trial_run_does(self):
        result = verify_by_execution(self.DODGES_THE_PATTERN, parse_ddl(self.SCHEMA, "sqlite"), "sqlite")
        assert any(i.code == "invalid_date_output" for i in result.issues), result.issues


class TestEveryDialectsRecipeIsSound:
    @pytest.mark.parametrize("dialect", sorted(DIALECTS))
    def test_the_reference_query_parses_and_uses_only_its_own_dialects_syntax(self, dialect):
        schema = parse_ddl("CREATE TABLE orders (order_id INT PRIMARY KEY, customer_id INT, order_date DATE);", dialect)
        assert [i for i in check_logic(longest_streak_sql(dialect), schema, dialect) if i.is_error] == []

    @pytest.mark.parametrize("dialect", sorted(DIALECTS))
    def test_the_month_start_template_never_uses_arithmetic_on_numbers(self, dialect):
        template = GUIDES[dialect].month("d")
        assert "% 12" not in template and "* 12" not in template and "/ 12" not in template

    def test_the_sqlite_recipe_is_the_one_the_scenarios_ran(self):
        assert GUIDES["sqlite"].month("order_date") in longest_streak_sql("sqlite")
