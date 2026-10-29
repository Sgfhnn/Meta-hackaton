"""Scan v2: two-read agreement, SAM veto, single-read retry, hard limit, async jobs."""

import json
import time

from conftest import boxes, post_scan, synthetic_jpeg

from birr.agent.decide import reads_agree
from birr.read.muse import MuseError
from birr.segment.sam import SamError

FOUR = boxes(
    ((0.05, 0.05, 0.25, 0.2), 0.95),
    ((0.55, 0.05, 0.25, 0.2), 0.93),
    ((0.05, 0.65, 0.25, 0.2), 0.92),
    ((0.55, 0.65, 0.25, 0.2), 0.91),
)


def trace_of(client, body):
    return json.loads((client.trace_dir / f"{body['trace_id']}.json").read_text())


def fast(monkeypatch, two_read="0.15", deadline="0.6"):
    monkeypatch.setenv("TWO_READ_TIMEOUT_S", two_read)
    monkeypatch.setenv("SCAN_DEADLINE_S", deadline)


# --- agreement rule -------------------------------------------------------------------------


def test_reads_agree_is_a_multiset_check():
    assert reads_agree([["100", "50", "10"], ["10", "100", "50"]])
    assert not reads_agree([["100", "50"], ["100", "10"]])
    assert not reads_agree([["10", "10"], ["10"]])
    assert not reads_agree([["100", "unclear"], ["100", "unclear"]])
    assert reads_agree([["200"]])  # one read: every note valid
    assert not reads_agree([])


def test_two_reads_agree_and_sam_matches_gives_total(client, fake):
    fake["reads"] = [["100", "50", "10", "10"], ["10", "100", "10", "50"]]
    fake["regions"] = FOUR
    body = post_scan(client).json()
    assert body["outcome"] == "total"
    assert body["total"] == 170
    trace = trace_of(client, body)
    assert trace["mode"] == "two_read"
    assert len(trace["reads"]) == 2 and all(r["ok"] for r in trace["reads"])
    assert fake["seen"]["readers"] == ["baseten", "baseten"]


def test_reads_disagree_on_a_value_rescans(client, fake):
    # The folded-10 case: one read sees an extra note value the other does not.
    fake["reads"] = [["100", "50", "10", "10"], ["100", "50", "10", "5"]]
    fake["regions"] = FOUR
    body = post_scan(client).json()
    assert body["outcome"] == "rescan"
    assert body["total"] is None


def test_reads_disagree_on_count_rescans(client, fake):
    fake["reads"] = [["10", "10"], ["10"]]
    fake["regions"] = FOUR[:2]
    assert post_scan(client).json()["outcome"] == "rescan"


def test_sam_vetoes_two_agreeing_wrong_reads(client, fake):
    # overlap_10: both reads agreed on an extra 5 (225), SAM counted 4 notes.
    fake["reads"] = [["100", "100", "10", "10", "5"], ["5", "10", "10", "100", "100"]]
    fake["regions"] = FOUR
    body = post_scan(client).json()
    assert body["outcome"] == "guide"
    assert body["total"] is None
    assert body["hint"]["action"] == "lay_flat"


def test_sam_down_two_agreeing_reads_still_rescan_by_default(client, fake):
    fake["reads"] = [["200"], ["200"]]
    fake["regions"] = SamError("down")
    assert post_scan(client).json()["outcome"] == "rescan"


# --- single-read retry ----------------------------------------------------------------------


def test_slow_second_read_uses_the_finished_one(client, fake, monkeypatch):
    fast(monkeypatch)
    fake["reads"] = [["100", "50"], ("slow", 5, ["100", "50"])]
    fake["regions"] = FOUR[:2]
    start = time.perf_counter()
    body = post_scan(client).json()
    assert time.perf_counter() - start < 2
    assert body["outcome"] == "total"
    assert body["total"] == 150
    trace = trace_of(client, body)
    assert trace["mode"] == "single_read"
    assert trace["retry"] == {"reason": "slow", "used": "finished_read"}


def test_single_read_still_needs_sam_match(client, fake, monkeypatch):
    fast(monkeypatch)
    fake["reads"] = [["100", "50", "10"], ("slow", 5, ["100", "50", "10"])]
    fake["regions"] = FOUR[:2]
    body = post_scan(client).json()
    assert body["outcome"] == "guide"
    assert body["total"] is None


def test_single_read_never_totals_without_sam(client, fake, monkeypatch):
    fast(monkeypatch)
    monkeypatch.setenv("MUSE_ONLY_TOTALS", "true")
    fake["reads"] = [["200"], ("slow", 5, ["200"])]
    fake["regions"] = SamError("down")
    assert post_scan(client).json()["outcome"] == "rescan"


def test_one_read_fails_other_counts_as_single_read(client, fake):
    fake["reads"] = [MuseError("bad json"), ["200", "100"]]
    fake["regions"] = FOUR[:2]
    body = post_scan(client).json()
    assert body["outcome"] == "total"
    trace = trace_of(client, body)
    assert trace["mode"] == "single_read"
    assert trace["retry"]["reason"] == "read_failed"


def test_both_reads_slow_starts_one_new_read(client, fake, monkeypatch):
    fast(monkeypatch)
    fake["reads"] = [("slow", 5, ["50"]), ("slow", 5, ["50"]), ["200"]]
    fake["regions"] = FOUR[:1]
    body = post_scan(client).json()
    assert body["outcome"] == "total"
    assert body["total"] == 200
    assert fake["seen"]["readers"] == ["baseten", "baseten", "baseten"]
    assert trace_of(client, body)["retry"]["used"] == "new_read:baseten"


def test_fallback_reader_takes_the_retry_when_enabled(client, fake, monkeypatch):
    fast(monkeypatch)
    monkeypatch.setenv("MUSE_FALLBACK", "cline")
    fake["reads"] = [("slow", 5, ["50"]), ("slow", 5, ["50"]), ["200"]]
    fake["regions"] = FOUR[:1]
    body = post_scan(client).json()
    assert body["total"] == 200
    assert fake["seen"]["readers"] == ["baseten", "baseten", "cline"]


def test_every_read_fails_is_upstream_error(client, fake):
    fake["labels"] = MuseError("down")
    fake["regions"] = FOUR
    r = post_scan(client)
    assert r.status_code == 502
    assert r.json()["error"] == "upstream_error"


def test_hard_limit_holds_with_slow_sam(client, fake, monkeypatch):
    fast(monkeypatch, two_read="0.1", deadline="0.3")
    fake["labels"] = ["100"]
    fake["regions"] = FOUR[:1]
    fake["sam_delay"] = 5
    start = time.perf_counter()
    body = post_scan(client).json()
    assert time.perf_counter() - start < 1.5
    assert body["outcome"] == "rescan"  # no SAM count, so no total
    assert trace_of(client, body)["sam_error"] == "deadline"


def test_trace_has_per_scan_timings(client, fake):
    fake["labels"] = ["100", "50"]
    fake["regions"] = FOUR[:2]
    body = post_scan(client).json()
    assert set(body["timing_ms"]) == {"muse", "sam", "total"}
    timing = trace_of(client, body)["timing_ms"]
    for key in ("reads_stage", "muse_reads", "sam", "muse", "total"):
        assert key in timing
    assert len(timing["muse_reads"]) == 2


# --- async jobs -----------------------------------------------------------------------------


def start_job(client, **fields):
    data = {"intent": "count", "lang": "en", "attempt": "1", **fields}
    files = {"image": ("pile.jpg", synthetic_jpeg(), "image/jpeg")}
    return client.post("/scan", data=data, files=files)


def poll(client, job_id, timeout=5.0):
    end = time.perf_counter() + timeout
    seen = []
    while time.perf_counter() < end:
        body = client.get(f"/scan/{job_id}").json()
        seen.append(body["status"])
        if body["status"] != "pending":
            return body, seen
        time.sleep(0.05)
    raise AssertionError("job never finished")


def test_post_returns_job_then_poll_gets_result(client, fake):
    fake["reads"] = [("slow", 0.3, ["200", "100"]), ("slow", 0.3, ["100", "200"])]
    fake["regions"] = FOUR[:2]
    r = start_job(client)
    assert r.status_code == 202
    job = r.json()
    assert job["status"] == "pending"
    assert job["poll_url"] == f"/scan/{job['job_id']}"
    pending = client.get(job["poll_url"]).json()
    assert pending["status"] == "pending"
    assert pending["speech"]["en"] == "Still counting."
    body, seen = poll(client, job["job_id"])
    assert body["status"] == "done"
    assert body["result"]["outcome"] == "total"
    assert body["result"]["total"] == 300
    assert body["result"]["trace_id"] == job["job_id"]


def test_poll_error_job(client, fake):
    fake["labels"] = MuseError("down")
    fake["regions"] = FOUR
    job = start_job(client).json()
    body, _ = poll(client, job["job_id"])
    assert body["status"] == "error"
    assert body["error"] == "upstream_error"
    assert body["speech"]["en"]
    assert body["result"] is None


def test_unknown_job_is_404_with_speech(client):
    r = client.get("/scan/nope")
    assert r.status_code == 404
    assert r.json()["speech"]["en"]


def test_bad_request_is_still_synchronous(client, fake):
    r = start_job(client, intent="change", paid="500")
    assert r.status_code == 400
    assert r.json()["error"] == "bad_request"


def test_cors_env_origin(monkeypatch):
    import importlib

    from fastapi.testclient import TestClient

    monkeypatch.setenv("CORS_ORIGINS", "https://preview.example")
    import birr.api as api

    api = importlib.reload(api)
    r = TestClient(api.app).options(
        "/scan",
        headers={"Origin": "https://preview.example", "Access-Control-Request-Method": "POST"},
    )
    assert r.headers.get("access-control-allow-origin") == "https://preview.example"
    monkeypatch.delenv("CORS_ORIGINS")
    importlib.reload(api)
