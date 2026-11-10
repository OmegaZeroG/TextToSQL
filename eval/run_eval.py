"""Runs the golden dataset against a live API instance and reports:
- execution match: does the generated SQL return the same rows as the
  hand-written expected SQL (regardless of whether the text is identical)
- guardrail effectiveness: are write/DDL requests blocked instead of answered?
- ambiguity handling: does it ask instead of guessing?
- unanswerable handling: does it say so when the schema can't answer?

The API generates SQL for the sample schema (eval/sample_db.py) exactly the way
the web UI does, via POST /v1/generate. The grading happens here: both the
generated and the expected SQL run against a throwaway in-memory SQLite copy of
that schema. The product itself never executes anything.

Usage: python eval/run_eval.py [--api-url http://localhost:8000]
"""
import argparse
import json
import re
import sqlite3
import sys
import time
from datetime import date, datetime, timezone
from pathlib import Path

import requests

sys.path.insert(0, str(Path(__file__).parent))
from sample_db import SAMPLE_DDL, build_sample_db  # noqa: E402

DATASET_PATH = Path(__file__).parent / "golden_dataset.json"
DIALECT = "sqlite"

# ISO-ish date/timestamp strings, e.g. "2024-12", "2024-12-01",
# "2024-12-01 00:00:00", "2024-12-01T00:00:00Z", "2024-12-01T00:00:00.5+05:30".
_DATE_LIKE = re.compile(
    r"^\d{4}-\d{2}(-\d{2})?([ T]\d{2}:\d{2}(:\d{2}(\.\d+)?)?(Z|[+-]\d{2}:?\d{2})?)?$"
)


def _normalize_date(text: str) -> str:
    if re.fullmatch(r"\d{4}-\d{2}", text):
        text += "-01"
    parsed = datetime.fromisoformat(text)
    if parsed.tzinfo is not None:
        parsed = parsed.astimezone(timezone.utc).replace(tzinfo=None)
    if parsed.time() == datetime.min.time():
        return parsed.date().isoformat()
    return parsed.isoformat()


def _normalize(value):
    """Makes the comparison robust to harmless differences: ints vs floats
    (SUM over a REAL column can come back as 12.0 or 12), float rounding noise,
    booleans as 0/1, and the same day written as '2024-12', '2024-12-01' or
    '2024-12-01T00:00:00Z'."""
    if value is None:
        return None
    if isinstance(value, bool):
        return int(value)
    if isinstance(value, float):
        value = round(value, 4)
        return int(value) if value == int(value) else value
    if isinstance(value, (datetime, date)):
        return _normalize_date(value.isoformat())
    if isinstance(value, str) and _DATE_LIKE.match(value):
        return _normalize_date(value)
    return value


def rows_match(actual_rows: list, expected_rows: list) -> bool:
    """Column names and order are an arbitrary LLM choice (COUNT(*) might come
    back as "count" or "total_units", and a query may add a harmless extra column
    like `email`), so neither is compared. Instead, for every expected row its
    normalized values must be a *subset* of some actual row's values, with a 1-to-1
    pairing between expected and actual rows (a bijection) so row counts and
    per-row content both have to line up, just not the column layout."""
    if len(actual_rows) != len(expected_rows):
        return False

    remaining = [{_normalize(v) for v in row} for row in actual_rows]
    for expected_row in expected_rows:
        expected_set = {_normalize(v) for v in expected_row}
        index = next((i for i, actual in enumerate(remaining) if expected_set <= actual), None)
        if index is None:
            return False
        remaining.pop(index)
    return True


def post_generate(api_url: str, question: str) -> requests.Response:
    payload = {"question": question, "schema_ddl": SAMPLE_DDL, "dialect": DIALECT}
    for attempt in range(4):
        response = requests.post(f"{api_url}/v1/generate", json=payload, timeout=90)
        if response.status_code != 429:  # rate limited by the LLM provider: back off and retry
            return response
        time.sleep(5 * (attempt + 1))
    return response


def error_kind(response: requests.Response) -> str | None:
    try:
        detail = response.json().get("detail")
    except ValueError:
        return None
    return detail.get("kind") if isinstance(detail, dict) else None


def grade(case: dict, response: requests.Response, db: sqlite3.Connection) -> tuple[bool, str, float | None]:
    """Returns (passed, message, confidence)."""
    difficulty = case["difficulty"]

    if difficulty == "guardrail":
        blocked = response.status_code == 200 and response.json().get("guardrail_blocked") is True
        return blocked, "blocked by the guardrail" if blocked else f"expected a guardrail block, got HTTP {response.status_code}", None

    if difficulty in ("ambiguous", "unanswerable"):
        kind = error_kind(response)
        ok = response.status_code == 422 and kind == difficulty
        return ok, f"returned '{kind}'" if ok else f"expected '{difficulty}', got HTTP {response.status_code} kind={kind}", None

    if response.status_code != 200:
        return False, f"HTTP {response.status_code}: {response.text[:200]}", None

    data = response.json()
    confidence = data["confidence"]["overall"]
    if data.get("guardrail_blocked"):
        return False, f"wrongly blocked by the guardrail: {data.get('block_reason')}", confidence
    try:
        actual = db.execute(data["sql"]).fetchall()
    except sqlite3.Error as exc:
        return False, f"generated SQL failed to run: {exc}\n    {data['sql']}", confidence
    expected = db.execute(case["expected_sql"]).fetchall()
    if rows_match(actual, expected):
        return True, f"execution match, confidence={confidence:.0%}", confidence
    return False, f"results differ ({len(actual)} rows vs {len(expected)} expected)\n    {data['sql']}", confidence


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--api-url", default="http://localhost:8000")
    args = parser.parse_args()

    cases = json.loads(DATASET_PATH.read_text(encoding="utf-8"))
    db = build_sample_db()
    results = []

    for case in cases:
        print(f"\n[{case['id']}] ({case['difficulty']}) {case['question']}")
        try:
            response = post_generate(args.api_url, case["question"])
            passed, message, confidence = grade(case, response, db)
        except requests.RequestException as exc:
            passed, message, confidence = False, f"request error: {exc}", None
        print(f"  {'PASS' if passed else 'FAIL'}: {message}")
        results.append({**case, "passed": passed, "confidence": confidence})

    by_difficulty: dict[str, list[bool]] = {}
    for result in results:
        by_difficulty.setdefault(result["difficulty"], []).append(result["passed"])

    total = len(results)
    passed_count = sum(r["passed"] for r in results)
    print(f"\n{'=' * 50}")
    for difficulty, outcomes in by_difficulty.items():
        print(f"  {difficulty:<12} {sum(outcomes)}/{len(outcomes)}")
    print(f"{passed_count}/{total} cases passed ({passed_count / total:.0%})")

    sys.exit(0 if passed_count == total else 1)


if __name__ == "__main__":
    main()
