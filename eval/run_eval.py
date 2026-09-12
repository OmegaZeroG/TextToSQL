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
import sys
from pathlib import Path

import pandas as pd
import requests
from sqlalchemy import create_engine, text

DATASET_PATH = Path(__file__).parent / "golden_dataset.json"
DATABASE_URL = os.getenv(
    "DATABASE_URL", "postgresql+psycopg2://postgres:postgres@localhost:5432/texttosql"
)


def run_expected_sql(sql: str) -> pd.DataFrame:
    engine = create_engine(DATABASE_URL)
    with engine.connect() as conn:
        result = conn.execute(text(sql))
        return pd.DataFrame(result.fetchall(), columns=list(result.keys()))


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
            actual_rows = set(tuple(row) for row in data["rows"])
            expected_rows = set(tuple(row) for row in expected_df.values.tolist())
            passed = actual_rows == expected_rows
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
