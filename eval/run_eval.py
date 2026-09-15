"""Runs the golden dataset against a live API instance and reports:
- execution match (do results match the expected SQL's results, regardless
  of whether the generated SQL is textually identical)
- guardrail effectiveness (are disguised write attempts blocked?)
- ambiguity handling (does the system ask for clarification instead of guessing?)

Usage: python run_eval.py [--api-url http://localhost:8000]
"""
import argparse
import json
import os
import re
import sys
from datetime import date, datetime
from pathlib import Path

import pandas as pd
import requests
from sqlalchemy import create_engine, text

DATASET_PATH = Path(__file__).parent / "golden_dataset.json"
DATABASE_URL = os.getenv(
    "DATABASE_URL", "postgresql+psycopg2://postgres:postgres@localhost:5433/texttosql"
)

# Matches ISO-ish date/timestamp strings (e.g. "2024-12", "2024-12-01",
# "2024-12-01 00:00:00") so they can be normalized against native
# date/datetime/Timestamp objects before comparison.
_DATE_LIKE = re.compile(r"^\d{4}-\d{2}(-\d{2})?([ T]\d{2}:\d{2}(:\d{2})?)?$")


def _normalize(value):
    """Makes execution-match comparison robust to two harmless sources of
    false negatives: (1) the API JSON-encodes Decimal as a string while a
    direct DB query keeps it as Decimal, and (2) two SQL queries can
    represent the same month/day at different granularities/formats
    (e.g. '2024-12' vs a DATE_TRUNC timestamp)."""
    if value is None:
        return None
    if isinstance(value, (datetime, date, pd.Timestamp)):
        ts = pd.Timestamp(value)
        if ts.tzinfo is not None:
            ts = ts.tz_convert("UTC").tz_localize(None)
        return ts.isoformat()
    if isinstance(value, str) and _DATE_LIKE.match(value):
        return pd.Timestamp(value).isoformat()
    return str(value)


def run_expected_sql(sql: str) -> pd.DataFrame:
    engine = create_engine(DATABASE_URL)
    with engine.connect() as conn:
        result = conn.execute(text(sql))
        return pd.DataFrame(result.fetchall(), columns=list(result.keys()))


def rows_match(actual_columns: list[str], actual_rows: list[list], expected_df: pd.DataFrame) -> bool:
    """Column names and order are an arbitrary LLM choice (COUNT(*) might
    come back as "count" or "total_units", and a query might add a
    harmless extra column like `email`) so we don't compare by column
    name or position. Instead: for every expected row, its normalized
    values must be a *subset* of some actual row's normalized values,
    with a 1-to-1 pairing between expected and actual rows (a bijection)
    so row counts and per-row content both have to line up — just not
    the column layout used to get there."""
    del actual_columns  # unused: comparison is value-set based, not column-based
    expected_rows = expected_df.values.tolist()
    if len(actual_rows) != len(expected_rows):
        return False

    actual_sets = [{_normalize(v) for v in row} for row in actual_rows]
    remaining = list(actual_sets)
    for expected_row in expected_rows:
        expected_set = {_normalize(v) for v in expected_row}
        match_idx = next((i for i, actual_set in enumerate(remaining) if expected_set <= actual_set), None)
        if match_idx is None:
            return False
        remaining.pop(match_idx)
    return True


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--api-url", default="http://localhost:8000")
    args = parser.parse_args()

    cases = json.loads(DATASET_PATH.read_text())
    results = []

    for case in cases:
        question = case["question"]
        difficulty = case["difficulty"]
        print(f"\n[{case['id']}] ({difficulty}) {question}")

        try:
            resp = requests.post(f"{args.api_url}/v1/query", json={"question": question}, timeout=60)
        except Exception as exc:
            print(f"  FAIL: request error: {exc}")
            results.append({**case, "passed": False, "reason": str(exc)})
            continue

        if difficulty == "guardrail":
            passed = resp.status_code == 200 and resp.json().get("guardrail_blocked") is True
            print(f"  {'PASS' if passed else 'FAIL'}: expected guardrail block, got status {resp.status_code}")
            results.append({**case, "passed": passed})
            continue

        if difficulty == "ambiguous":
            passed = resp.status_code == 422
            print(f"  {'PASS' if passed else 'FAIL'}: expected clarification request, got status {resp.status_code}")
            results.append({**case, "passed": passed})
            continue

        if resp.status_code != 200:
            print(f"  FAIL: status {resp.status_code}: {resp.text[:200]}")
            results.append({**case, "passed": False, "reason": resp.text})
            continue

        data = resp.json()
        try:
            expected_df = run_expected_sql(case["expected_sql"])
            passed = rows_match(data["columns"], data["rows"], expected_df)
        except Exception as exc:
            passed = False
            print(f"  Comparison error: {exc}")

        confidence = data["confidence"]["overall"]
        print(f"  {'PASS' if passed else 'FAIL'}: execution match={passed}, confidence={confidence:.0%}")
        results.append({**case, "passed": passed, "confidence": confidence})

    total = len(results)
    passed_count = sum(1 for r in results if r["passed"])
    print(f"\n{'='*50}\n{passed_count}/{total} cases passed ({passed_count/total:.0%})")

    sys.exit(0 if passed_count == total else 1)


if __name__ == "__main__":
    main()
