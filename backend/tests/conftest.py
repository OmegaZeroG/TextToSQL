import pytest
from fastapi.testclient import TestClient

from app import main
from app.rate_limit import RateLimiter
from tests.helpers import FakeLLM


class ApiHarness:
    def __init__(self):
        self.client = TestClient(main.app)
        self.llm = None

    def script(self, *responses):
        self.llm = FakeLLM(responses)
        return self.llm


@pytest.fixture
def api(monkeypatch):
    """FastAPI client with the LLM replaced by a scripted fake, so the whole
    request pipeline runs with no network."""
    harness = ApiHarness()
    monkeypatch.setattr(main, "get_llm_provider", lambda: harness.llm)
    # Limits are off here so tests can make as many calls as they like; test_rate_limit.py turns them on.
    monkeypatch.setattr(main, "limiter", RateLimiter(0, 60, 0, 3600))
    return harness
