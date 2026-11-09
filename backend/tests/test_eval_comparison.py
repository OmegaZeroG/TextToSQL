"""Tests for the eval harness's own result-comparison logic (eval/run_eval.py).

If this logic is wrong the eval pass rate is meaningless, so it gets tests too.
Each case below is a real false-negative the first versions of the harness hit.
"""
import importlib.util
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path

import pandas as pd

_spec = importlib.util.spec_from_file_location(
    "run_eval", Path(__file__).resolve().parents[2] / "eval" / "run_eval.py"
)
run_eval = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(run_eval)

rows_match = run_eval.rows_match


def expected(columns, rows):
    return pd.DataFrame(rows, columns=columns)


def test_identical_results_match():
    assert rows_match(["n"], [[61]], expected(["count"], [[61]]))


def test_api_decimal_strings_match_database_decimals():
    """FastAPI serialises Decimal as a JSON string; the eval's own DB query keeps Decimal."""
    assert rows_match(["total"], [["10565.40"]], expected(["total"], [[Decimal("10565.40")]]))


def test_column_aliases_are_irrelevant():
    assert rows_match(["customer_count"], [[61]], expected(["count"], [[61]]))


def test_extra_columns_in_the_generated_query_are_allowed():
    actual_rows = [[34, "Morgan", "Nguyen", "morgan.nguyen34@example.com"]]
    assert rows_match(
        ["customer_id", "first_name", "last_name", "email"],
        actual_rows,
        expected(["customer_id", "first_name", "last_name"], [[34, "Morgan", "Nguyen"]]),
    )


def test_row_order_is_irrelevant():
    assert rows_match(["n"], [[2], [1]], expected(["n"], [[1], [2]]))


def test_timezone_aware_timestamp_matches_a_plain_month_string():
    """date_trunc() returns timestamptz; a TO_CHAR(..., 'YYYY-MM') query returns '2024-12'."""
    month = datetime(2024, 12, 1, tzinfo=timezone.utc)
    assert rows_match(["month", "n"], [["2024-12", 31]], expected(["month", "n"], [[month, 31]]))


def test_null_values_match_each_other():
    assert rows_match(["a"], [[None]], expected(["a"], [[None]]))


def test_different_values_do_not_match():
    assert not rows_match(["n"], [[62]], expected(["n"], [[61]]))


def test_different_row_counts_do_not_match():
    assert not rows_match(["n"], [[1]], expected(["n"], [[1], [2]]))


def test_duplicate_rows_are_counted_not_collapsed():
    assert not rows_match(["n"], [[1]], expected(["n"], [[1], [1]]))


def test_a_row_missing_an_expected_value_does_not_match():
    assert not rows_match(["a"], [["x"]], expected(["a", "b"], [["x", "y"]]))
