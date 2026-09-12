from app import config
from app.llm.base import LLMProvider


def get_llm_provider() -> LLMProvider:
    provider = config.LLM_PROVIDER.lower()

    if provider == "groq":
        from app.llm.providers import GroqProvider
        if not config.GROQ_API_KEY:
            raise RuntimeError("GROQ_API_KEY is not set")
        return GroqProvider(config.GROQ_API_KEY, config.LLM_MODEL)

    if provider == "openai":
        from app.llm.providers import OpenAIProvider
        if not config.OPENAI_API_KEY:
            raise RuntimeError("OPENAI_API_KEY is not set")
        return OpenAIProvider(config.OPENAI_API_KEY, config.LLM_MODEL)

    if provider == "anthropic":
        from app.llm.providers import AnthropicProvider
        if not config.ANTHROPIC_API_KEY:
            raise RuntimeError("ANTHROPIC_API_KEY is not set")
        return AnthropicProvider(config.ANTHROPIC_API_KEY, config.LLM_MODEL)

    if provider == "gemini":
        from app.llm.providers import GeminiProvider
        if not config.GEMINI_API_KEY:
            raise RuntimeError("GEMINI_API_KEY is not set")
        return GeminiProvider(config.GEMINI_API_KEY, config.LLM_MODEL)

    raise ValueError(f"Unknown LLM_PROVIDER: {provider}")
