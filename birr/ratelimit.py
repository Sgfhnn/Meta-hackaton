"""Per-client rate limit for the endpoints that spend model credit (POST /scan, POST /intent).

The backend URL is public (it is inside the APK), and every scan pays for Muse reads. Counts live
in memory, so run one uvicorn worker (the job store needs that anyway). Localhost is exempt, so lab
and eval runs on the box are never limited. Polling GET /scan/{id} is free and never counted.
"""

from __future__ import annotations

import time
from collections import OrderedDict, deque

from fastapi import Request

WINDOW_S = 3600.0
EXEMPT = frozenset({"127.0.0.1", "::1"})
MAX_CLIENTS = 10_000  # oldest clients are forgotten past this, so memory stays bounded


def client_key(request: Request) -> str:
    """The caller's address. Behind the box's proxy, the last X-Forwarded-For entry is the address
    the proxy itself saw (earlier entries can be forged by the caller)."""
    forwarded = request.headers.get("x-forwarded-for", "")
    if forwarded.strip():
        return forwarded.split(",")[-1].strip()
    if real := request.headers.get("x-real-ip", "").strip():
        return real
    return request.client.host if request.client else "unknown"


class RateLimiter:
    def __init__(self) -> None:
        self.hits: OrderedDict[str, deque[float]] = OrderedDict()

    def allow(self, key: str, per_hour: int, now: float | None = None) -> bool:
        """Count one request for `key`; False once it made `per_hour` in the last hour."""
        if per_hour <= 0 or key in EXEMPT:
            return True
        now = time.monotonic() if now is None else now
        recent = self.hits.setdefault(key, deque())
        self.hits.move_to_end(key)
        while recent and now - recent[0] >= WINDOW_S:
            recent.popleft()
        if len(recent) >= per_hour:
            return False
        recent.append(now)
        while len(self.hits) > MAX_CLIENTS:
            self.hits.popitem(last=False)
        return True
