"""The verify-and-repair loop through POST /v1/generate.

The LLM is scripted, so each test controls exactly what the model "writes" on its
first attempt and on each repair, and the tests check what the pipeline does with it.
Call order for one request: generation, [repair, ...], back-translation, judge.
"""
import pytest

import app.main as main
from tests.helpers import BACK_TRANSLATION, alignment, gen, no_schema_gen
from tests.streak_sql import longest_streak_sql, month_number_roundtrip_sql

DDL = """
CREATE TABLE customers (customer_id INT PRIMARY KEY, name VARCHAR(50), manager_id INT);
CREATE TABLE orders (
    order_id INT PRIMARY KEY, customer_id INT REFERENCES customers(customer_id),
    order_date DATE, amount DECIMAL(10, 2), quantity INT
);
"""

NULL_BUG = "SELECT name FROM customers WHERE manager_id = NULL"
NULL_FIXED = "SELECT name FROM customers WHERE manager_id IS NULL"
DIVISION_BUG = "SELECT order_id, amount / quantity AS unit_price FROM orders"
DIVISION_FIXED = "SELECT order_id, amount / NULLIF(quantity, 0) AS unit_price FROM orders"


def generate(api, question="Who has no manager?", dialect="postgres", schema_ddl=DDL):
    body = {"question": question, "dialect": dialect}
    if schema_ddl is not None:
        body["schema_ddl"] = schema_ddl
    return api.client.post("/v1/generate", json=body)


def judge(score=1.0):
    return [BACK_TRANSLATION, alignment(score)]


class TestRepairHappyPath:
    def test_a_query_that_passes_is_never_sent_for_repair(self, api):
        api.script(gen(NULL_FIXED), *judge())
        generate(api)
        assert len(api.llm.calls) == 3  # generation + the two judge calls, nothing else

    def test_null_comparison_is_repaired(self, api):
        api.script(gen(NULL_BUG), gen(NULL_FIXED), *judge())
        body = generate(api).json()

        assert body["sql"] == NULL_FIXED
        assert body["confidence"]["logic_check_passed"] is True
        assert body["confidence"]["overall"] == 1.0
        note = next(w for w in body["warnings"] if "Corrected automatically" in w)
        assert "manager_id = NULL" in note  # says what was wrong, in one line

    def test_the_repair_request_names_the_problem_and_the_original_sql(self, api):
        api.script(gen(NULL_BUG), gen(NULL_FIXED), *judge())
        generate(api)

        repair = api.llm.calls[1]
        assert NULL_BUG in repair["user"]
        assert "Who has no manager?" in repair["user"]
        assert "manager_id IS NULL" in repair["user"]
        assert "CREATE TABLE customers" in repair["system"]
        assert repair["json_mode"] is True

    def test_unguarded_division_is_repaired(self, api):
        api.script(gen(DIVISION_BUG), gen(DIVISION_FIXED), *judge())
        body = generate(api, "unit price per order").json()
        assert body["sql"] == DIVISION_FIXED
        assert body["confidence"]["logic_check_passed"] is True

    def test_the_reported_month_arithmetic_bug_is_repaired_to_native_date_functions(self, api):
        api.script(gen(month_number_roundtrip_sql("postgres")), gen(longest_streak_sql("postgres")), *judge())
        body = generate(api, "customers with consecutive months of orders").json()

        repair_prompt = api.llm.calls[1]
        assert "month 00" in repair_prompt["user"]
        assert "DATE_TRUNC('month', d)::date" in repair_prompt["system"]  # the native recipe is in the repair prompt
        assert body["sql"] == longest_streak_sql("postgres")
        assert body["confidence"]["logic_check_passed"] is True
        assert "% 12" not in body["sql"]

    def test_an_impossible_date_literal_is_repaired(self, api):
        api.script(gen("SELECT * FROM orders WHERE order_date < '2025-02-30'"), gen("SELECT * FROM orders WHERE order_date < '2025-03-01'"), *judge())
        assert generate(api).json()["sql"].endswith("'2025-03-01'")

    def test_the_repaired_explanation_replaces_the_old_one(self, api):
        api.script(gen(NULL_BUG, explanation="old"), gen(NULL_FIXED, explanation="Lists customers with no manager."), *judge())
        assert generate(api).json()["explanation"] == "Lists customers with no manager."

    def test_the_repaired_models_own_confidence_is_used(self, api):
        api.script(gen(NULL_BUG, confidence=1), gen(NULL_FIXED, confidence=5), *judge())
        assert generate(api).json()["confidence"]["overall"] == 1.0


class TestDialectIsPreserved:
    def test_the_repair_prompt_is_in_the_requested_dialect(self, api):
        api.script(gen(NULL_BUG), gen(NULL_FIXED), *judge())
        generate(api, dialect="mysql")
        system = api.llm.calls[1]["system"]
        assert "MySQL" in system and "DATE_FORMAT" in system
        assert "PostgreSQL" not in system

    def test_a_repair_in_the_wrong_dialect_is_not_accepted(self, api):
        """The 'fix' swaps one error for a dialect error, which is not an improvement."""
        api.script(gen(NULL_BUG), gen("SELECT name FROM customers WHERE manager_id IS NULL LIMIT 5"), gen("SELECT TOP 5 name FROM customers WHERE manager_id IS NULL"), *judge())
        body = generate(api, dialect="tsql").json()
        assert "LIMIT" not in body["sql"]

    def test_a_tsql_limit_is_repaired_to_top(self, api):
        api.script(
            gen("SELECT name FROM customers LIMIT 5"),
            gen("SELECT TOP 5 name FROM customers"),
            *judge(),
        )
        body = generate(api, dialect="tsql").json()
        assert body["sql"] == "SELECT TOP 5 name FROM customers"
        assert body["confidence"]["syntax_valid"] is True

    def test_a_dialect_mistake_is_repaired(self, api):
        api.script(
            gen("SELECT DATE_TRUNC('month', order_date) AS m, COUNT(*) FROM orders GROUP BY 1"),
            gen("SELECT DATE_FORMAT(order_date, '%Y-%m-01') AS m, COUNT(*) FROM orders GROUP BY 1"),
            *judge(),
        )
        body = generate(api, dialect="mysql").json()
        assert "DATE_FORMAT" in body["sql"]
        assert body["confidence"]["logic_check_passed"] is True


class TestWhenRepairDoesNotWork:
    def test_a_repair_that_changes_nothing_keeps_the_draft_and_reports_its_problem(self, api):
        api.script(gen(NULL_BUG), gen(NULL_BUG), *judge())
        body = generate(api).json()

        assert body["sql"] == NULL_BUG
        assert body["confidence"]["logic_check_passed"] is False
        assert any("IS NULL" in w for w in body["warnings"])
        assert not any("Corrected automatically" in w for w in body["warnings"])
        assert body["confidence"]["overall"] < 1.0
        assert len(api.llm.calls) == 4  # generation, one repair, two judge calls

    def test_a_worse_repair_is_rejected(self, api):
        worse = "SELECT amount / quantity FROM orders WHERE amount = NULL"  # two problems instead of one
        api.script(gen(NULL_BUG), gen(worse), *judge())
        assert generate(api).json()["sql"] == NULL_BUG

    def test_a_repair_that_hits_a_model_outage_keeps_the_draft(self, api):
        api.script(gen(NULL_BUG), RuntimeError("groq is down"), *judge())
        response = generate(api)
        assert response.status_code == 200
        assert response.json()["sql"] == NULL_BUG
        assert response.json()["confidence"]["logic_check_passed"] is False

    def test_a_repair_that_returns_garbage_keeps_the_draft(self, api):
        api.script(gen(NULL_BUG), "definitely not json", *judge())
        assert generate(api).json()["sql"] == NULL_BUG

    def test_a_repair_that_says_ambiguous_is_ignored(self, api):
        api.script(gen(NULL_BUG), gen("", ambiguous=True, interpretations=["a", "b"]), *judge())
        assert generate(api).json()["sql"] == NULL_BUG

    def test_a_repair_that_says_the_schema_cannot_answer_is_ignored(self, api):
        api.script(gen(NULL_BUG), gen("", unanswerable_reason="no data"), *judge())
        assert generate(api).json()["sql"] == NULL_BUG

    @pytest.mark.parametrize("unsafe", ["DROP TABLE customers", "DELETE FROM customers", "SELECT 1; DROP TABLE orders"])
    def test_a_repair_that_is_unsafe_is_rejected_by_the_guardrail(self, api, unsafe):
        api.script(gen(NULL_BUG), gen(unsafe), *judge())
        body = generate(api).json()
        assert body["sql"] == NULL_BUG
        assert body["guardrail_blocked"] is False

    def test_the_users_request_is_never_failed_by_a_repair_problem(self, api):
        api.script(gen(NULL_BUG), RuntimeError("boom"), RuntimeError("judge boom"), RuntimeError("judge boom"))
        assert generate(api).status_code == 200


class TestRepairRounds:
    TWO_BUGS = "SELECT o.amount / o.quantity FROM orders o JOIN customers c ON c.customer_id = o.customer_id WHERE c.manager_id = NULL"
    ONE_BUG = "SELECT o.amount / o.quantity FROM orders o JOIN customers c ON c.customer_id = o.customer_id WHERE c.manager_id IS NULL"
    NO_BUG = "SELECT o.amount / NULLIF(o.quantity, 0) FROM orders o JOIN customers c ON c.customer_id = o.customer_id WHERE c.manager_id IS NULL"

    def test_a_second_round_finishes_the_job(self, api):
        api.script(gen(self.TWO_BUGS), gen(self.ONE_BUG), gen(self.NO_BUG), *judge())
        body = generate(api).json()
        assert body["sql"] == self.NO_BUG
        assert body["confidence"]["logic_check_passed"] is True
        assert len(api.llm.calls) == 5

    def test_the_second_round_is_told_only_what_is_still_wrong(self, api):
        api.script(gen(self.TWO_BUGS), gen(self.ONE_BUG), gen(self.NO_BUG), *judge())
        generate(api)
        second_repair = api.llm.calls[2]["user"]
        assert self.ONE_BUG in second_repair
        assert "NULLIF" in second_repair and "IS NULL" not in second_repair.split("Problems found:")[1]

    def test_it_stops_after_the_maximum_number_of_rounds(self, api, monkeypatch):
        monkeypatch.setattr(main, "MAX_REPAIR_ATTEMPTS", 1)
        api.script(gen(self.TWO_BUGS), gen(self.ONE_BUG), *judge())
        body = generate(api).json()
        assert body["sql"] == self.ONE_BUG  # improved once, then stopped
        assert body["confidence"]["logic_check_passed"] is False
        assert len(api.llm.calls) == 4

    def test_an_improvement_that_is_not_complete_is_still_kept(self, api):
        api.script(gen(self.TWO_BUGS), gen(self.ONE_BUG), gen(self.ONE_BUG), *judge())
        body = generate(api).json()
        assert body["sql"] == self.ONE_BUG
        assert any("NULLIF" in w for w in body["warnings"])  # the remaining problem is shown
        assert any("Corrected automatically" in w for w in body["warnings"])  # and what was fixed


class TestWithoutASchema:
    def test_a_repair_uses_the_assumed_schema(self, api):
        api.script(no_schema_gen(NULL_BUG.replace("manager_id", "id")), no_schema_gen("SELECT name FROM customers WHERE id IS NULL"), *judge())
        body = generate(api, schema_ddl=None).json()
        assert "IS NULL" in body["sql"]
        repair_system = api.llm.calls[1]["system"]
        assert "CREATE TABLE customers (id INT PRIMARY KEY, name TEXT);" in repair_system

    def test_the_no_schema_cap_and_note_still_apply_after_a_repair(self, api):
        api.script(no_schema_gen("SELECT name FROM customers WHERE id = NULL"), no_schema_gen("SELECT name FROM customers WHERE id IS NULL"), *judge())
        body = generate(api, schema_ddl=None).json()
        assert body["confidence"]["overall"] <= 0.6
        assert any("No schema was provided" in w for w in body["warnings"])
        assert body["assumed_schema"] is not None

    def test_with_an_unreadable_assumed_schema_logic_is_still_checked(self, api):
        api.script(no_schema_gen("SELECT name FROM customers WHERE id = NULL", assumed_schema="not ddl"), no_schema_gen("SELECT name FROM customers WHERE id IS NULL", assumed_schema="not ddl"), *judge())
        body = generate(api, schema_ddl=None).json()
        assert "IS NULL" in body["sql"]


class TestApiShape:
    def test_the_response_reports_the_new_check_without_changing_existing_fields(self, api):
        api.script(gen(NULL_FIXED), *judge())
        confidence = generate(api).json()["confidence"]
        assert set(confidence) == {"syntax_valid", "back_translation_alignment", "schema_check_passed", "logic_check_passed", "overall"}

    def test_a_logic_failure_lowers_the_overall_confidence(self, api):
        api.script(gen(NULL_FIXED), *judge())
        clean = generate(api).json()["confidence"]["overall"]
        api.script(gen(NULL_BUG), gen(NULL_BUG), *judge())
        broken = generate(api).json()["confidence"]["overall"]
        assert broken < clean

    def test_unsafe_sql_is_still_blocked_before_any_verification_or_repair(self, api):
        api.script(gen("DELETE FROM customers WHERE manager_id = NULL"))
        body = generate(api).json()
        assert body["guardrail_blocked"] is True
        assert len(api.llm.calls) == 1
