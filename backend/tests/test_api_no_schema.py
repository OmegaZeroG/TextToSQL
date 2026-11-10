"""/v1/generate when the user gives only a question and no schema."""
import pytest

from tests.helpers import BACK_TRANSLATION, alignment, gen, no_schema_gen

DDL = "CREATE TABLE customers (id INT PRIMARY KEY, name TEXT);"


def generate(api, question="How many customers are there?", **extra):
    body = {"question": question, "dialect": "postgres", **extra}
    return api.client.post("/v1/generate", json=body)


class TestWithoutASchema:
    def test_writes_sql_and_reports_the_schema_it_assumed(self, api):
        api.script(no_schema_gen(), BACK_TRANSLATION, alignment(1.0))

        response = generate(api)

        assert response.status_code == 200
        body = response.json()
        assert body["schema_provided"] is False
        assert body["sql"] == "SELECT COUNT(*) FROM customers"
        assert body["assumed_schema"] == "CREATE TABLE customers (id INT PRIMARY KEY, name TEXT);"
        assert body["assumptions"] == ["Assumed a customers table with id and name."]
        assert body["tables_used"] == ["customers"]
        assert body["guardrail_blocked"] is False

    @pytest.mark.parametrize("extra", [{}, {"schema_ddl": None}, {"schema_ddl": ""}, {"schema_ddl": "  \n  "}])
    def test_missing_null_or_blank_schema_all_mean_no_schema(self, api, extra):
        api.script(no_schema_gen(), BACK_TRANSLATION, alignment(1.0))
        assert generate(api, **extra).json()["schema_provided"] is False

    def test_always_warns_that_names_are_assumed(self, api):
        api.script(no_schema_gen(), BACK_TRANSLATION, alignment(1.0))
        warnings = generate(api).json()["warnings"]
        assert any("No schema was provided" in w for w in warnings)

    def test_confidence_is_capped_however_clean_the_signals(self, api):
        api.script(no_schema_gen(confidence=5), BACK_TRANSLATION, alignment(1.0))
        assert generate(api).json()["confidence"]["overall"] == 0.6

    def test_the_same_perfect_signals_are_not_capped_when_a_schema_is_given(self, api):
        api.script(gen("SELECT COUNT(*) FROM customers"), BACK_TRANSLATION, alignment(1.0))
        assert generate(api, schema_ddl=DDL).json()["confidence"]["overall"] == 1.0

    def test_poor_signals_still_fall_below_the_cap(self, api):
        api.script(no_schema_gen(confidence=1), BACK_TRANSLATION, alignment(0.0))
        body = generate(api).json()
        assert body["confidence"]["overall"] < 0.5
        assert any("Low confidence" in w for w in body["warnings"])

    def test_prompt_tells_the_model_there_is_no_schema_and_to_guess(self, api):
        api.script(no_schema_gen(), BACK_TRANSLATION, alignment(1.0))
        generate(api, dialect="tsql")
        system = api.llm.calls[0]["system"]
        assert "NO schema" in system
        assert "SQL Server" in system
        assert "Do NOT ask for clarification" in system
        assert "SCHEMA:" not in system


class TestSelfConsistencyCheck:
    def test_sql_using_a_column_missing_from_its_own_assumed_schema_is_flagged(self, api):
        api.script(no_schema_gen("SELECT phone FROM customers"), no_schema_gen("SELECT phone FROM customers"), BACK_TRANSLATION, alignment(1.0))  # the repair attempt changes nothing
        body = generate(api).json()
        assert body["confidence"]["schema_check_passed"] is False
        assert any("phone" in w for w in body["warnings"])

    def test_sql_using_a_table_missing_from_its_own_assumed_schema_is_flagged(self, api):
        api.script(no_schema_gen("SELECT * FROM invoices"), no_schema_gen("SELECT * FROM invoices"), BACK_TRANSLATION, alignment(1.0))
        body = generate(api).json()
        assert body["confidence"]["schema_check_passed"] is False
        assert any("invoices" in w for w in body["warnings"])

    @pytest.mark.parametrize("overrides", [
        {"assumed_schema": "this is not DDL"},
        {"assumed_schema": None},
        {"assumed_schema": 42},
    ])
    def test_an_unreadable_assumed_schema_degrades_gracefully(self, api, overrides):
        api.script(no_schema_gen(**overrides), BACK_TRANSLATION, alignment(1.0))
        response = generate(api)
        assert response.status_code == 200
        body = response.json()
        assert body["assumed_schema"] is None
        assert any("couldn't be read" in w for w in body["warnings"])

    def test_a_missing_assumed_schema_key_is_handled(self, api):
        payload = no_schema_gen()
        import json
        data = json.loads(payload)
        del data["assumed_schema"]
        api.script(json.dumps(data), BACK_TRANSLATION, alignment(1.0))
        assert generate(api).status_code == 200

    def test_wrong_dialect_syntax_is_still_caught_without_a_schema(self, api):
        api.script(no_schema_gen("SELECT name FROM customers LIMIT 5"), no_schema_gen("SELECT name FROM customers LIMIT 5"), BACK_TRANSLATION, alignment(1.0))
        body = generate(api, dialect="tsql").json()
        assert body["confidence"]["syntax_valid"] is False
        assert any("TOP" in w for w in body["warnings"])


class TestAssumptionsAreSanitised:
    def test_non_string_items_are_dropped_and_the_list_is_capped(self, api):
        api.script(
            no_schema_gen(assumptions=["a", 1, None, {"x": 1}, "b"] + [f"extra {i}" for i in range(10)]),
            BACK_TRANSLATION, alignment(1.0),
        )
        assumptions = generate(api).json()["assumptions"]
        assert assumptions[:2] == ["a", "b"]
        assert len(assumptions) == 8
        assert all(isinstance(a, str) for a in assumptions)

    def test_a_non_list_value_is_ignored(self, api):
        api.script(no_schema_gen(assumptions="not a list"), BACK_TRANSLATION, alignment(1.0))
        assert generate(api).json()["assumptions"] == []


class TestGuardrailsAndFailures:
    @pytest.mark.parametrize("sql", ["DELETE FROM customers", "DROP TABLE customers", "SELECT 1; DROP TABLE t"])
    def test_unsafe_sql_is_blocked(self, api, sql):
        api.script(no_schema_gen(sql))
        body = generate(api, "remove all customers").json()
        assert body["guardrail_blocked"] is True
        assert body["schema_provided"] is False
        assert len(api.llm.calls) == 1

    def test_model_output_without_sql_is_a_502(self, api):
        api.script('{"explanation": "no sql"}')
        assert generate(api).status_code == 502

    def test_ambiguity_flag_is_ignored_because_the_model_must_guess(self, api):
        api.script(no_schema_gen(ambiguous=True, interpretations=["a", "b"]), BACK_TRANSLATION, alignment(1.0))
        response = generate(api)
        assert response.status_code == 200
        assert response.json()["sql"]

    def test_ambiguous_without_sql_is_a_502_not_a_clarification_prompt(self, api):
        api.script('{"ambiguous": true, "interpretations": ["a", "b"]}')
        assert generate(api).status_code == 502

    def test_llm_outage_is_a_502(self, api):
        api.script(RuntimeError("groq is down"))
        assert generate(api).status_code == 502
