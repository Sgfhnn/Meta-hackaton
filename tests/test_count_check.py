"""COUNT_CHECK: one narrow Muse count per repeated denomination before a total is spoken."""

import asyncio
import json

import httpx
import pytest
from conftest import post_scan

from birr.agent.decide import decide
from birr.config import Settings
from birr.read import muse
from birr.read.muse import MuseError, parse_count
from birr.read.prompt import COUNT_PROMPT
from birr.scan import repeated_denominations


def trace_of(client, body):
    return json.loads((client.trace_dir / f"{body['trace_id']}.json").read_text())


@pytest.fixture
def counts(monkeypatch, fake):
    """Mock the count calls: state["counts"][d] is an int, an exception or ("slow", s, int)."""
    state = {"counts": {}, "asked": []}

    async def fake_count(client, jpeg, settings, denomination):
        state["asked"].append(denomination)
        item = state["counts"][denomination]
        if isinstance(item, tuple) and item[0] == "slow":
            await asyncio.sleep(item[1])
            item = item[2]
        if isinstance(item, Exception):
            raise item
        return item

    monkeypatch.setattr(muse, "count_notes", fake_count)
    monkeypatch.setenv("SAM_OFF", "1")
    monkeypatch.setenv("MUSE_ONLY_TOTALS", "1")
    monkeypatch.setenv("COUNT_CHECK", "1")
    return state


# --- parsing --------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("text", "d", "want"),
    [
        ("2", 100, 2),
        (" 1\n", 50, 1),
        ("2.", 100, 2),
        ("**3**", 10, 3),
        ('{"count": 2}', 100, 2),
        ("There are two notes.", 100, 2),
        ("100-birr notes: 1", 100, 1),
        ("I see 2 notes of 50 birr", 50, 2),
        ("Answer: 2 (two 100 notes)", 100, 2),
        ("5", 5, 5),
        ("There are 3 5-birr notes", 5, 3),
        ("0", 200, 0),
    ],
)
def test_parse_count_reads_one_integer(text, d, want):
    assert parse_count(text, d) == want


@pytest.mark.parametrize("text", ["", "many", "1 or 2", "2.5", '{"count": "two"} or 3 4'])
def test_parse_count_refuses_unclear_replies(text):
    with pytest.raises(MuseError):
        parse_count(text, 100)


def test_repeated_denominations():
    assert repeated_denominations(["5", "100", "100", "50", "10", "200"]) == {100: 2}
    assert repeated_denominations(["10", "50", "50", "50"]) == {50: 3}
    assert repeated_denominations(["10", "50", "100"]) == {}
    assert repeated_denominations(["10", "10", "50", "50"]) == {10: 2, 50: 2}


def test_count_prompt_text():
    assert COUNT_PROMPT.format(d=100).startswith(
        "How many 100-birr notes are in this photo? Count whole physical notes, not pieces or "
        "layers."
    )


def test_count_notes_request_and_parse():
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["body"] = json.loads(request.content)
        return httpx.Response(200, json={"choices": [{"message": {"content": "1"}}]})

    async def run():
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            return await muse.count_notes(client, b"jpeg", Settings(), 100)

    assert asyncio.run(run()) == 1
    content = seen["body"]["messages"][0]["content"]
    assert content[0]["text"].startswith("How many 100-birr notes")
    assert content[1]["type"] == "image_url"
    assert seen["body"]["temperature"] == 0


def test_count_notes_http_error_is_muse_error():
    def handler(request):
        return httpx.Response(500)

    async def run():
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            return await muse.count_notes(client, b"jpeg", Settings(), 50)

    with pytest.raises(MuseError):
        asyncio.run(run())


# --- decision -------------------------------------------------------------------------------


def test_decide_mismatch_turns_total_into_rescan():
    args = dict(intent="count", paid=None, price=None, attempt=1, max_attempts=3,
                muse_only_totals=True)  # fmt: skip
    reads = [["10", "50", "50"], ["50", "10", "50"]]
    assert decide(reads, None, **args)["outcome"] == "total"
    assert decide(reads, None, count_check_ok=True, **args)["outcome"] == "total"
    out = decide(reads, None, count_check_ok=False, **args)
    assert out["outcome"] == "rescan" and out["total"] is None
    assert out["path"] == "count_check_mismatch"


# --- end to end (mocked Muse) ---------------------------------------------------------------

L04 = [["5", "100", "100", "50", "10", "200"], ["100", "5", "50", "100", "200", "10"]]
L03 = [["10", "50", "50", "50"], ["50", "10", "50", "50"]]


def test_l04_over_split_is_caught(client, fake, counts):
    fake["reads"] = [list(r) for r in L04]
    counts["counts"] = {100: 1}
    body = post_scan(client).json()
    assert body["outcome"] == "rescan" and body["total"] is None
    trace = trace_of(client, body)
    assert trace["path"] == "count_check_mismatch"
    cc = trace["count_check"]
    assert cc["ok"] is False and cc["calls"] == 1
    assert cc["checks"][0] == {**cc["checks"][0], "denomination": 100, "expected": 2, "count": 1}
    assert "count_check" in trace["timing_ms"]


def test_l03_over_split_is_caught(client, fake, counts):
    fake["reads"] = [list(r) for r in L03]
    counts["counts"] = {50: 2}
    body = post_scan(client).json()
    assert body["outcome"] == "rescan"
    assert counts["asked"] == [50]


def test_matching_counts_speak_the_total(client, fake, counts):
    fake["reads"] = [list(r) for r in L04]
    counts["counts"] = {100: 2}
    body = post_scan(client).json()
    assert body["outcome"] == "total" and body["total"] == 465
    assert trace_of(client, body)["count_check"]["ok"] is True


def test_one_call_per_repeated_denomination_all_must_match(client, fake, counts):
    fake["reads"] = [["10", "10", "50", "50"], ["50", "10", "50", "10"]]
    counts["counts"] = {10: 2, 50: 1}
    body = post_scan(client).json()
    assert body["outcome"] == "rescan"
    assert sorted(counts["asked"]) == [10, 50]
    checks = trace_of(client, body)["count_check"]["checks"]
    assert [c["ok"] for c in checks] == [True, False]


def test_no_repeats_no_extra_call(client, fake, counts):
    fake["reads"] = [["10", "50", "100"], ["100", "10", "50"]]
    body = post_scan(client).json()
    assert body["outcome"] == "total" and body["total"] == 160
    assert counts["asked"] == []
    assert "count_check" not in trace_of(client, body)


def test_failed_count_call_rescans(client, fake, counts):
    fake["reads"] = [list(r) for r in L03]
    counts["counts"] = {50: MuseError("no single count in Muse reply")}
    body = post_scan(client).json()
    assert body["outcome"] == "rescan"
    check = trace_of(client, body)["count_check"]["checks"][0]
    assert check["ok"] is False and "error" in check


def test_count_past_deadline_rescans(client, fake, counts, monkeypatch):
    monkeypatch.setenv("SCAN_DEADLINE_S", "0.3")
    fake["reads"] = [list(r) for r in L03]
    counts["counts"] = {50: ("slow", 2.0, 3)}
    body = post_scan(client).json()
    assert body["outcome"] == "rescan"
    assert trace_of(client, body)["count_check"]["checks"][0]["error"] == "deadline"


def test_disagreeing_reads_cost_no_count_call(client, fake, counts):
    fake["reads"] = [["10", "50", "50"], ["10", "50", "100"]]
    assert post_scan(client).json()["outcome"] == "rescan"
    assert counts["asked"] == []


def test_flag_off_by_default(client, fake, counts, monkeypatch):
    monkeypatch.delenv("COUNT_CHECK")
    fake["reads"] = [list(r) for r in L04]
    counts["counts"] = {100: 1}
    body = post_scan(client).json()
    assert body["outcome"] == "total" and body["total"] == 465
    assert counts["asked"] == []
