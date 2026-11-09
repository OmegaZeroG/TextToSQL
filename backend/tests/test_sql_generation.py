import json

import pytest

from app import sql_generation
from app.schema_introspection import ColumnInfo, TableInfo
from app.sql_generation import _extract_json, generate_sql
from tests.helpers import FakeLLM, gen


class TestExtractJson:
    def test_plain_json(self):
        assert _extract_json('{"sql": "SELECT 1"}') == {"sql": "SELECT 1"}

    @pytest.mark.parametrize("raw", [
        '```json\n{"sql": "SELECT 1"}\n```',
        '```\n{"sql": "SELECT 1"}\n```',
        '  \n{"sql": "SELECT 1"}\n  ',
    ])
    def test_strips_fences_and_whitespace(self, raw):
        assert _extract_json(raw) == {"sql": "SELECT 1"}

    def test_plain_text_refusal_raises(self):
        with pytest.raises(json.JSONDecodeError):
            _extract_json("I'm sorry, but I can't help with that.")


class TestGenerateSql:
    def test_returns_the_parsed_model_output(self, tables):
        llm = FakeLLM([gen("SELECT 1")])
        assert generate_sql(llm, "anything", tables)["sql"] == "SELECT 1"

    def test_requests_json_mode_and_passes_the_question(self, tables):
        llm = FakeLLM([gen()])
        generate_sql(llm, "How many orders?", tables)
        call = llm.calls[0]
        assert call["json_mode"] is True
        assert "How many orders?" in call["user"]

    def test_prompt_tells_the_model_not_to_refuse_destructive_requests(self, tables):
        """Regression: the model used to refuse 'delete ...' in plain text, which
        skipped our guardrail and produced a 502 instead of a clean block."""
        llm = FakeLLM([gen()])
        generate_sql(llm, "delete everything", tables)
        system = llm.calls[0]["system"]
        assert "Do NOT" in system and "refuse" in system
        assert "DELETE FROM orders" in system  # the few-shot example

    def test_small_schemas_are_always_sent_in_full(self, tables):
        """Regression: keyword filtering hid orders/order_items for 'top customers
        by total spend' (the word 'spend' matches no table), causing false ambiguity."""
        llm = FakeLLM([gen()])
        generate_sql(llm, "top customers by total spend", tables)
        system = llm.calls[0]["system"]
        for table in tables:
            assert f"TABLE {table.name}" in system

    def test_large_schemas_are_filtered_to_relevant_tables(self):
        many = [
            TableInfo(f"table{i}x", [ColumnInfo("id", "INTEGER")], [])
            for i in range(sql_generation.RELEVANCE_FILTER_TABLE_THRESHOLD + 1)
        ]
        llm = FakeLLM([gen()])
        generate_sql(llm, "show me table3x", many)
        system = llm.calls[0]["system"]
        assert "TABLE table3x" in system
        assert "TABLE table9x" not in system

    def test_propagates_invalid_json_so_the_api_can_return_a_502(self, tables):
        with pytest.raises(json.JSONDecodeError):
            generate_sql(FakeLLM(["definitely not json"]), "q", tables)

    @pytest.mark.parametrize("payload", ["[1, 2]", '"just a string"', "42"])
    def test_rejects_json_that_is_not_an_object(self, tables, payload):
        with pytest.raises(ValueError, match="not a JSON object"):
            generate_sql(FakeLLM([payload]), "q", tables)

    @pytest.mark.parametrize("payload", ['{"explanation": "x"}', '{"sql": null}', '{"sql": 5}'])
    def test_rejects_output_without_a_sql_string(self, tables, payload):
        with pytest.raises(ValueError, match="missing a 'sql' string"):
            generate_sql(FakeLLM([payload]), "q", tables)

    def test_ambiguous_output_does_not_need_sql(self, tables):
        payload = '{"ambiguous": true, "interpretations": ["a", "b"]}'
        assert generate_sql(FakeLLM([payload]), "q", tables)["interpretations"] == ["a", "b"]
