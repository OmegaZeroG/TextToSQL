"""Remembering finished answers so repeats cost no LLM tokens (app/cache.py, /v1/generate)."""
import pytest

from app import main
from app.cache import ResponseCache, make_key
from app.rate_limit import RateLimiter
from tests.helpers import BACK_TRANSLATION, alignment, gen

DDL = "CREATE TABLE customers (id INT PRIMARY KEY, name TEXT);"


class Clock:
    def __init__(self):
        self.now = 0.0

    def __call__(self):
        return self.now


class TestKey:
    def test_whitespace_does_not_matter(self):
        assert make_key("how  many\n customers ", DDL, "postgres", "m") == make_key(
            "how many customers", "CREATE TABLE customers (id INT PRIMARY KEY,\n   name TEXT);", "postgres", "m"
        )

    @pytest.mark.parametrize(
        "other",
        [
            ("How many customers", DDL, "postgres", "m"),  # case can change a quoted value, so it is kept
            ("how many customers", DDL.replace("name", "nom"), "postgres", "m"),
            ("how many customers", DDL, "mysql", "m"),
            ("how many customers", DDL, "postgres", "other-model"),
            ("how many customers", None, "postgres", "m"),
        ],
    )
    def test_anything_that_changes_the_answer_changes_the_key(self, other):
        assert make_key("how many customers", DDL, "postgres", "m") != make_key(*other)

    def test_question_and_schema_cannot_be_confused_by_moving_text_between_them(self):
        assert make_key("a b", "c", "postgres", "m") != make_key("a", "b c", "postgres", "m")


class TestStore:
    def test_remembers_and_forgets_after_the_ttl(self):
        clock = Clock()
        cache = ResponseCache(10, 100, clock)
        cache.put("k", "v")
        assert cache.get("k") == "v"
        clock.now += 101
        assert cache.get("k") is None
        assert len(cache) == 0

    def test_drops_the_least_recently_used_when_full(self):
        cache = ResponseCache(2, 100, Clock())
        cache.put("a", 1)
        cache.put("b", 2)
        cache.get("a")  # a is now the most recently used
        cache.put("c", 3)
        assert cache.get("b") is None
        assert cache.get("a") == 1 and cache.get("c") == 3

    @pytest.mark.parametrize("size, ttl", [(0, 100), (10, 0)])
    def test_zero_turns_it_off(self, size, ttl):
        cache = ResponseCache(size, ttl)
        cache.put("k", "v")
        assert cache.get("k") is None


@pytest.fixture
def cached_api(api, monkeypatch):
    monkeypatch.setattr(main, "cache", ResponseCache(50, 3600))
    return api


def ask(api, question="How many customers are there?", dialect="postgres", schema=DDL):
    return api.client.post("/v1/generate", json={"question": question, "schema_ddl": schema, "dialect": dialect})


GOOD = lambda: (gen("SELECT COUNT(*) FROM customers", tables_used=["customers"]), BACK_TRANSLATION, alignment(1.0))


class TestGenerateEndpoint:
    def test_the_second_identical_question_makes_no_llm_calls(self, cached_api):
        llm = cached_api.script(*GOOD())
        first = ask(cached_api)
        assert first.status_code == 200 and first.headers["x-cache"] == "MISS"
        calls = len(llm.calls)
        second = ask(cached_api)
        assert second.status_code == 200 and second.headers["x-cache"] == "HIT"
        assert len(llm.calls) == calls  # nothing was asked of the model
        assert second.json() == first.json()

    def test_a_remembered_answer_is_not_changed_by_what_the_caller_does_with_it(self, cached_api):
        cached_api.script(*GOOD())
        ask(cached_api)
        body = ask(cached_api).json()
        body["sql"] = "DROP TABLE customers"
        assert ask(cached_api).json()["sql"] == "SELECT COUNT(*) FROM customers"

    def test_a_different_question_schema_or_dialect_is_a_miss(self, cached_api):
        cached_api.script(*GOOD(), *GOOD(), *GOOD(), *GOOD())
        assert ask(cached_api).headers["x-cache"] == "MISS"
        assert ask(cached_api, question="How many customers exist?").headers["x-cache"] == "MISS"
        assert ask(cached_api, dialect="mysql").headers["x-cache"] == "MISS"
        assert ask(cached_api, schema=DDL + " CREATE TABLE t (id INT);").headers["x-cache"] == "MISS"

    def test_errors_are_not_remembered(self, cached_api):
        cached_api.script(RuntimeError("down"), *GOOD())
        assert ask(cached_api).status_code == 502
        retry = ask(cached_api)
        assert retry.status_code == 200 and retry.headers["x-cache"] == "MISS"

    def test_a_low_confidence_answer_is_not_remembered_so_asking_again_tries_again(self, cached_api):
        cached_api.script(gen("SELECT COUNT(*) FROM customers", confidence=1), BACK_TRANSLATION, alignment(0.0), *GOOD())
        first = ask(cached_api)
        assert first.json()["confidence"]["overall"] < 0.5
        assert ask(cached_api).headers["x-cache"] == "MISS"

    def test_a_blocked_statement_is_remembered_so_it_costs_nothing_to_block_again(self, cached_api):
        llm = cached_api.script(gen("DROP TABLE customers"))
        assert ask(cached_api, question="Remove customers").json()["guardrail_blocked"] is True
        calls = len(llm.calls)
        again = ask(cached_api, question="Remove customers")
        assert again.headers["x-cache"] == "HIT" and again.json()["guardrail_blocked"] is True
        assert len(llm.calls) == calls

    def test_a_remembered_answer_does_not_use_up_the_rate_limit(self, cached_api, monkeypatch):
        cached_api.script(*GOOD())
        monkeypatch.setattr(main, "limiter", RateLimiter(1, 60, 1, 3600))
        assert ask(cached_api).status_code == 200  # uses the one allowed request
        for _ in range(5):
            assert ask(cached_api).status_code == 200  # all remembered: free
        assert ask(cached_api, question="something new").status_code == 429

    def test_it_is_off_when_configured_to_zero(self, api):
        api.script(*GOOD(), *GOOD())
        assert ask(api).headers["x-cache"] == "MISS"
        assert ask(api).headers["x-cache"] == "MISS"
