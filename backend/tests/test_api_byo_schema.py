"""Bring-your-own-schema endpoints: /v1/dialects, /v1/schema/analyze, /v1/generate."""
import json

import pytest

from tests.helpers import BACK_TRANSLATION, alignment, gen

DDL = """
CREATE TABLE customers (id INT PRIMARY KEY, name TEXT, email TEXT);
CREATE TABLE orders (id INT PRIMARY KEY, customer_id INT, total DECIMAL(10, 2));
"""


def generate(api, question="How many customers are there?", dialect="postgres", schema_ddl=DDL):
    return api.client.post(
        "/v1/generate", json={"question": question, "schema_ddl": schema_ddl, "dialect": dialect}
    )


def analyze(api, schema_text, dialect="postgres"):
    return api.client.post("/v1/schema/analyze", json={"schema_text": schema_text, "dialect": dialect})


def test_dialects_endpoint_lists_every_supported_dialect(api):
    body = api.client.get("/v1/dialects").json()
    assert {"id": "postgres", "label": "PostgreSQL"} in body
    assert {"id": "tsql", "label": "SQL Server"} in body
    assert len(body) == 7


class TestAnalyze:
    def test_ddl_is_parsed_without_any_llm_call(self, api):
        response = analyze(api, DDL)
        assert response.status_code == 200
        body = response.json()
        assert body["source"] == "ddl"
        assert [t["name"] for t in body["tables"]] == ["customers", "orders"]
        assert body["tables"][1]["columns"][2] == {
            "name": "total", "type": "DECIMAL(10, 2)", "primary_key": False, "foreign_key": None,
        }
        assert api.llm is None  # get_llm_provider was never needed

    def test_plain_english_is_converted_by_the_llm(self, api):
        api.script(json.dumps({"ddl": "CREATE TABLE books (id INT, title TEXT);"}))
        body = analyze(api, "a books table with an id and a title").json()
        assert body["source"] == "text"
        assert body["tables"][0]["name"] == "books"
        assert "books" in body["ddl"]

    def test_unreadable_schema_returns_422(self, api):
        bad = json.dumps({"ddl": "not sql"})
        api.script(bad, bad)
        response = analyze(api, "gibberish")
        assert response.status_code == 422
        assert "Couldn't read that schema" in response.json()["detail"]

    def test_llm_outage_returns_502(self, api):
        api.script(RuntimeError("groq is down"))
        assert analyze(api, "a table of books").status_code == 502

    @pytest.mark.parametrize("body", [
        {"schema_text": ""},
        {"schema_text": "x" * 20001},
        {"schema_text": "CREATE TABLE t (id INT);", "dialect": "klingon"},
        {},
    ])
    def test_rejects_bad_requests(self, api, body):
        assert api.client.post("/v1/schema/analyze", json=body).status_code == 422


class TestGenerate:
    def test_returns_sql_with_a_confidence_breakdown(self, api):
        api.script(gen("SELECT COUNT(*) FROM customers", tables_used=["customers"]), BACK_TRANSLATION, alignment(1.0))

        response = generate(api)

        assert response.status_code == 200
        body = response.json()
        assert body["sql"] == "SELECT COUNT(*) FROM customers"
        assert body["dialect"] == "postgres"
        assert body["tables_used"] == ["customers"]
        assert body["guardrail_blocked"] is False
        assert body["warnings"] == []
        assert body["confidence"] == {
            "syntax_valid": True,
            "back_translation_alignment": 1.0,
            "schema_check_passed": True,
            "overall": 1.0,
        }

    def test_nothing_is_executed(self, api):
        api.script(gen("SELECT COUNT(*) FROM customers"), BACK_TRANSLATION, alignment(1.0))
        generate(api)
        assert api.executed_sql == []

    def test_no_row_limit_is_forced_onto_the_sql(self, api):
        api.script(gen("SELECT name FROM customers;"), BACK_TRANSLATION, alignment(1.0))
        assert generate(api).json()["sql"] == "SELECT name FROM customers"

    def test_multiline_formatting_is_preserved(self, api):
        sql = "SELECT c.name\nFROM customers c\nJOIN orders o ON o.customer_id = c.id"
        api.script(gen(sql), BACK_TRANSLATION, alignment(1.0))
        assert generate(api).json()["sql"] == sql

    def test_prompt_contains_the_users_schema_and_dialect(self, api):
        api.script(gen("SELECT COUNT(*) FROM customers"), BACK_TRANSLATION, alignment(1.0))
        generate(api, dialect="tsql")
        system = api.llm.calls[0]["system"]
        assert "CREATE TABLE customers" in system
        assert "SQL Server" in system

    def test_tables_used_comes_from_the_sql_not_the_models_claim(self, api):
        api.script(gen("SELECT name FROM customers", tables_used=["orders", "ghost"]), BACK_TRANSLATION, alignment(1.0))
        assert generate(api).json()["tables_used"] == ["customers"]


class TestHallucinationDetection:
    def test_invented_table_is_warned_about_and_lowers_confidence(self, api):
        api.script(gen("SELECT * FROM invoices"), BACK_TRANSLATION, alignment(1.0))
        body = generate(api).json()
        assert body["confidence"]["schema_check_passed"] is False
        assert any("invoices" in w for w in body["warnings"])
        assert body["confidence"]["overall"] < 1.0

    def test_invented_column_is_warned_about(self, api):
        api.script(gen("SELECT c.phone FROM customers c"), BACK_TRANSLATION, alignment(1.0))
        body = generate(api).json()
        assert body["confidence"]["schema_check_passed"] is False
        assert any("phone" in w for w in body["warnings"])

    def test_wrong_dialect_syntax_is_reported(self, api):
        api.script(gen("SELECT name FROM customers LIMIT 5"), BACK_TRANSLATION, alignment(1.0))
        body = generate(api, dialect="tsql").json()
        assert body["confidence"]["syntax_valid"] is False
        assert any("TOP" in w for w in body["warnings"])

    def test_low_confidence_adds_a_warning(self, api):
        api.script(gen("SELECT * FROM invoices", confidence=1), BACK_TRANSLATION, alignment(0.0))
        assert any("Low confidence" in w for w in generate(api).json()["warnings"])

    def test_a_failing_judge_does_not_fail_the_request(self, api):
        api.script(gen("SELECT COUNT(*) FROM customers"), RuntimeError("judge down"))
        response = generate(api)
        assert response.status_code == 200
        assert response.json()["confidence"]["back_translation_alignment"] == 0.5


class TestGuardrails:
    @pytest.mark.parametrize("sql", [
        "DELETE FROM customers WHERE id = 1",
        "DROP TABLE customers",
        "UPDATE customers SET name = 'x'",
        "SELECT 1; DROP TABLE customers",
    ])
    def test_unsafe_sql_is_blocked_even_though_nothing_would_run(self, api, sql):
        api.script(gen(sql))
        body = generate(api, "remove everything").json()
        assert body["guardrail_blocked"] is True
        assert body["block_reason"]
        assert body["confidence"]["overall"] == 0
        assert len(api.llm.calls) == 1  # no back-translation spend on blocked SQL

    def test_deeply_nested_but_read_only_sql_is_allowed(self, api):
        """The nesting cap protects a database that executes the query. Here nothing
        executes, so it must not get in the way of legitimately complex SQL."""
        nested = (
            "SELECT * FROM (SELECT * FROM (SELECT * FROM (SELECT * FROM "
            "(SELECT name FROM customers) a) b) c) d"
        )
        api.script(gen(nested), BACK_TRANSLATION, alignment(1.0))
        assert generate(api).json()["guardrail_blocked"] is False


class TestNonAnswers:
    def test_ambiguous_question_returns_422_with_readings(self, api):
        api.script(gen("", ambiguous=True, interpretations=["gross", "net"]))
        response = generate(api, "What is the revenue?")
        assert response.status_code == 422
        detail = response.json()["detail"]
        assert detail["kind"] == "ambiguous"
        assert detail["interpretations"] == ["gross", "net"]

    def test_question_the_schema_cannot_answer_says_what_is_missing(self, api):
        api.script(gen("", unanswerable_reason="The schema has no column for shoe size."))
        response = generate(api, "What is each customer's shoe size?")
        assert response.status_code == 422
        detail = response.json()["detail"]
        assert detail["kind"] == "unanswerable"
        assert detail["interpretations"] == ["The schema has no column for shoe size."]


class TestFailureModes:
    def test_unreadable_schema_returns_422_before_any_llm_call(self, api):
        response = generate(api, schema_ddl="this is not a schema")
        assert response.status_code == 422
        assert "Couldn't read that schema" in response.json()["detail"]
        assert api.llm is None

    def test_llm_outage_returns_502(self, api):
        api.script(RuntimeError("groq is down"))
        assert generate(api).status_code == 502

    def test_plain_text_refusal_returns_502(self, api):
        api.script("I'm sorry, but I can't help with that.")
        assert generate(api).status_code == 502

    @pytest.mark.parametrize("body", [
        {"schema_ddl": DDL},
        {"question": "", "schema_ddl": DDL},
        {"question": "", "schema_ddl": ""},
        {"question": "q", "schema_ddl": DDL, "dialect": "klingon"},
        {"question": "x" * 1001, "schema_ddl": DDL},
        {"question": "q", "schema_ddl": "x" * 20001},
    ])
    def test_rejects_bad_requests_before_touching_the_llm(self, api, body):
        api.script()
        assert api.client.post("/v1/generate", json=body).status_code == 422
        assert api.llm.calls == []


class TestSchemaUpdateEndpoint:
    CURRENT = "CREATE TABLE customers (id INT PRIMARY KEY, name TEXT);"

    def update(self, api, change_text, current_ddl=None, dialect="postgres"):
        return api.client.post(
            "/v1/schema/update",
            json={"current_ddl": current_ddl or self.CURRENT, "change_text": change_text, "dialect": dialect},
        )

    def test_explicit_sql_change_succeeds_without_an_llm(self, api):
        response = self.update(api, "CREATE TABLE orders (id INT, customer_id INT);")
        assert response.status_code == 200
        body = response.json()
        assert body["source"] == "ddl"
        assert body["changes"] == ["Added table orders (2 columns)"]
        assert [t["name"] for t in body["tables"]] == ["customers", "orders"]
        assert "CREATE TABLE orders" in body["ddl"]
        assert api.llm is None

    def test_plain_english_change_is_applied_and_reported(self, api):
        api.script(json.dumps({"ddl": "CREATE TABLE customers (id INT PRIMARY KEY, name TEXT, phone TEXT);"}))
        body = self.update(api, "customers also have a phone number").json()
        assert body["source"] == "text"
        assert body["changes"] == ["Added column customers.phone (TEXT)"]
        assert body["tables"][0]["columns"][2] == {
            "name": "phone", "type": "TEXT", "primary_key": False, "foreign_key": None,
        }

    @pytest.mark.parametrize("change_text, ddl_from_llm, expected_in_detail", [
        ("make sure customers has a name", "CREATE TABLE customers (id INT PRIMARY KEY, name TEXT);", "doesn't change anything"),
        ("add a phone column", "CREATE TABLE other (x INT);", "Removed table customers"),
    ])
    def test_unsafe_or_pointless_changes_fail_with_a_reason(self, api, change_text, ddl_from_llm, expected_in_detail):
        api.script(json.dumps({"ddl": ddl_from_llm}))
        response = self.update(api, change_text)
        assert response.status_code == 422
        assert "Schema not changed" in response.json()["detail"]
        assert expected_in_detail in response.json()["detail"]

    def test_unreadable_change_fails_after_two_attempts(self, api):
        bad = json.dumps({"ddl": "not sql"})
        api.script(bad, bad)
        assert self.update(api, "gibberish").status_code == 422

    def test_unreadable_saved_schema_fails(self, api):
        response = self.update(api, "CREATE TABLE t (id INT);", current_ddl="garbage")
        assert response.status_code == 422
        assert "saved schema can't be read" in response.json()["detail"]

    def test_llm_outage_is_a_502(self, api):
        api.script(RuntimeError("groq is down"))
        assert self.update(api, "add a phone column").status_code == 502

    @pytest.mark.parametrize("body", [
        {"change_text": "x"},
        {"current_ddl": "CREATE TABLE t (id INT);"},
        {"current_ddl": "", "change_text": "x"},
        {"current_ddl": "CREATE TABLE t (id INT);", "change_text": ""},
        {"current_ddl": "CREATE TABLE t (id INT);", "change_text": "x", "dialect": "klingon"},
        {"current_ddl": "CREATE TABLE t (id INT);", "change_text": "x" * 20001},
    ])
    def test_rejects_bad_requests(self, api, body):
        assert api.client.post("/v1/schema/update", json=body).status_code == 422


class TestKeyFlagsInTheApi:
    def test_analyze_reports_primary_and_foreign_keys(self, api):
        ddl = "CREATE TABLE emp (id INT PRIMARY KEY, dept_id INT REFERENCES dept(id), name TEXT);"
        columns = {c["name"]: c for c in analyze(api, ddl).json()["tables"][0]["columns"]}
        assert columns["id"]["primary_key"] is True
        assert columns["dept_id"]["foreign_key"] == "dept.id"
        assert columns["name"] == {"name": "name", "type": "TEXT", "primary_key": False, "foreign_key": None}

    def test_update_keeps_reporting_keys(self, api):
        current = "CREATE TABLE emp (id INT PRIMARY KEY, name TEXT);"
        body = api.client.post(
            "/v1/schema/update",
            json={"current_ddl": current, "change_text": "CREATE TABLE tags (id INT PRIMARY KEY);", "dialect": "postgres"},
        ).json()
        assert all(t["columns"][0]["primary_key"] for t in body["tables"])
