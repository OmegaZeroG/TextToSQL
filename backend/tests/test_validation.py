import json

import pandas as pd
import pytest

from app.validation import back_translate_and_score, compute_confidence, result_sanity_check
from tests.helpers import FakeLLM, alignment


class TestResultSanityCheck:
    def test_clean_result_passes_without_warnings(self):
        passed, warnings = result_sanity_check(pd.DataFrame({"city": ["a", "b"], "n": [1, 2]}), 1000)
        assert passed
        assert warnings == []

    def test_empty_result_warns_but_still_passes(self):
        passed, warnings = result_sanity_check(pd.DataFrame({"n": []}), 1000)
        assert passed
        assert any("zero rows" in w for w in warnings)

    def test_result_at_the_row_limit_is_flagged_as_truncated(self):
        passed, warnings = result_sanity_check(pd.DataFrame({"n": range(5)}), 5)
        assert not passed
        assert any("truncated" in w for w in warnings)

    @pytest.mark.parametrize("column", ["quantity", "total_spend", "order_count", "unit_price", "amount"])
    def test_negative_values_in_count_like_columns_are_flagged(self, column):
        passed, warnings = result_sanity_check(pd.DataFrame({column: [-1, 2]}), 1000)
        assert not passed
        assert any("negative" in w for w in warnings)

    def test_negative_values_in_unrelated_columns_are_fine(self):
        passed, _ = result_sanity_check(pd.DataFrame({"temperature": [-5, 2]}), 1000)
        assert passed

    def test_null_heavy_column_suggests_a_bad_join(self):
        df = pd.DataFrame({"a": [1, 2, 3, 4, 5], "b": [None, None, None, None, 1]})
        passed, warnings = result_sanity_check(df, 1000)
        assert not passed
        assert any("NULL" in w for w in warnings)

    def test_tiny_results_are_not_judged_on_null_ratio(self):
        df = pd.DataFrame({"a": [1, 2], "b": [None, None]})
        passed, _ = result_sanity_check(df, 1000)
        assert passed


class TestComputeConfidence:
    def test_perfect_signals_give_full_confidence(self):
        assert compute_confidence(5, 1.0, True) == 1.0

    def test_weights_are_applied(self):
        # 0.2 * (3/5) + 0.5 * 0.5 + 0.3 * 0.4
        assert compute_confidence(3, 0.5, False) == pytest.approx(0.49)

    def test_failed_sanity_check_costs_eighteen_points(self):
        assert compute_confidence(5, 1.0, True) - compute_confidence(5, 1.0, False) == pytest.approx(0.18)

    def test_back_translation_dominates_self_reported_confidence(self):
        overconfident_but_misaligned = compute_confidence(5, 0.0, True)
        unsure_but_aligned = compute_confidence(1, 1.0, True)
        assert unsure_but_aligned > overconfident_but_misaligned

    def test_result_is_rounded_to_three_places(self):
        assert compute_confidence(1, 0.333, True) == round(compute_confidence(1, 0.333, True), 3)


class TestBackTranslation:
    def test_returns_the_judges_alignment_score(self):
        llm = FakeLLM([json.dumps({"back_translated_question": "How many orders?"}), alignment(0.9)])
        assert back_translate_and_score(llm, "Count orders", "SELECT COUNT(*) FROM orders") == 0.9

    def test_judge_sees_both_the_original_and_back_translated_question(self):
        llm = FakeLLM([json.dumps({"back_translated_question": "How many orders?"}), alignment(1.0)])
        back_translate_and_score(llm, "Count orders", "SELECT COUNT(*) FROM orders")
        assert "SELECT COUNT(*) FROM orders" in llm.calls[0]["user"]
        assert "Count orders" in llm.calls[1]["user"]
        assert "How many orders?" in llm.calls[1]["user"]

    def test_tolerates_markdown_fenced_json(self):
        llm = FakeLLM([
            '```json\n{"back_translated_question": "x"}\n```',
            '```\n{"alignment_score": 0.7}\n```',
        ])
        assert back_translate_and_score(llm, "q", "SELECT 1") == 0.7

    @pytest.mark.parametrize("raw, expected", [(1.7, 1.0), (-0.4, 0.0)])
    def test_clamps_out_of_range_scores(self, raw, expected):
        llm = FakeLLM([json.dumps({"back_translated_question": "x"}), alignment(raw)])
        assert back_translate_and_score(llm, "q", "SELECT 1") == expected

    def test_falls_back_to_neutral_when_the_llm_call_fails(self):
        assert back_translate_and_score(FakeLLM([RuntimeError("boom")]), "q", "SELECT 1") == 0.5

    def test_falls_back_to_neutral_on_malformed_json(self):
        assert back_translate_and_score(FakeLLM(["not json"]), "q", "SELECT 1") == 0.5
