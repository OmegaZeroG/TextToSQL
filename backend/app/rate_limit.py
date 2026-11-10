"""Protects the LLM quota. Every request that reaches the model costs tokens on a free
tier shared by everyone, so two limits apply to the endpoints that call it:

* per client: a burst of requests from one address can't use the quota up alone;
* global, per hour and per day: even if many addresses (or a spoofed header) get past
  the first limit, the total stays under a ceiling. The daily one is sized to what the
  provider's free quota can actually pay for.

The owner's own machine can be exempt from all of these (see `is_exempt`).

State is in memory and per process, which is right for a single free-tier instance.
A limit of 0 turns that limit off.
"""
import ipaddress
import threading
import time
from collections import deque
from collections.abc import Callable

from fastapi import HTTPException, Request

MAX_TRACKED_CLIENTS = 10_000


class SlidingWindow:
    """At most `limit` events per `window` seconds for each key."""

    def __init__(self, limit: int, window: float, clock: Callable[[], float] = time.monotonic):
        self.limit = limit
        self.window = window
        self._clock = clock
        self._events: dict[str, deque[float]] = {}
        self._lock = threading.Lock()

    def hit(self, key: str) -> float | None:
        """Record an event. Returns None if allowed, else seconds until one would be."""
        if self.limit <= 0:
            return None
        now = self._clock()
        with self._lock:
            events = self._events.setdefault(key, deque())
            while events and events[0] <= now - self.window:
                events.popleft()
            if len(events) >= self.limit:
                return max(0.0, events[0] + self.window - now)
            events.append(now)
            if len(self._events) > MAX_TRACKED_CLIENTS:
                self._prune(now)
            return None

    def _prune(self, now: float) -> None:
        for key in [k for k, e in self._events.items() if not e or e[-1] <= now - self.window]:
            del self._events[key]


class RateLimiter:
    def __init__(
        self,
        per_client: int,
        per_client_window: float,
        overall: int,
        overall_window: float,
        proxy_hops: int = 1,
        clock: Callable[[], float] = time.monotonic,
        daily: int = 0,
        exempt_ips: frozenset[str] | set[str] = frozenset(),
        exempt_local: bool = False,
    ):
        self._client = SlidingWindow(per_client, per_client_window, clock)
        self._overall = SlidingWindow(overall, overall_window, clock)
        self._daily = SlidingWindow(daily, 24 * 3600, clock)
        self._proxy_hops = proxy_hops
        self._exempt_ips = set(exempt_ips)
        self._exempt_local = exempt_local

    def client_id(self, request: Request) -> str:
        """The caller's address. Behind a proxy the real address is the entry the
        proxy appended to X-Forwarded-For; earlier entries are supplied by the caller
        and can be forged, so they are never used."""
        forwarded = [p.strip() for p in request.headers.get("x-forwarded-for", "").split(",") if p.strip()]
        if self._proxy_hops > 0 and len(forwarded) >= self._proxy_hops:
            return forwarded[-self._proxy_hops]
        return request.client.host if request.client else "unknown"

    def is_exempt(self, request: Request) -> bool:
        """True for the owner's own machine: an address listed in RATE_LIMIT_EXEMPT_IPS, or
        (when enabled) a direct connection from this computer or its local network, as in
        local development and Docker. A request that went through a proxy never counts as
        local, however it got there: behind Render every caller arrives from a private
        address, and treating that as "local" would exempt the whole internet."""
        if self.client_id(request) in self._exempt_ips:
            return True
        if not self._exempt_local or request.headers.get("x-forwarded-for"):
            return False
        host = request.client.host if request.client else ""
        try:
            address = ipaddress.ip_address(host)
        except ValueError:
            return False
        return address.is_loopback or address.is_private

    def enforce(self, request: Request) -> None:
        if self.is_exempt(request):
            return
        wait = self._client.hit(self.client_id(request))
        if wait is not None:
            self._reject("You're sending requests too quickly.", wait)
        wait = self._overall.hit("*")
        if wait is not None:
            self._reject("The free demo has hit its hourly usage limit.", wait)
        wait = self._daily.hit("*")
        if wait is not None:
            self._reject("The free demo has reached its daily limit.", wait)

    @staticmethod
    def _reject(message: str, wait: float) -> None:
        seconds = max(1, int(wait) + 1)
        if seconds < 90:
            when = f"{seconds} seconds"
        elif seconds < 90 * 60:
            when = f"{round(seconds / 60)} minutes"
        else:
            when = f"{round(seconds / 3600)} hours"
        raise HTTPException(
            status_code=429,
            detail=f"{message} Please try again in about {when}.",
            headers={"Retry-After": str(seconds)},
        )
