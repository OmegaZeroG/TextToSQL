"""Hallucination detection: catches SQL that is syntactically valid and
executes cleanly but doesn't actually answer the question asked.

Three independent signals feed the final confidence score:
1. Back-translation alignment  - ask the LLM what question the SQL answers,
   compare it to the original question.
2. Result sanity checks        - do row/column counts and value ranges look
   plausible, or does this smell like a broken JOIN (e.g. row explosion)?
3. Guardrail/syntax validity   - did the query pass static checks at all.
"""
import json
import re

import pandas as pd

from app.llm.base import LLMProvider

BACK_TRANSLATION_PROMPT = """Given this SQL query, describe in one plain-English sentence what \
question it answers. Respond with JSON only: {{"back_translated_question": "..."}}

SQL:
{sql}
"""

ALIGNMENT_JUDGE_PROMPT = """Compare these two questions and rate how well they mean the same \
thing on a 0.0-1.0 scale (1.0 = identical meaning, 0.0 = unrelated).
Respond with JSON only: {{"alignment_score": 0.0}}

Original question: {original}
Back-translated question: {back_translated}
"""


def back_translate_and_score(llm: LLMProvider, original_question: str, sql: str) -> float:
    try:
        raw = llm.complete("You are a precise SQL analyst.", BACK_TRANSLATION_PROMPT.format(sql=sql), json_mode=True)
        back_translated = json.loads(_strip_fences(raw))["back_translated_question"]

        raw_score = llm.complete(
            "You are a strict semantic similarity judge.",
            ALIGNMENT_JUDGE_PROMPT.format(original=original_question, back_translated=back_translated),
            json_mode=True,
        )
        score = json.loads(_strip_fences(raw_score))["alignment_score"]
        return max(0.0, min(1.0, float(score)))
    except Exception:
        return 0.5  # neutral score if the judge call itself fails


def _strip_fences(text: str) -> str:
    return re.sub(r"^```(json)?|```$", "", text.strip(), flags=re.MULTILINE).strip()


def result_sanity_check(df: pd.DataFrame, row_limit: int) -> tuple[bool, list[str]]:
    warnings = []
    passed = True

    if len(df) == 0:
        warnings.append("Query returned zero rows — verify this is expected, not a filter/JOIN bug.")

    if len(df) >= row_limit:
        warnings.append(f"Result was truncated at the {row_limit}-row limit; totals/aggregates may be incomplete.")
        passed = False

    for col in df.select_dtypes(include="number").columns:
        if (df[col] < 0).any() and any(k in col.lower() for k in ("count", "quantity", "total", "amount", "price")):
            warnings.append(f"Column '{col}' contains negative values, which is implausible for this field.")
            passed = False

    null_heavy = [c for c in df.columns if df[c].isna().mean() > 0.5 and len(df) > 3]
    if null_heavy:
        warnings.append(f"Columns {null_heavy} are more than 50% NULL — possible bad JOIN.")
        passed = False

    return passed, warnings


def compute_confidence(
    llm_reported_confidence: int,
    back_translation_score: float,
    sanity_passed: bool,
) -> float:
    """Weighted blend: the model's self-reported confidence is the least
    trustworthy signal, so it gets the smallest weight."""
    self_reported = llm_reported_confidence / 5.0
    sanity = 1.0 if sanity_passed else 0.4
    return round(0.2 * self_reported + 0.5 * back_translation_score + 0.3 * sanity, 3)
