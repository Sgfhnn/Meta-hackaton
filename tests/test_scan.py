import asyncio
import json

from conftest import boxes, post_scan

from birr.read import muse
from birr.read.muse import MuseError, parse_labels
from birr.segment.filter import filter_regions
from birr.segment.sam import SamError, regions_from_response

THREE = boxes(
    ((0.05, 0.05, 0.3, 0.2), 0.95),
    ((0.55, 0.05, 0.3, 0.2), 0.93),
    ((0.30, 0.65, 0.3, 0.2), 0.91),
)


def test_total(client, fake):
    fake["labels"] = ["200", "100", "50"]
    fake["regions"] = THREE
    r = post_scan(client)
    assert r.status_code == 200
    body = r.json()
    assert body["outcome"] == "total"
    assert body["total"] == 350
    assert body["speech"]["en"] == "You have 350 birr: one 200, one 100 and one 50."
    assert set(body["timing_ms"]) == {"muse", "sam", "total"}
    assert max(fake["seen"]["size"]) == 768  # resized server-side


def test_five_birr_is_valid(client, fake):
    fake["labels"] = ["5", "5"]
    fake["regions"] = THREE[:2]
    body = post_scan(client).json()
    assert body["total"] == 10
    assert body["speech"]["en"] == "You have 10 birr: two 5s."


def test_guide_when_sam_sees_a_covered_note(client, fake):
    fake["labels"] = ["100", "50"]
    # second note sits mostly under the first, near the user on the left
    fake["regions"] = boxes(
        ((0.05, 0.60, 0.40, 0.30), 0.95),
        ((0.10, 0.70, 0.20, 0.25), 0.80),
        ((0.60, 0.05, 0.30, 0.20), 0.90),
    )
    body = post_scan(client).json()
    assert body["outcome"] == "guide"
    assert body["total"] is None
    hint = body["hint"]
    assert hint["action"] == "slide_out"
    assert hint["position"] == "near left"
    assert hint["note_index"] is None
    assert len(body["notes"]) == 2
    assert "covered" in body["speech"]["en"]


def test_rescan_on_unclear_note(client, fake):
    fake["labels"] = ["100", "unclear"]
    fake["regions"] = THREE[:2]
    body = post_scan(client).json()
    assert body["outcome"] == "rescan"
    assert body["total"] is None
    assert body["notes"][1]["status"] == "unclear"


def test_rescan_on_not_birr(client, fake):
    fake["labels"] = ["not_birr"]
    fake["regions"] = THREE[:1]
    assert post_scan(client).json()["outcome"] == "rescan"


def test_give_up_speech_on_last_attempt(client, fake):
    fake["labels"] = ["unclear"]
    fake["regions"] = THREE[:1]
    body = post_scan(client, attempt="3").json()
    assert body["outcome"] == "rescan"
    assert "cannot count" in body["speech"]["en"]


def test_sam_down_never_guides(client, fake):
    fake["labels"] = ["200", "unclear"]
    fake["regions"] = SamError("down")
    body = post_scan(client).json()
    assert body["outcome"] == "rescan"
    assert body["hint"] is None


def test_sam_down_flag_off_rescans(client, fake, monkeypatch):
    monkeypatch.setenv("MUSE_ONLY_TOTALS", "false")
    fake["labels"] = ["200"]
    fake["regions"] = SamError("down")
    assert post_scan(client).json()["outcome"] == "rescan"


def test_sam_down_flag_on_allows_muse_total(client, fake, monkeypatch):
    monkeypatch.setenv("MUSE_ONLY_TOTALS", "true")
    fake["labels"] = ["200"]
    fake["regions"] = SamError("down")
    assert post_scan(client).json()["outcome"] == "total"


def test_sam_fewer_than_muse_lay_flat(client, fake):
    fake["labels"] = ["100", "50", "10"]
    fake["regions"] = THREE[:2]
    body = post_scan(client).json()
    assert body["outcome"] == "guide"
    assert body["hint"]["action"] == "lay_flat"
    assert len(body["notes"]) == 3
    assert "Spread the notes apart" in body["speech"]["en"]


def test_change_short(client, fake):
    fake["labels"] = ["100", "50"]
    fake["regions"] = THREE[:2]
    body = post_scan(client, intent="change", paid="500", price="300").json()
    assert body["change"] == {"expected": 200, "counted": 150, "difference": -50}
    assert "50 birr short" in body["speech"]["en"]


def test_change_correct(client, fake):
    fake["labels"] = ["200"]
    fake["regions"] = THREE[:1]
    body = post_scan(client, intent="change", paid="500", price="300").json()
    assert body["change"]["difference"] == 0
    assert body["speech"]["en"].endswith("Your change is correct.")


def test_amharic_returns_english_with_todo(client, fake):
    fake["labels"] = ["100"]
    fake["regions"] = THREE[:1]
    body = post_scan(client, lang="am").json()
    assert body["speech"]["am"] == body["speech"]["en"]
    assert "Gemini" in body["speech_todo"]


def test_error_missing_field_has_speech(client, fake):
    r = client.post("/scan", data={"intent": "count"})
    assert r.status_code == 400
    assert r.json()["error"] == "bad_request"
    assert r.json()["speech"]["en"]


def test_error_not_jpeg(client, fake):
    files = {"image": ("x.png", b"\x89PNG not really", "image/png")}
    r = client.post("/scan", data={"intent": "count", "lang": "en"}, files=files)
    assert r.status_code == 400
    assert r.json()["speech"]["en"]


def test_error_change_without_price(client, fake):
    r = post_scan(client, intent="change", paid="500")
    assert r.status_code == 400
    assert "price" in r.json()["speech"]["en"]


def test_error_muse_down_is_502(client, fake):
    fake["labels"] = MuseError("down")
    fake["regions"] = THREE
    r = post_scan(client)
    assert r.status_code == 502
    assert r.json()["error"] == "upstream_error"
    assert r.json()["speech"]["en"]


def test_deadline_gives_rescan_not_error(client, fake, monkeypatch):
    monkeypatch.setenv("SCAN_DEADLINE_S", "0.2")
    monkeypatch.setenv("TWO_READ_TIMEOUT_S", "0.1")

    async def slow(*args, **kwargs):
        await asyncio.sleep(1)

    monkeypatch.setattr(muse, "read_notes", slow)
    r = post_scan(client)
    assert r.status_code == 200
    body = r.json()
    assert body["outcome"] == "rescan"
    assert body["total"] is None
    assert "too long" in body["speech"]["en"]


def test_trace_written_without_image(client, fake):
    fake["labels"] = ["50"]
    fake["regions"] = THREE[:1]
    body = post_scan(client).json()
    path = client.trace_dir / f"{body['trace_id']}.json"
    trace = json.loads(path.read_text())
    assert trace["outcome"] == "total"
    assert "base64" not in path.read_text() and "jpeg" not in json.dumps(trace).lower()


def test_intent_needs_audio(client):
    # The spoken question is required; without Gemini an upload gets 501 (tests/test_voice.py).
    r = client.post("/intent", data={"lang": "en"})
    assert r.status_code == 400
    assert r.json()["speech"]["en"]


def test_parse_labels_robust():
    assert parse_labels('Sure!\n```json\n{"notes": ["100", "50"]}\n```') == ["100", "50"]
    assert parse_labels('{"notes": [200, "Unclear"]}') == ["200", "unclear"]


def test_filter_and_polygons():
    data = {
        "prompt_results": [
            {
                "predictions": [
                    {"masks": [[[0, 0], [400, 0], [400, 300], [0, 300]]], "confidence": 0.9},
                    {"masks": [[[5, 5], [395, 5], [395, 295], [5, 295]]], "confidence": 0.8},
                    {"masks": [[[500, 500], [510, 500], [510, 510]]], "confidence": 0.95},
                    {"masks": [[[600, 0], [800, 0], [800, 300]]], "confidence": 0.4},
                ]
            }
        ]
    }
    regions = regions_from_response(data, 800, 600)
    kept, decisions = filter_regions(regions)
    assert len(kept) == 1
    reasons = sorted(d["reason"] for d in decisions if not d["kept"])
    assert reasons == ["duplicate", "low_score", "small_area"]
