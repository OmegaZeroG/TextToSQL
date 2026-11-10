"""Hallucination detection: catches SQL that is syntactically valid but doesn't
actually answer the question asked.

Signals that feed the confidence score:
1. Back-translation alignment: ask the LLM what question the SQL answers and
   compare that to the original question (this module).
2. Static checks: does the SQL parse in the chosen dialect, and does it only use
   tables and columns that exist in the schema (schema_validation.py).
3. The model's own confidence, the least trustworthy signal and so weighted least.
"""
import json
import re

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


def compute_confidence(
    llm_reported_confidence: int,
    back_translation_score: float,
    static_checks_passed: bool,
) -> float:
    """Weighted blend: the model's self-reported confidence is the least
    trustworthy signal, so it gets the smallest weight."""
    self_reported = llm_reported_confidence / 5.0
    static = 1.0 if static_checks_passed else 0.4
    return round(0.2 * self_reported + 0.5 * back_translation_score + 0.3 * static, 3)
