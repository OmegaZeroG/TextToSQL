"""Tests for the eval harness's own result-comparison logic and golden dataset
(eval/run_eval.py, eval/sample_db.py, eval/golden_dataset.json).

If the comparison is wrong the eval pass rate is meaningless, so it gets tests
too. None of this needs the network or an LLM.
"""
import importlib.util
import json
import sys
from datetime import date, datetime, timezone
from pathlib import Path

import pytest

from app.guardrails import check_sql
from app.schema_parser import parse_ddl
from app.schema_validation import check_sql_against_schema

EVAL_DIR = Path(__file__).resolve().parents[2] / "eval"
sys.path.insert(0, str(EVAL_DIR))  # run_eval imports sample_db as a sibling module

_spec = importlib.util.spec_from_file_location("run_eval", EVAL_DIR / "run_eval.py")
run_eval = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(run_eval)

from sample_db import SAMPLE_DDL, build_sample_db  # noqa: E402

rows_match = run_eval.rows_match
CASES = json.loads((EVAL_DIR / "golden_dataset.json").read_text(encoding="utf-8"))
ANSWERABLE = [c for c in CASES if c["expected_sql"]]


class TestRowsMatch:
    def test_identical_results_match(self):
        assert rows_match([(61,)], [(61,)])

    def test_column_layout_is_irrelevant(self):
        assert rows_match([("Morgan", 34)], [(34, "Morgan")])

    def test_extra_columns_in_the_generated_query_are_allowed(self):
        assert rows_match([(34, "Morgan", "Nguyen", "m@example.com")], [(34, "Morgan", "Nguyen")])

    def test_row_order_is_irrelevant(self):
        assert rows_match([(2,), (1,)], [(1,), (2,)])

    def test_ints_and_floats_are_equal(self):
        assert rows_match([(12.0,)], [(12,)])

    def test_float_rounding_noise_is_ignored(self):
        assert rows_match([(10565.400000000001,)], [(10565.4,)])

    def test_booleans_match_zero_and_one(self):
        assert rows_match([(True,)], [(1,)])

    def test_null_values_match_each_other(self):
        assert rows_match([(None,)], [(None,)])

    def test_different_values_do_not_match(self):
        assert not rows_match([(62,)], [(61,)])

    def test_different_row_counts_do_not_match(self):
        assert not rows_match([(1,)], [(1,), (2,)])

    def test_duplicate_rows_are_counted_not_collapsed(self):
        assert not rows_match([(1,)], [(1,), (1,)])

    def test_a_row_missing_an_expected_value_does_not_match(self):
        assert not rows_match([("x",)], [("x", "y")])

    def test_empty_results_match_each_other(self):
        assert rows_match([], [])


class TestDateNormalization:
    @pytest.mark.parametrize("actual", ["2024-12", "2024-12-01", "2024-12-01 00:00:00", "2024-12-01T00:00:00Z"])
    def test_the_same_day_in_any_format_matches(self, actual):
        assert rows_match([(actual, 31)], [("2024-12-01", 31)])

    def test_real_date_objects_match_strings(self):
        assert rows_match([("2024-12-01",)], [(date(2024, 12, 1),)])
        assert rows_match([("2024-12-01T00:00:00Z",)], [(datetime(2024, 12, 1, tzinfo=timezone.utc),)])

    def test_a_utc_offset_is_converted_before_comparing(self):
        assert rows_match([("2024-12-01T05:30:00+05:30",)], [("2024-12-01",)])

    def test_fractional_seconds_are_accepted(self):
        assert rows_match([("2024-12-01T00:00:00.5Z",)], [("2024-12-01T00:00:00.5",)])

    def test_a_different_day_does_not_match(self):
        assert not rows_match([("2024-11-01",)], [("2024-12-01",)])

    def test_non_date_strings_are_left_alone(self):
        assert not rows_match([("2024-12 report",)], [("2024-12-01",)])


class TestSampleDatabase:
    def test_is_identical_on_every_build(self):
        first = build_sample_db().execute("SELECT SUM(quantity * unit_price) FROM order_items").fetchone()
        second = build_sample_db().execute("SELECT SUM(quantity * unit_price) FROM order_items").fetchone()
        assert first == second

    def test_the_sample_ddl_parses_as_sqlite(self):
        schema = parse_ddl(SAMPLE_DDL, "sqlite")
        assert {t.name for t in schema.tables} == {"categories", "products", "customers", "orders", "order_items"}

    def test_the_database_is_read_only_once_built(self):
        import sqlite3

        with pytest.raises(sqlite3.OperationalError):
            build_sample_db().execute("DELETE FROM orders")


class TestStreakCustomers:
    """The hand-built customers give the streak question a known answer."""

    @staticmethod
    def streaks():
        case = next(c for c in CASES if c["id"] == "q13")
        return {row[0]: row[1:] for row in build_sample_db().execute(case["expected_sql"]).fetchall()}

    def test_a_run_with_several_orders_in_one_month_counts_that_month_once(self):
        assert self.streaks()[121] == ("2025-01-01", "2025-03-01", 3)

    def test_a_gap_breaks_the_run(self):
        assert 122 not in self.streaks()

    def test_the_longest_run_wins(self):
        assert self.streaks()[123] == ("2025-06-01", "2025-09-01", 4)

    def test_equal_runs_go_to_the_earliest(self):
        assert self.streaks()[124] == ("2025-01-01", "2025-03-01", 3)

    def test_a_run_can_cross_a_year_end(self):
        assert self.streaks()[125] == ("2025-11-01", "2026-01-01", 3)

    def test_the_cancelled_percentage_has_a_real_answer(self):
        case = next(c for c in CASES if c["id"] == "q14")
        (value,), = build_sample_db().execute(case["expected_sql"]).fetchall()
        assert 0 < value < 100


class TestGoldenDataset:
    def test_ids_are_unique_and_difficulties_known(self):
        assert len({c["id"] for c in CASES}) == len(CASES)
        assert {c["difficulty"] for c in CASES} <= {"easy", "medium", "hard", "ambiguous", "unanswerable", "guardrail"}

    def test_every_kind_of_behaviour_is_covered(self):
        assert {"ambiguous", "unanswerable", "guardrail"} <= {c["difficulty"] for c in CASES}

    @pytest.mark.parametrize("case", ANSWERABLE, ids=lambda c: c["id"])
    def test_expected_sql_runs_and_returns_rows(self, case):
        rows = build_sample_db().execute(case["expected_sql"]).fetchall()
        assert rows, f"{case['id']}'s expected SQL returns nothing, so it can't tell right from wrong"

    @pytest.mark.parametrize("case", ANSWERABLE, ids=lambda c: c["id"])
    def test_expected_sql_passes_our_own_checks(self, case):
        """The answer key must itself be something the product would accept."""
        assert check_sql(case["expected_sql"]).allowed
        schema = parse_ddl(SAMPLE_DDL, "sqlite")
        result = check_sql_against_schema(case["expected_sql"], schema, "sqlite")
        assert result.syntax_valid and result.schema_ok, result.problems

    @pytest.mark.parametrize("case", [c for c in CASES if c["difficulty"] == "guardrail"], ids=lambda c: c["id"])
    def test_guardrail_questions_are_write_requests(self, case):
        assert case["expected_sql"] is None
