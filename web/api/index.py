"""Vercel entry point for the Birr web demo.

Runs the same scan backend as the phone app (birr/api.py), as one serverless function:
- every path under /api is passed to the backend with the /api prefix removed;
- the app state the backend's lifespan would set up is created on first use, because a
  serverless function may never see a lifespan event;
- scans always run with wait=true (a poll could land on another instance);
- a small per-visitor limit keeps a public page from running up the Muse bill.
"""

from __future__ import annotations

import os
import time
from collections import defaultdict, deque
from pathlib import Path

HERE = Path(__file__).resolve().parent.parent
os.environ.setdefault("REFS_DIR", str(HERE / "refs"))
os.environ.setdefault("TRACE_DIR", "/tmp/birr-traces")
os.environ.setdefault("VOICE_CACHE_DIR", "/tmp/birr-voice")
os.environ.setdefault("TTS_ENGINE", "off")
# The live reader settings (Muse at 2048 px, SAM off, two agreeing Muse reads speak a total).
os.environ.setdefault("MUSE_MAX_PX", "2048")
os.environ.setdefault("SAM_OFF", "1")
os.environ.setdefault("MUSE_ONLY_TOTALS", "1")
os.environ.setdefault("SCAN_DEADLINE_S", "55")

import httpx  # noqa: E402
from fastapi.responses import JSONResponse  # noqa: E402

from birr.api import app as birr_app  # noqa: E402
from birr.config import get_settings  # noqa: E402
from birr.jobs import JobStore  # noqa: E402
from birr.voice.service import Voice  # noqa: E402

PER_HOUR = int(os.getenv("DEMO_SCANS_PER_HOUR", "60"))
PER_DAY_ALL = int(os.getenv("DEMO_SCANS_PER_DAY", "400"))
_hits: dict[str, deque] = defaultdict(deque)
_day: list = [time.strftime("%Y-%m-%d"), 0]


def _ready() -> None:
    state = birr_app.state
    if getattr(state, "http", None) is None:
        settings = get_settings()
        state.http = httpx.AsyncClient(timeout=settings.scan_deadline_s)
        state.jobs = JobStore()
        state.voice = Voice(settings)
        from birr.voice import assist
        state.sessions = assist.Sessions()


def _limited(ip: str) -> bool:
    now = time.time()
    today = time.strftime("%Y-%m-%d")
    if _day[0] != today:
        _day[:] = [today, 0]
    q = _hits[ip]
    while q and now - q[0] > 3600:
        q.popleft()
    if len(q) >= PER_HOUR or _day[1] >= PER_DAY_ALL:
        return True
    q.append(now)
    _day[1] += 1
    return False


async def app(scope, receive, send):
    if scope["type"] == "lifespan":
        await birr_app(scope, receive, send)
        return
    if scope["type"] != "http":
        return
    path = scope.get("path", "")
    if path.startswith("/api"):
        path = path[4:] or "/"
    if path not in ("/scan", "/health", "/phrases"):
        resp = JSONResponse({"error": "not_found"}, status_code=404)
        await resp(scope, receive, send)
        return
    _ready()
    if path == "/scan" and scope.get("method") == "POST":
        headers = dict(scope.get("headers") or [])
        ip = headers.get(b"x-forwarded-for", b"").decode().split(",")[0].strip() or "?"
        if _limited(ip):
            body = {"error": "rate_limited",
                    "speech": {"en": "The demo is busy. Please try again in a while."}}
            await JSONResponse(body, status_code=429)(scope, receive, send)
            return
    scope = dict(scope, path=path, raw_path=path.encode())
    await birr_app(scope, receive, send)
