import os

from dotenv import load_dotenv

load_dotenv()

LLM_PROVIDER = os.getenv("LLM_PROVIDER", "groq")
LLM_MODEL = os.getenv("LLM_MODEL", "openai/gpt-oss-120b")

GROQ_API_KEY = os.getenv("GROQ_API_KEY", "")
# Extra Groq keys, used in order when the one before runs out of its daily quota:
# GROQ_API_KEY2 ... GROQ_API_KEY9, and/or a comma-separated GROQ_API_KEYS.
GROQ_EXTRA_KEYS = [
    *(os.getenv(f"GROQ_API_KEY{n}", "") for n in range(2, 10)),
    *os.getenv("GROQ_API_KEYS", "").split(","),
]
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "")
ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY", "")
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "")

CORS_ORIGINS = os.getenv("CORS_ORIGINS", "*").split(",")


def _int(name: str, default: int) -> int:
    try:
        return int(os.getenv(name, default))
    except ValueError:
        return default


# Finished answers are remembered so a repeated question costs no tokens. 0 turns it off.
CACHE_MAX_ENTRIES = _int("CACHE_MAX_ENTRIES", 500)
CACHE_TTL_SECONDS = _int("CACHE_TTL_SECONDS", 24 * 3600)

# Requests that reach the LLM are limited so one visitor can't use up a free quota.
# 0 turns a limit off.
RATE_LIMIT_PER_MINUTE = _int("RATE_LIMIT_PER_MINUTE", 10)  # per client address
RATE_LIMIT_PER_HOUR = _int("RATE_LIMIT_PER_HOUR", 120)  # across everyone
# Requests per day across everyone. A question costs roughly 9,000 tokens (about three model
# calls; an estimate, not measured) and a free Groq key allows 200,000 tokens a day, so the
# default is 20 questions per key. Repeats served from the cache don't count. 0 turns it off.
_KEY_COUNT = len({k.strip() for k in [GROQ_API_KEY, *GROQ_EXTRA_KEYS] if k.strip()}) if LLM_PROVIDER.lower() == "groq" else 1
RATE_LIMIT_PER_DAY = _int("RATE_LIMIT_PER_DAY", 20 * max(1, _KEY_COUNT))
# Addresses that skip every limit (your own public IP, for the deployed site), comma-separated.
RATE_LIMIT_EXEMPT_IPS = {ip.strip() for ip in os.getenv("RATE_LIMIT_EXEMPT_IPS", "").split(",") if ip.strip()}
# Skip the limits for direct connections from this computer or its network (local development, Docker).
RATE_LIMIT_EXEMPT_LOCAL = _int("RATE_LIMIT_EXEMPT_LOCAL", 1) == 1
# How many reverse proxies sit in front of the app (Render: 1). 0 ignores X-Forwarded-For.
TRUSTED_PROXY_HOPS = _int("TRUSTED_PROXY_HOPS", 1)
