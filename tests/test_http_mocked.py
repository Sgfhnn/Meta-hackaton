"""Reader and SAM clients against mocked HTTP (httpx.MockTransport). No network, no keys."""

import asyncio
import json

import httpx
import pytest
from conftest import synthetic_jpeg

from birr import api
from birr.config import Settings
from birr.read import muse
from birr.read.prompt import PROMPT
from birr.segment import sam


def completion(content: str) -> dict:
    return {"choices": [{"message": {"role": "assistant", "content": content}}]}


def polygon(x0, y0, x1, y1, conf=0.9):
    return {"masks": [[[x0, y0], [x1, y0], [x1, y1], [x0, y1]]], "confidence": conf}


def run(coro):
    return asyncio.run(coro)


def call_reader(handler, reader=muse.PRIMARY):
    async def go():
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            return await muse.read_notes(client, b"jpeg", Settings(), reader=reader)

    return run(go())


def test_baseten_request_shape(monkeypatch):
    monkeypatch.setenv("BASETEN_API_KEY", "test-key")
    monkeypatch.delenv("MUSE_REASONING_EFFORT", raising=False)
    seen = {}

    def handler(request: httpx.Request):
        seen["url"] = str(request.url)
        seen["auth"] = request.headers["authorization"]
        seen["body"] = json.loads(request.content)
        return httpx.Response(200, json=completion('```json\n{"notes": ["100", "50"]}\n```'))

    assert call_reader(handler) == ["100", "50"]
    assert seen["url"] == "https://inference.baseten.co/v1/chat/completions"
    assert seen["auth"] == "Bearer test-key"
    body = seen["body"]
    assert body["model"] == "meta-models/muse-spark-open-1026"
    assert body["reasoning_effort"] == "low"
    assert body["temperature"] == 0
    content = body["messages"][0]["content"]
    assert content[0]["text"] == PROMPT
    assert content[-1]["image_url"]["url"].startswith("data:image/jpeg;base64,")


def test_reasoning_effort_can_be_left_out(monkeypatch):
    monkeypatch.setenv("MUSE_REASONING_EFFORT", "")
    seen = {}

    def handler(request):
        seen["body"] = json.loads(request.content)
        return httpx.Response(200, json=completion('{"notes": ["5"]}'))

    call_reader(handler)
    assert "reasoning_effort" not in seen["body"]


def test_cline_fallback_request_and_wrapped_reply(monkeypatch):
    monkeypatch.setenv("CLINE_API_KEY", "cline-key")
    seen = {}

    def handler(request):
        seen["url"] = str(request.url)
        seen["auth"] = request.headers["authorization"]
        seen["model"] = json.loads(request.content)["model"]
        return httpx.Response(200, json={"data": completion('{"notes": ["200"]}')})

    assert call_reader(handler, reader=muse.FALLBACK) == ["200"]
    assert seen["url"] == "https://api.cline.bot/api/v1/chat/completions"
    assert seen["auth"] == "Bearer cline-key"
    assert seen["model"] == "meta/muse-spark-1.3"


@pytest.mark.parametrize(
    "response",
    [
        httpx.Response(500, json={"error": "boom"}),
        httpx.Response(200, json={"nothing": True}),
        httpx.Response(200, json=completion("I see some money.")),
    ],
)
def test_reader_failures_raise_muse_error(response):
    with pytest.raises(muse.MuseError):
        call_reader(lambda request: response)


def test_per_note_objects_are_accepted():
    text = json.dumps(
        {
            "notes": [
                {"value": 100, "status": "read"},
                {"value": 5, "status": "partial"},
                {"value": None, "status": "unclear"},
                {"value": 20},
            ]
        }
    )
    assert muse.parse_labels(text) == ["100", "unclear", "unclear", "unclear"]
    assert muse.parse_labels('{"notes": ["100 birr", "Unclear"]}') == ["100", "unclear"]


def test_prompt_has_colour_rule_and_reference_sheets():
    for fact in (
        "purple/lilac = 200, red/pink = 50, bright green = 10, periwinkle blue = 100",
        "፪፻",
        "Walia ibex",
        "Harar gate",
        "three chimneys",
        "camels",
        "Colour alone can decide a value",
        "Count a note once",
        "Never add up the notes",
    ):
        assert fact in PROMPT


def test_sam_request_and_regions(monkeypatch):
    monkeypatch.setenv("ROBOFLOW_API_KEY", "rf-key")
    seen = {}

    def handler(request):
        seen["url"] = str(request.url)
        seen["body"] = json.loads(request.content)
        preds = [polygon(0, 0, 400, 300), polygon(420, 0, 800, 300)]
        return httpx.Response(200, json={"prompt_results": [{"predictions": preds}]})

    async def go():
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            return await sam.segment(client, b"jpeg", 800, 600, Settings())

    regions = run(go())
    assert len(regions) == 2
    assert seen["url"] == "https://serverless.roboflow.com/sam3/concept_segment"
    assert seen["body"]["prompts"] == [{"type": "text", "text": "banknote"}]


def test_full_scan_over_mocked_http(client, tmp_path, monkeypatch):
    """End to end through the real reader and SAM clients, HTTP mocked at the transport."""
    (tmp_path / "clean_sheet.jpg").write_bytes(b"c")
    (tmp_path / "real_sheet.jpg").write_bytes(b"r")
    monkeypatch.setenv("REFS_DIR", str(tmp_path))
    calls = {"muse": 0, "sam": 0}
    replies = iter(['{"notes": ["200", "100"]}', '{"notes": ["100", "200"]}'])

    def handler(request):
        if "baseten" in request.url.host:
            calls["muse"] += 1
            return httpx.Response(200, json=completion(next(replies)))
        calls["sam"] += 1
        preds = [polygon(0, 0, 300, 250), polygon(400, 300, 760, 560)]
        return httpx.Response(200, json={"prompt_results": [{"predictions": preds}]})

    api.app.state.http = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    files = {"image": ("pile.jpg", synthetic_jpeg(), "image/jpeg")}
    r = client.post("/scan", data={"intent": "count", "wait": "true"}, files=files)
    assert r.status_code == 200
    body = r.json()
    assert body["outcome"] == "total"
    assert body["total"] == 300
    assert calls == {"muse": 2, "sam": 1}
