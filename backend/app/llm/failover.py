"""Switches to the next API key when one runs out of quota.

Free tiers cap tokens per day per account. With several keys configured, a call that
fails because a key is out of quota (HTTP 429) or rejected (401/403) is retried on the
next key, and the failed key is skipped until its limit should have reset. Keys are
always tried in the order given, so the first one is used again as soon as it recovers.

Any other failure (a bad request, a network error, a server error) is not a reason to
change keys and is raised unchanged.
"""
import logging
import re
import threading
import time
from collections.abc import Callable

from app.llm.base import LLMProvider

log = logging.getLogger("plainquery.llm")

DEFAULT_COOLDOWN = 60.0  # a 429 that doesn't say when to retry
REJECTED_KEY_COOLDOWN = 3600.0  # a revoked or invalid key won't fix itself soon
MAX_COOLDOWN = 24 * 3600.0

_UNITS = {"ms": 0.001, "s": 1, "m": 60, "h": 3600, "d": 86400}
_RETRY_IN = re.compile(r"try again in\s+((?:\d+(?:\.\d+)?\s*(?:ms|d|h|m|s)\s*)+)", re.IGNORECASE)
_PART = re.compile(r"(\d+(?:\.\d+)?)\s*(ms|d|h|m|s)", re.IGNORECASE)


class QuotaExhausted(RuntimeError):
    """Every configured key is out of quota for now."""


def switch_wait(exc: Exception) -> float | None:
    """Seconds to leave this key alone if the error means "use another key", else None."""
    status = getattr(exc, "status_code", None)
    if status in (401, 403):
        return REJECTED_KEY_COOLDOWN
    if status != 429:
        return None
    return min(MAX_COOLDOWN, _retry_after(exc) or DEFAULT_COOLDOWN)


def _retry_after(exc: Exception) -> float | None:
    headers = getattr(getattr(exc, "response", None), "headers", None)
    try:
        value = headers.get("retry-after") if headers is not None else None
        if value is not None and float(value) > 0:
            return float(value)
    except (TypeError, ValueError, AttributeError):
        pass
    match = _RETRY_IN.search(str(exc))
    if match:
        total = sum(float(n) * _UNITS[u.lower()] for n, u in _PART.findall(match.group(1)))
        if total > 0:
            return total
    return None


def _describe(seconds: float) -> str:
    seconds = max(1, int(seconds) + 1)
    if seconds < 90:
        return f"{seconds} seconds"
    if seconds < 90 * 60:
        return f"{round(seconds / 60)} minutes"
    return f"{round(seconds / 3600)} hours"


class FailoverProvider(LLMProvider):
    def __init__(self, providers: list[LLMProvider], clock: Callable[[], float] = time.monotonic):
        if not providers:
            raise ValueError("at least one provider is required")
        self._providers = providers
        self._clock = clock
        self._resume_at = [0.0] * len(providers)
        self._lock = threading.Lock()

    def _next(self, tried: set[int]) -> int | None:
        now = self._clock()
        with self._lock:
            for i, resume in enumerate(self._resume_at):
                if i not in tried and resume <= now:
                    return i
        return None

    def _bench(self, index: int, seconds: float) -> None:
        with self._lock:
            self._resume_at[index] = self._clock() + seconds

    def _soonest(self) -> float:
        now = self._clock()
        with self._lock:
            return max(0.0, min(self._resume_at) - now)

    def complete(self, system_prompt: str, user_prompt: str, json_mode: bool = False) -> str:
        tried: set[int] = set()
        while (index := self._next(tried)) is not None:
            tried.add(index)
            try:
                return self._providers[index].complete(system_prompt, user_prompt, json_mode=json_mode)
            except Exception as exc:
                wait = switch_wait(exc)
                if wait is None:
                    raise
                self._bench(index, wait)
                remaining = len(self._providers) - len(tried)
                log.warning(
                    "LLM key #%d unavailable (HTTP %s); benched for %ds; %d other key(s) to try",
                    index + 1, getattr(exc, "status_code", "?"), wait, remaining,
                )
        raise QuotaExhausted(
            "The AI provider's free quota is used up for now. "
            f"Please try again in about {_describe(self._soonest())}."
        )
