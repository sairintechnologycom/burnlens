"""In-process sliding-window rate limiter.

Why: brute-force / credential-stuffing / ingest-flood protection on auth and
ingest routes. Scope is intentionally small — per-instance memory, per-IP
buckets, no Redis. Good enough for Railway's single-instance backend today.
If we ever scale to multiple replicas this will need a shared store.

Limits are applied by path prefix, not by exact route, so nested paths under
`/auth/` also count toward the auth bucket.
"""
from __future__ import annotations

import time
from collections import defaultdict, deque
from threading import Lock
from typing import Iterable

from fastapi import Request
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware


class SlidingWindowLimiter:
    def __init__(self) -> None:
        self._buckets: dict[tuple, deque] = defaultdict(deque)
        self._lock = Lock()

    def check(self, key: tuple, max_requests: int, window_seconds: int) -> bool:
        now = time.monotonic()
        cutoff = now - window_seconds
        with self._lock:
            bucket = self._buckets[key]
            while bucket and bucket[0] < cutoff:
                bucket.popleft()
            if len(bucket) >= max_requests:
                return False
            bucket.append(now)
            return True


def _client_ip(request: Request) -> str:
    # Railway appends a trusted hop to X-Forwarded-For rather than overwriting
    # it, so the rightmost entry is the closest trusted-proxy view of the real
    # client IP. Taking the first entry lets an attacker spoof their bucket by
    # sending a forged XFF header, effectively bypassing the rate limiter.
    xff = request.headers.get("x-forwarded-for", "")
    if xff:
        return xff.split(",")[-1].strip()
    return request.client.host if request.client else "unknown"


class RateLimitMiddleware(BaseHTTPMiddleware):
    """Apply (max_requests, window_seconds) caps to requests whose path
    starts with one of the configured prefixes. First-match wins.

    Rules: iterable of (path_prefix, max_requests, window_seconds).
    Requests that don't match any prefix are passed through unlimited.
    """

    def __init__(
        self,
        app,
        rules: Iterable[tuple[str, int, int]],
        limiter: SlidingWindowLimiter | None = None,
    ) -> None:
        super().__init__(app)
        self._rules = list(rules)
        self._limiter = limiter or SlidingWindowLimiter()

    async def dispatch(self, request: Request, call_next):
        path = request.url.path
        for prefix, max_req, window in self._rules:
            if path.startswith(prefix):
                key = (prefix, _client_ip(request))
                if not self._limiter.check(key, max_req, window):
                    return JSONResponse(
                        {"error": "rate_limit_exceeded", "retry_after_seconds": window},
                        status_code=429,
                        headers={"Retry-After": str(window)},
                    )
                break
        return await call_next(request)


# Default rule set wired from main.py. Tuned for BurnLens' current traffic
# patterns: auth is rare and human-driven, ingest is machine-driven but per-
# workspace (not expected to burst >10 rps per source IP).
DEFAULT_RULES: tuple[tuple[str, int, int], ...] = (
    ("/auth/login", 10, 60),
    ("/auth/signup", 5, 60),
    ("/auth/invite", 20, 60),
    ("/auth/reset-password", 3, 900),
    ("/auth/resend-verification", 3, 900),  # same budget as reset-password
    ("/v1/ingest", 600, 60),
)
