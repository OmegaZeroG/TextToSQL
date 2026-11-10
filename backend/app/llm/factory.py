import threading

from app import config
from app.llm.base import LLMProvider
from app.llm.failover import FailoverProvider

# One provider object per configuration, kept for the life of the process so that a key
# that has run out of quota stays benched between requests instead of being retried.
_cache: dict[tuple, LLMProvider] = {}
_lock = threading.Lock()


def _unique(keys: list[str]) -> list[str]:
    seen: list[str] = []
    for key in keys:
        key = key.strip()
        if key and key not in seen:
            seen.append(key)
    return seen


def get_llm_provider() -> LLMProvider:
    provider = config.LLM_PROVIDER.lower()

    if provider == "groq":
        env_name, keys = "GROQ_API_KEY", _unique([config.GROQ_API_KEY, *config.GROQ_EXTRA_KEYS])
    elif provider == "openai":
        env_name, keys = "OPENAI_API_KEY", _unique([config.OPENAI_API_KEY])
    elif provider == "anthropic":
        env_name, keys = "ANTHROPIC_API_KEY", _unique([config.ANTHROPIC_API_KEY])
    elif provider == "gemini":
        env_name, keys = "GEMINI_API_KEY", _unique([config.GEMINI_API_KEY])
    else:
        raise ValueError(f"Unknown LLM_PROVIDER: {provider}")

    if not keys:
        raise RuntimeError(f"{env_name} is not set")

    cache_key = (provider, config.LLM_MODEL, tuple(keys))
    with _lock:
        cached = _cache.get(cache_key)
        if cached is None:
            cached = _cache[cache_key] = FailoverProvider([_build(provider, key) for key in keys])
        return cached


def _build(provider: str, key: str) -> LLMProvider:
    if provider == "groq":
        from app.llm.providers import GroqProvider
        return GroqProvider(key, config.LLM_MODEL)
    if provider == "openai":
        from app.llm.providers import OpenAIProvider
        return OpenAIProvider(key, config.LLM_MODEL)
    if provider == "anthropic":
        from app.llm.providers import AnthropicProvider
        return AnthropicProvider(key, config.LLM_MODEL)
    from app.llm.providers import GeminiProvider
    return GeminiProvider(key, config.LLM_MODEL)
