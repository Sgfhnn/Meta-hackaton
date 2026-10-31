"""The repeat check (REPEAT_CHECK=1): two agreeing reads of one photo can share a misread of a
repeated value (Hark's 3x111 run: L04 read 465 for 365). Muse is mocked."""

import asyncio
import json

import httpx
import pytest
from conftest import post_scan

from birr.config import Settings
from birr.read import muse
from birr.voice import speech as say


@pytest.fixture
def counts(client, monkeypatch):
    """Live flags (SAM off, Muse-only totals) plus the repeat check, with a fake Muse count."""
    monkeypatch.setenv("SAM_OFF", "1")
    monkeypatch.setenv("MUSE_ONLY_TOTALS", "1")
    monkeypatch.setenv("REPEAT_CHECK", "1")
    state = {"counts": {}, "asked": []}

    async def count_notes(client, jpeg, value, settings):
        state["asked"].append(value)
        found = state["counts"].get(value)
        if isinstance(found, Exception):
            raise found
        return found

    monkeypatch.setattr(muse, "count_notes", count_notes)
    return state


def trace_of(client, body):
    return json.loads((client.trace_dir / f"{body['trace_id']}.json").read_text())


def test_off_by_default(client, fake, counts, monkeypatch):
    monkeypatch.delenv("REPEAT_CHECK")
    fake["labels"] = ["100", "100", "50"]
    body = post_scan(client).json()
    assert (body["outcome"], body["total"]) == ("total", 250)
    assert counts["asked"] == []


def test_no_repeated_value_no_extra_call(client, fake, counts):
    fake["labels"] = ["200", "100", "50"]
    body = post_scan(client).json()
    assert (body["outcome"], body["total"]) == ("total", 350)
    assert counts["asked"] == []
    assert trace_of(client, body)["repeat_check"] == {"asked": {}, "ok": True}


def test_matching_count_keeps_the_total(client, fake, counts):
    fake["labels"] = ["100", "100", "50"]
    counts["counts"] = {100: 2}
    body = post_scan(client).json()
    assert (body["outcome"], body["total"]) == ("total", 250)
    assert counts["asked"] == [100]
    check = trace_of(client, body)["repeat_check"]
    assert check["asked"] == {"100": 2} and check["counted"] == {"100": 2} and check["ok"]


def test_l04_extra_note_becomes_a_rescan(client, fake, counts):
    fake["labels"] = ["5", "100", "100", "50", "10", "200"]  # both reads: 465; truth 365
    counts["counts"] = {100: 1}
    body = post_scan(client).json()
    assert (body["outcome"], body["total"], body["change"]) == ("rescan", None, None)
    assert body["speech"]["en"] == say.RESCAN
    trace = trace_of(client, body)
    assert trace["path"] == "repeat_check_failed" and trace["outcome"] == "rescan"
    assert trace["repeat_check"]["counted"] == {"100": 1}


@pytest.mark.parametrize("found", [None, muse.MuseError("down")])
def test_a_count_it_cannot_give_is_a_rescan(client, fake, counts, found):
    fake["labels"] = ["50", "50"]
    counts["counts"] = {50: found}
    assert post_scan(client).json()["outcome"] == "rescan"


def test_every_repeated_value_is_checked(client, fake, counts):
    fake["labels"] = ["50", "50", "10", "10", "10"]
    counts["counts"] = {50: 2, 10: 3}
    assert post_scan(client).json()["total"] == 130
    assert sorted(counts["asked"]) == [10, 50]
    counts["counts"] = {50: 2, 10: 2}
    assert post_scan(client).json()["outcome"] == "rescan"


def test_change_check_is_withheld_too(client, fake, counts):
    fake["labels"] = ["100", "100"]
    counts["counts"] = {100: 1}
    body = post_scan(client, intent="change", paid="500", price="300").json()
    assert (body["outcome"], body["change"]) == ("rescan", None)


def test_last_attempt_gives_up(client, fake, counts):
    fake["labels"] = ["100", "100"]
    counts["counts"] = {100: 3}
    body = post_scan(client, attempt="3", max_attempts="3").json()
    assert body["speech"]["en"] == say.GIVE_UP


def test_count_notes_request_and_parsing(monkeypatch):
    monkeypatch.setenv("BASETEN_API_KEY", "test-key")
    replies = iter(['{"count": 2}', 'Hmm {"count": null}', '{"count": "2"}', "no json"])
    seen = {}

    def handler(request):
        seen["body"] = json.loads(request.content)
        content = next(replies)
        return httpx.Response(200, json={"choices": [{"message": {"content": content}}]})

    async def go():
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            out = [await muse.count_notes(client, b"jpeg", 100, Settings()) for _ in range(3)]
            with pytest.raises(muse.MuseError):
                await muse.count_notes(client, b"jpeg", 100, Settings())
            return out

    assert asyncio.run(go()) == [2, None, None]
    content = seen["body"]["messages"][0]["content"]
    assert content[0]["text"] == muse.COUNT_PROMPT.format(value=100, looks=muse.NOTE_LOOKS[100])
    assert "Count ONLY the 100-birr notes" in content[0]["text"]
    assert content[-1]["image_url"]["url"].startswith("data:image/jpeg;base64,")
    assert seen["body"]["model"] == "meta-models/muse-spark-open-1026"
