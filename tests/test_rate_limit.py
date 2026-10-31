"""Per-client rate limit on POST /scan and POST /intent (the backend URL is public)."""

import pytest
from conftest import post_scan, synthetic_jpeg
from starlette.requests import Request

from birr.ratelimit import WINDOW_S, RateLimiter, client_key
from birr.voice import localize
from birr.voice import speech as say


def request_with(headers=None, host="203.0.113.7"):
    scope = {
        "type": "http",
        "headers": [(k.lower().encode(), v.encode()) for k, v in (headers or {}).items()],
        "client": (host, 50000),
    }
    return Request(scope)


def test_window_and_limit():
    limiter = RateLimiter()
    assert all(limiter.allow("a", 3, now=t) for t in (0, 1, 2))
    assert not limiter.allow("a", 3, now=3)
    assert limiter.allow("b", 3, now=3)  # another caller has its own count
    assert limiter.allow("a", 3, now=WINDOW_S + 0.5)  # the first request has left the hour


@pytest.mark.parametrize("key", ["127.0.0.1", "::1"])
def test_localhost_and_zero_are_never_limited(key):
    limiter = RateLimiter()
    assert all(limiter.allow(key, 1, now=t) for t in range(5))
    assert all(limiter.allow("x", 0, now=t) for t in range(5))


def test_client_key_uses_the_proxys_view():
    assert client_key(request_with({"X-Forwarded-For": "1.1.1.1, 198.51.100.4"})) == "198.51.100.4"
    assert client_key(request_with({"X-Real-IP": "198.51.100.9"})) == "198.51.100.9"
    assert client_key(request_with()) == "203.0.113.7"


def test_scan_over_the_limit_is_429(client, fake, monkeypatch):
    monkeypatch.setenv("RATE_LIMIT_PER_HOUR", "2")
    fake["labels"] = ["100"]
    assert post_scan(client).status_code == 200
    first = post_scan(client, wait="false").json()  # a job: polling it is never counted
    assert client.get(f"/scan/{first['job_id']}").status_code == 200
    r = post_scan(client, lang="am")
    assert r.status_code == 429
    body = r.json()
    assert body["error"] == "rate_limited"
    assert body["speech"]["am"] == localize.render(say.RATE_LIMITED, "am")[0]
    other = {"image": ("pile.jpg", synthetic_jpeg(), "image/jpeg")}
    data = {"intent": "count", "lang": "en", "wait": "true"}
    r2 = client.post("/scan", data=data, files=other, headers={"X-Forwarded-For": "198.51.100.4"})
    assert r2.status_code == 200  # a different caller


def test_intent_counts_too(client, monkeypatch):
    monkeypatch.setenv("RATE_LIMIT_PER_HOUR", "1")
    files = {"audio": ("q.m4a", b"fake", "audio/mp4")}
    assert client.post("/intent", files=files).status_code == 501  # no voice engine, but counted
    assert client.post("/intent", files=files).status_code == 429
