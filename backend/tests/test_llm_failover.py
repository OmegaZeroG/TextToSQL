"""Switching to the next API key when one runs out of quota (app/llm/failover.py)."""
import pytest

from app import config
from app.llm import factory
from app.llm.base import LLMProvider
from app.llm.failover import FailoverProvider, QuotaExhausted, switch_wait


class Headers(dict):
    pass


class ApiError(Exception):
    def __init__(self, status, message="error", retry_after=None):
        super().__init__(message)
        self.status_code = status
        self.response = type("R", (), {"headers": Headers({"retry-after": str(retry_after)} if retry_after else {})})()


class Key(LLMProvider):
    """A key that answers, or raises, as scripted."""

    def __init__(self, name, *outcomes):
        self.name = name
        self.outcomes = list(outcomes)
        self.calls = 0

    def complete(self, system_prompt, user_prompt, json_mode=False):
        self.calls += 1
        outcome = self.outcomes.pop(0) if self.outcomes else f"ok from {self.name}"
        if isinstance(outcome, Exception):
            raise outcome
        return outcome


class Clock:
    def __init__(self):
        self.now = 1000.0

    def __call__(self):
        return self.now


def ask(provider):
    return provider.complete("system", "user")


class TestSwitching:
    def test_uses_the_first_key_while_it_works(self):
        a, b = Key("a"), Key("b")
        assert ask(FailoverProvider([a, b])) == "ok from a"
        assert (a.calls, b.calls) == (1, 0)

    def test_a_429_moves_the_same_request_to_the_next_key(self):
        a, b = Key("a", ApiError(429)), Key("b")
        assert ask(FailoverProvider([a, b])) == "ok from b"
        assert (a.calls, b.calls) == (1, 1)

    def test_a_rejected_key_is_skipped_too(self):
        a, b = Key("a", ApiError(401)), Key("b")
        assert ask(FailoverProvider([a, b])) == "ok from b"

    def test_a_key_that_ran_out_is_not_tried_again_until_its_limit_resets(self):
        clock = Clock()
        a, b = Key("a", ApiError(429, retry_after=600)), Key("b")
        provider = FailoverProvider([a, b], clock)
        ask(provider)
        ask(provider)
        ask(provider)
        assert (a.calls, b.calls) == (1, 3)
        clock.now += 601
        assert ask(provider) == "ok from a"  # back to the first key as soon as it recovers

    def test_walks_through_every_key_in_order(self):
        keys = [Key("a", ApiError(429)), Key("b", ApiError(429)), Key("c", ApiError(429)), Key("d")]
        assert ask(FailoverProvider(keys)) == "ok from d"
        assert [k.calls for k in keys] == [1, 1, 1, 1]

    def test_other_errors_are_raised_and_do_not_burn_a_key(self):
        a, b = Key("a", ApiError(400, "bad request")), Key("b")
        provider = FailoverProvider([a, b])
        with pytest.raises(ApiError):
            ask(provider)
        assert b.calls == 0
        assert ask(provider) == "ok from a"  # a was not benched

    @pytest.mark.parametrize("error", [ApiError(500), ApiError(503), ConnectionError("down"), ValueError("x")])
    def test_server_and_network_errors_do_not_switch_keys(self, error):
        a, b = Key("a", error), Key("b")
        with pytest.raises(type(error)):
            ask(FailoverProvider([a, b]))
        assert b.calls == 0

    def test_json_mode_is_passed_through(self):
        seen = []

        class Spy(LLMProvider):
            def complete(self, system_prompt, user_prompt, json_mode=False):
                seen.append(json_mode)
                return "x"

        FailoverProvider([Spy()]).complete("s", "u", json_mode=True)
        assert seen == [True]

    def test_needs_at_least_one_key(self):
        with pytest.raises(ValueError):
            FailoverProvider([])


class TestWhenEverythingIsUsedUp:
    def test_raises_a_friendly_error_that_says_when_to_come_back(self):
        keys = [Key("a", ApiError(429, retry_after=1200)), Key("b", ApiError(429, retry_after=3000))]
        with pytest.raises(QuotaExhausted) as info:
            ask(FailoverProvider(keys))
        assert "quota is used up" in str(info.value) and "20 minutes" in str(info.value)

    def test_the_message_does_not_leak_the_providers_error_text(self):
        key = Key("a", ApiError(429, "Rate limit reached for organization org_secret123 ..."))
        with pytest.raises(QuotaExhausted) as info:
            ask(FailoverProvider([key]))
        assert "org_secret123" not in str(info.value)

    def test_while_every_key_is_benched_no_request_is_sent_at_all(self):
        a = Key("a", ApiError(429, retry_after=600))
        provider = FailoverProvider([a], Clock())
        with pytest.raises(QuotaExhausted):
            ask(provider)
        with pytest.raises(QuotaExhausted):
            ask(provider)
        assert a.calls == 1

    def test_works_again_after_the_wait(self):
        clock = Clock()
        a = Key("a", ApiError(429, retry_after=60))
        provider = FailoverProvider([a], clock)
        with pytest.raises(QuotaExhausted):
            ask(provider)
        clock.now += 61
        assert ask(provider) == "ok from a"


class TestHowLongToWait:
    def test_non_switching_errors_have_no_wait(self):
        assert switch_wait(ApiError(400)) is None
        assert switch_wait(ValueError("x")) is None

    def test_uses_the_retry_after_header(self):
        assert switch_wait(ApiError(429, retry_after=42)) == 42

    @pytest.mark.parametrize(
        "text, seconds",
        [
            ("Please try again in 3m46.8s.", 226.8),
            ("Please try again in 45.2s", 45.2),
            ("Please try again in 2h5m30s", 7530),
            ("Please try again in 1h2m", 3720),
            ("Please try again in 250ms", 0.25),
        ],
    )
    def test_reads_groqs_try_again_in_text(self, text, seconds):
        assert switch_wait(ApiError(429, f"Rate limit reached. {text}")) == pytest.approx(seconds)

    def test_without_any_hint_it_waits_a_minute(self):
        assert switch_wait(ApiError(429, "slow down")) == 60

    def test_is_capped_at_a_day(self):
        assert switch_wait(ApiError(429, retry_after=10**7)) == 24 * 3600

    def test_a_rejected_key_is_benched_for_an_hour(self):
        assert switch_wait(ApiError(403)) == 3600


class TestFactory:
    def test_builds_one_failover_over_every_configured_groq_key(self, monkeypatch):
        monkeypatch.setattr(config, "LLM_PROVIDER", "groq")
        monkeypatch.setattr(config, "GROQ_API_KEY", "k1")
        monkeypatch.setattr(config, "GROQ_EXTRA_KEYS", ["k2", "", " k3 ", "k1"])
        provider = factory.get_llm_provider()
        assert isinstance(provider, FailoverProvider)
        assert len(provider._providers) == 3  # blanks and duplicates dropped

    def test_the_same_configuration_gives_the_same_object_so_benched_keys_stay_benched(self, monkeypatch):
        monkeypatch.setattr(config, "LLM_PROVIDER", "groq")
        monkeypatch.setattr(config, "GROQ_API_KEY", "k1")
        monkeypatch.setattr(config, "GROQ_EXTRA_KEYS", ["k2"])
        assert factory.get_llm_provider() is factory.get_llm_provider()

    def test_changing_the_keys_builds_a_new_one(self, monkeypatch):
        monkeypatch.setattr(config, "LLM_PROVIDER", "groq")
        monkeypatch.setattr(config, "GROQ_API_KEY", "k1")
        monkeypatch.setattr(config, "GROQ_EXTRA_KEYS", [])
        first = factory.get_llm_provider()
        monkeypatch.setattr(config, "GROQ_EXTRA_KEYS", ["k2"])
        assert factory.get_llm_provider() is not first

    def test_extra_keys_alone_are_enough(self, monkeypatch):
        monkeypatch.setattr(config, "LLM_PROVIDER", "groq")
        monkeypatch.setattr(config, "GROQ_API_KEY", "")
        monkeypatch.setattr(config, "GROQ_EXTRA_KEYS", ["k2"])
        assert len(factory.get_llm_provider()._providers) == 1
