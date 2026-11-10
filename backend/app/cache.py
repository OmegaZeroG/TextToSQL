"""Remembers finished answers so a repeated question costs no LLM tokens.

The key is the question, the schema and the dialect (whitespace-normalised) plus the
model name, so changing any of them is a miss. Entries expire, the cache holds a
bounded number of them (least recently used goes first), and it lives in memory, so
it is per process and empty after a restart. A size of 0 turns it off.
"""
import hashlib
import threading
import time
from collections import OrderedDict
from collections.abc import Callable

# Bump when prompts or checks change in a way that should invalidate remembered answers.
CACHE_VERSION = 1


def _squash(text: str | None) -> str:
    return " ".join((text or "").split())


def make_key(question: str, schema_ddl: str | None, dialect: str, model: str) -> str:
    parts = (str(CACHE_VERSION), model, dialect, _squash(schema_ddl), _squash(question))
    return hashlib.sha256("\x1f".join(parts).encode("utf-8")).hexdigest()


class ResponseCache:
    def __init__(self, max_entries: int, ttl_seconds: float, clock: Callable[[], float] = time.monotonic):
        self.max_entries = max_entries
        self.ttl = ttl_seconds
        self._clock = clock
        self._items: OrderedDict[str, tuple[float, object]] = OrderedDict()
        self._lock = threading.Lock()

    @property
    def enabled(self) -> bool:
        return self.max_entries > 0 and self.ttl > 0

    def get(self, key: str):
        if not self.enabled:
            return None
        with self._lock:
            entry = self._items.get(key)
            if entry is None:
                return None
            stored_at, value = entry
            if self._clock() - stored_at > self.ttl:
                del self._items[key]
                return None
            self._items.move_to_end(key)
            return value

    def put(self, key: str, value) -> None:
        if not self.enabled:
            return
        with self._lock:
            self._items[key] = (self._clock(), value)
            self._items.move_to_end(key)
            while len(self._items) > self.max_entries:
                self._items.popitem(last=False)

    def __len__(self) -> int:
        return len(self._items)
