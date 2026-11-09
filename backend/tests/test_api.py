import pandas as pd
import pytest

from tests.helpers import BACK_TRANSLATION, alignment, gen


def ask(api, question="How many orders are there?"):
    return api.client.post("/v1/query", json={"question": question})


def test_health(api):
    response = api.client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_schema_endpoint_lists_tables(api, tables):
    body = api.client.get("/v1/schema").json()
    assert body["tables"] == [t.name for t in tables]
    assert "TABLE orders" in body["schema"]


class TestSuccessfulQuery:
    def test_runs_the_full_pipeline(self, api):
        api.script(gen(), BACK_TRANSLATION, alignment(1.0))
        api.returns(pd.DataFrame({"n": [227]}))

        response = ask(api)

        assert response.status_code == 200
        body = response.json()
        assert body["guardrail_blocked"] is False
        assert body["columns"] == ["n"]
        assert body["rows"] == [[227]]
        assert body["row_count"] == 1
        assert body["explanation"] == "Counts orders."
        assert body["confidence"] == {
            "syntax_valid": True,
            "back_translation_alignment": 1.0,
            "result_sanity_passed": True,
            "overall": 1.0,
        }
        assert body["warnings"] == []

    def test_executes_the_guardrail_rewritten_sql_with_a_row_limit(self, api):
        api.script(gen("SELECT COUNT(*) AS n FROM orders;"), BACK_TRANSLATION, alignment(1.0))
        ask(api)
        assert api.executed_sql == ["SELECT COUNT(*) AS n FROM orders LIMIT 1000"]

    def test_is_recorded_in_history(self, api):
        api.script(gen(), BACK_TRANSLATION, alignment(1.0))
        ask(api, "How many orders?")
        entries = api.client.get("/v1/history").json()
        assert len(entries) == 1
        assert entries[0]["question"] == "How many orders?"
        assert entries[0]["confidence"] == 1.0

    def test_low_confidence_adds_a_warning(self, api):
        api.script(gen(confidence=1), BACK_TRANSLATION, alignment(0.0))
        body = ask(api).json()
        assert body["confidence"]["overall"] < 0.5
        assert any("Low confidence" in w for w in body["warnings"])

    def test_empty_result_is_flagged(self, api):
        api.script(gen(), BACK_TRANSLATION, alignment(1.0))
        api.returns(pd.DataFrame({"n": []}))
        body = ask(api).json()
        assert body["row_count"] == 0
        assert body["columns"] == ["n"]
        assert any("zero rows" in w for w in body["warnings"])

    def test_truncated_result_lowers_confidence_and_warns(self, api):
        api.script(gen(), BACK_TRANSLATION, alignment(1.0))
        api.returns(pd.DataFrame({"n": range(1000)}))
        body = ask(api).json()
        assert body["confidence"]["result_sanity_passed"] is False
        assert any("truncated" in w for w in body["warnings"])

    def test_a_failing_judge_does_not_fail_the_request(self, api):
        """Back-translation is advisory: if that LLM call dies we degrade to a
        neutral 0.5 alignment instead of returning an error."""
        api.script(gen(), RuntimeError("judge unavailable"))
        response = ask(api)
        assert response.status_code == 200
        body = response.json()
        assert body["confidence"]["back_translation_alignment"] == 0.5
        assert body["confidence"]["overall"] == pytest.approx(0.75)


class TestGuardrailsAtTheApiBoundary:
    @pytest.mark.parametrize("sql", [
        "DELETE FROM orders WHERE status = 'cancelled'",
        "DROP TABLE orders",
        "UPDATE orders SET status = 'x'",
        "INSERT INTO orders VALUES (1)",
        "SELECT 1; DELETE FROM orders",
    ])
    def test_unsafe_sql_is_blocked_and_never_executed(self, api, sql):
        api.script(gen(sql))

        response = ask(api, "do something destructive")

        assert response.status_code == 200
        body = response.json()
        assert body["guardrail_blocked"] is True
        assert body["block_reason"]
        assert body["rows"] == []
        assert body["confidence"]["overall"] == 0
        assert api.executed_sql == []

    def test_blocked_queries_skip_the_back_translation_llm_calls(self, api):
        api.script(gen("DROP TABLE orders"))
        ask(api)
        assert len(api.llm.calls) == 1

    def test_blocked_queries_are_not_added_to_history(self, api):
        api.script(gen("DROP TABLE orders"))
        ask(api)
        assert api.client.get("/v1/history").json() == []


class TestAmbiguity:
    def test_ambiguous_question_returns_422_with_interpretations(self, api):
        api.script(gen(sql="", ambiguous=True, interpretations=["gross revenue", "net revenue"]))

        response = ask(api, "What is the revenue?")

        assert response.status_code == 422
        detail = response.json()["detail"]
        assert detail["interpretations"] == ["gross revenue", "net revenue"]
        assert api.executed_sql == []


class TestFailureModes:
    def test_llm_outage_returns_502(self, api):
        api.script(RuntimeError("groq is down"))
        response = ask(api)
        assert response.status_code == 502
        assert "LLM generation failed" in response.json()["detail"]

    def test_plain_text_refusal_returns_502_not_a_crash(self, api):
        api.script("I'm sorry, but I can't help with that.")
        assert ask(api).status_code == 502

    def test_database_error_returns_400(self, api):
        api.script(gen())
        api.returns(RuntimeError('relation "ghost" does not exist'))
        response = ask(api)
        assert response.status_code == 400
        assert "Query execution failed" in response.json()["detail"]

    @pytest.mark.parametrize("payload", [
        '{"explanation": "no sql key", "confidence": 3, "tables_used": []}',
        "[1, 2, 3]",
    ])
    def test_structurally_invalid_llm_json_returns_502(self, api, payload):
        api.script(payload)
        assert ask(api).status_code == 502


class TestRequestValidation:
    @pytest.mark.parametrize("body", [
        {},
        {"question": ""},
        {"question": "x" * 1001},
        {"question": 123},
    ])
    def test_rejects_bad_requests_before_touching_the_llm(self, api, body):
        api.script()
        assert api.client.post("/v1/query", json=body).status_code == 422
        assert api.llm.calls == []


class TestHistoryEndpoint:
    def test_newest_first_and_limit(self, api):
        for question in ["first", "second", "third"]:
            api.script(gen(), BACK_TRANSLATION, alignment(1.0))
            ask(api, question)

        entries = api.client.get("/v1/history").json()
        assert [e["question"] for e in entries] == ["third", "second", "first"]

        limited = api.client.get("/v1/history", params={"limit": 1}).json()
        assert [e["question"] for e in limited] == ["third"]
