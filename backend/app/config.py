import os

from dotenv import load_dotenv

load_dotenv()

LLM_PROVIDER = os.getenv("LLM_PROVIDER", "groq")
LLM_MODEL = os.getenv("LLM_MODEL", "openai/gpt-oss-120b")

GROQ_API_KEY = os.getenv("GROQ_API_KEY", "")
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "")
ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY", "")
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "")

CORS_ORIGINS = os.getenv("CORS_ORIGINS", "*").split(",")


def _int(name: str, default: int) -> int:
    try:
        return int(os.getenv(name, default))
    except ValueError:
        return default


# Requests that reach the LLM are limited so one visitor can't use up a free quota.
# 0 turns a limit off.
RATE_LIMIT_PER_MINUTE = _int("RATE_LIMIT_PER_MINUTE", 10)  # per client address
RATE_LIMIT_PER_HOUR = _int("RATE_LIMIT_PER_HOUR", 120)  # across everyone
# How many reverse proxies sit in front of the app (Render: 1). 0 ignores X-Forwarded-For.
TRUSTED_PROXY_HOPS = _int("TRUSTED_PROXY_HOPS", 1)
