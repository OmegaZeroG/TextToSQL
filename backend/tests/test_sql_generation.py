import json

import pytest

from app.sql_generation import _extract_json, generate_sql_for_schema, generate_sql_without_schema
from tests.helpers import FakeLLM, gen, no_schema_gen

DDL = "CREATE TABLE orders (order_id INT PRIMARY KEY, status TEXT);"


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


def run(llm, question="q", dialect="postgres"):
    return generate_sql_for_schema(llm, question, DDL, dialect)


class TestGenerateSqlForSchema:
    def test_returns_the_parsed_model_output(self):
        assert run(FakeLLM([gen("SELECT 1")]))["sql"] == "SELECT 1"

    def test_requests_json_mode_and_passes_the_question(self):
        llm = FakeLLM([gen()])
        run(llm, "How many orders?")
        call = llm.calls[0]
        assert call["json_mode"] is True
        assert "How many orders?" in call["user"]

    def test_the_schema_and_dialect_are_in_the_prompt(self):
        llm = FakeLLM([gen()])
        run(llm, dialect="tsql")
        system = llm.calls[0]["system"]
        assert DDL in system
        assert "SQL Server" in system

    def test_prompt_tells_the_model_not_to_refuse_destructive_requests(self):
        """Regression: the model used to refuse 'delete ...' in plain text, which
        skipped our guardrail and produced a 502 instead of a clean block."""
        llm = FakeLLM([gen()])
        run(llm, "delete everything")
        system = llm.calls[0]["system"]
        assert "Do NOT" in system and "refuse" in system
        assert "DELETE FROM books" in system  # the few-shot example

    def test_propagates_invalid_json_so_the_api_can_return_a_502(self):
        with pytest.raises(json.JSONDecodeError):
            run(FakeLLM(["definitely not json"]))

    @pytest.mark.parametrize("payload", ["[1, 2]", '"just a string"', "42"])
    def test_rejects_json_that_is_not_an_object(self, payload):
        with pytest.raises(ValueError, match="not a JSON object"):
            run(FakeLLM([payload]))

    @pytest.mark.parametrize("payload", ['{"explanation": "x"}', '{"sql": null}', '{"sql": 5}'])
    def test_rejects_output_without_a_sql_string(self, payload):
        with pytest.raises(ValueError, match="missing a 'sql' string"):
            run(FakeLLM([payload]))

    def test_ambiguous_output_does_not_need_sql(self):
        payload = '{"ambiguous": true, "interpretations": ["a", "b"]}'
        assert run(FakeLLM([payload]))["interpretations"] == ["a", "b"]

    def test_unanswerable_output_does_not_need_sql(self):
        payload = '{"unanswerable_reason": "no such column"}'
        assert run(FakeLLM([payload]))["unanswerable_reason"] == "no such column"


class TestGenerateSqlWithoutSchema:
    def test_returns_the_parsed_model_output(self):
        assert generate_sql_without_schema(FakeLLM([no_schema_gen()]), "q", "postgres")["sql"]

    def test_prompt_has_no_schema_and_forbids_asking_for_clarification(self):
        llm = FakeLLM([no_schema_gen()])
        generate_sql_without_schema(llm, "How many customers?", "tsql")
        system = llm.calls[0]["system"]
        assert "SQL Server" in system
        assert "SCHEMA:" not in system
        assert "Do NOT ask for clarification" in system
