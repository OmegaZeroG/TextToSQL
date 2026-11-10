"""Rate limiting protects the shared LLM quota (app/rate_limit.py)."""
import pytest
from fastapi import HTTPException

from app import main
from app.rate_limit import RateLimiter, SlidingWindow


class Clock:
    def __init__(self):
        self.now = 1000.0

    def __call__(self):
        return self.now


class TestSlidingWindow:
    def test_allows_up_to_the_limit_then_refuses(self):
        window = SlidingWindow(3, 60, Clock())
        assert [window.hit("a") for _ in range(3)] == [None, None, None]
        assert window.hit("a") is not None

    def test_each_key_has_its_own_allowance(self):
        window = SlidingWindow(1, 60, Clock())
        assert window.hit("a") is None
        assert window.hit("b") is None
        assert window.hit("a") is not None

    def test_the_wait_is_how_long_until_the_oldest_request_expires(self):
        clock = Clock()
        window = SlidingWindow(2, 60, clock)
        window.hit("a")
        clock.now += 10
        window.hit("a")
        clock.now += 20
        assert window.hit("a") == pytest.approx(30)

    def test_requests_are_allowed_again_once_the_window_passes(self):
        clock = Clock()
        window = SlidingWindow(1, 60, clock)
        window.hit("a")
        assert window.hit("a") is not None
        clock.now += 61
        assert window.hit("a") is None

    def test_refused_requests_do_not_extend_the_block(self):
        clock = Clock()
        window = SlidingWindow(1, 60, clock)
        window.hit("a")
        for _ in range(20):
            clock.now += 1
            window.hit("a")
        clock.now += 41  # 61s after the one request that counted
        assert window.hit("a") is None

    def test_zero_means_unlimited(self):
        window = SlidingWindow(0, 60, Clock())
        assert all(window.hit("a") is None for _ in range(1000))

    def test_idle_clients_are_forgotten_so_memory_stays_bounded(self, monkeypatch):
        import app.rate_limit as module

        monkeypatch.setattr(module, "MAX_TRACKED_CLIENTS", 5)
        clock = Clock()
        window = SlidingWindow(1, 60, clock)
        for i in range(5):
            window.hit(f"old{i}")
        clock.now += 120
        window.hit("new")
        assert len(window._events) <= 2


class TestAgainstTheApi:
    DDL = {"schema_text": "CREATE TABLE t (id INT PRIMARY KEY);", "dialect": "postgres"}

    def test_the_client_limit_returns_429_with_a_readable_message_and_retry_after(self, api, monkeypatch):
        monkeypatch.setattr(main, "limiter", RateLimiter(2, 60, 0, 3600))
        for _ in range(2):
            assert api.client.post("/v1/schema/analyze", json=self.DDL).status_code == 200
        blocked = api.client.post("/v1/schema/analyze", json=self.DDL)
        assert blocked.status_code == 429
        assert "too quickly" in blocked.json()["detail"]
        assert int(blocked.headers["retry-after"]) >= 1

    def test_the_overall_limit_applies_across_clients(self, api, monkeypatch):
        monkeypatch.setattr(main, "limiter", RateLimiter(0, 60, 2, 3600))
        for ip in ("1.1.1.1", "2.2.2.2"):
            assert api.client.post("/v1/schema/analyze", json=self.DDL, headers={"x-forwarded-for": ip}).status_code == 200
        blocked = api.client.post("/v1/schema/analyze", json=self.DDL, headers={"x-forwarded-for": "3.3.3.3"})
        assert blocked.status_code == 429 and "usage limit" in blocked.json()["detail"]

    def test_all_three_model_endpoints_are_limited(self, api, monkeypatch):
        monkeypatch.setattr(main, "limiter", RateLimiter(1, 60, 0, 3600))
        paths = {
            "/v1/schema/analyze": self.DDL,
            "/v1/generate": {"question": "q", "dialect": "postgres"},
            "/v1/schema/update": {"current_ddl": "CREATE TABLE t (id INT);", "change_text": "x", "dialect": "postgres"},
        }
        for path, body in paths.items():
            monkeypatch.setattr(main, "limiter", RateLimiter(1, 60, 0, 3600))
            api.client.post(path, json=body)  # spends the allowance (any outcome)
            assert api.client.post(path, json=body).status_code == 429, path

    def test_health_and_dialects_are_never_limited(self, api, monkeypatch):
        monkeypatch.setattr(main, "limiter", RateLimiter(1, 60, 1, 3600))
        for _ in range(5):
            assert api.client.get("/health").status_code == 200
            assert api.client.get("/v1/dialects").status_code == 200

    def test_a_rejected_request_never_reaches_the_llm(self, api, monkeypatch):
        monkeypatch.setattr(main, "limiter", RateLimiter(1, 60, 0, 3600))
        llm = api.script()  # nothing scripted: any call would fail
        api.client.post("/v1/generate", json={"question": "q", "dialect": "postgres"})
        calls_before = len(getattr(llm, "calls", []))
        assert api.client.post("/v1/generate", json={"question": "q", "dialect": "postgres"}).status_code == 429
        assert len(getattr(llm, "calls", [])) == calls_before


class TestClientAddress:
    def limiter(self, hops):
        return RateLimiter(1, 60, 0, 3600, proxy_hops=hops)

    class Req:
        def __init__(self, forwarded=None, host="10.0.0.1"):
            self.headers = {"x-forwarded-for": forwarded} if forwarded else {}
            self.client = type("C", (), {"host": host})()

    def test_without_a_proxy_header_the_socket_address_is_used(self):
        assert self.limiter(1).client_id(self.Req()) == "10.0.0.1"

    def test_the_entry_added_by_the_proxy_is_used_not_one_the_caller_made_up(self):
        # the caller sent "6.6.6.6"; the proxy appended the real address
        assert self.limiter(1).client_id(self.Req("6.6.6.6, 203.0.113.9")) == "203.0.113.9"

    def test_a_forged_header_cannot_dodge_the_limit(self):
        limiter = self.limiter(1)
        first = limiter._client.hit(limiter.client_id(self.Req("1.1.1.1, 203.0.113.9")))
        second = limiter._client.hit(limiter.client_id(self.Req("2.2.2.2, 203.0.113.9")))
        assert first is None and second is not None

    def test_with_zero_hops_the_header_is_ignored(self):
        assert self.limiter(0).client_id(self.Req("6.6.6.6", host="10.0.0.1")) == "10.0.0.1"

    def test_a_header_shorter_than_the_hop_count_falls_back_to_the_socket(self):
        assert self.limiter(2).client_id(self.Req("203.0.113.9")) == "10.0.0.1"


def test_enforce_raises_http_429():
    limiter = RateLimiter(1, 60, 0, 3600)
    request = TestClientAddress.Req()
    limiter.enforce(request)
    with pytest.raises(HTTPException) as info:
        limiter.enforce(request)
    assert info.value.status_code == 429
