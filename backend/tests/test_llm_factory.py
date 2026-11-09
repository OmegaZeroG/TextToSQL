import pytest

from app import config
from app.llm.factory import get_llm_provider


def test_unknown_provider_is_rejected(monkeypatch):
    monkeypatch.setattr(config, "LLM_PROVIDER", "skynet")
    with pytest.raises(ValueError, match="Unknown LLM_PROVIDER"):
        get_llm_provider()


@pytest.mark.parametrize("provider, key_attr", [
    ("groq", "GROQ_API_KEY"),
    ("openai", "OPENAI_API_KEY"),
    ("anthropic", "ANTHROPIC_API_KEY"),
    ("gemini", "GEMINI_API_KEY"),
])
def test_missing_api_key_fails_fast_with_a_clear_message(monkeypatch, provider, key_attr):
    monkeypatch.setattr(config, "LLM_PROVIDER", provider)
    monkeypatch.setattr(config, key_attr, "")
    with pytest.raises(RuntimeError, match=f"{key_attr} is not set"):
        get_llm_provider()


def test_provider_name_is_case_insensitive(monkeypatch):
    monkeypatch.setattr(config, "LLM_PROVIDER", "GROQ")
    monkeypatch.setattr(config, "GROQ_API_KEY", "")
    with pytest.raises(RuntimeError, match="GROQ_API_KEY"):
        get_llm_provider()
