"""SAM provider setting: roboflow (default), modal (our SAM 3.1 endpoint) or off. Mocked HTTP."""

import asyncio
import json

import httpx
import pytest

from birr.config import Settings
from birr.segment import sam


def run(coro):
    return asyncio.run(coro)


def segment_with(handler, settings: Settings, width=800, height=600):
    async def go():
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            return await sam.segment(client, b"jpeg", width, height, settings)

    return run(go())


def test_provider_defaults_to_roboflow(monkeypatch):
    monkeypatch.delenv("SAM_PROVIDER", raising=False)
    monkeypatch.delenv("SAM_OFF", raising=False)
    assert Settings().sam_provider == "roboflow"


def test_sam_off_flag_still_means_off(monkeypatch):
    monkeypatch.setenv("SAM_PROVIDER", "modal")
    monkeypatch.setenv("SAM_OFF", "1")
    assert Settings().sam_provider == "off"


def test_modal_request_shape_and_regions(monkeypatch):
    monkeypatch.setenv("SAM_PROVIDER", "modal")
    monkeypatch.setenv("SAM_MODAL_URL", "https://example--birr-sam31-segment.modal.run")
    monkeypatch.setenv("SAM_MODAL_KEY", "wk-test")
    monkeypatch.setenv("SAM_MODAL_SECRET", "ws-test")
    seen = {}

    def handler(request):
        seen["url"] = str(request.url)
        seen["headers"] = request.headers
        seen["body"] = json.loads(request.content)
        dets = [
            {"box": [0, 0, 400, 300], "score": 0.91},
            {"box": [420, 10, 900, 300], "score": 0.82},  # right edge past the image: clipped
            {"box": [50, 50, 50, 80], "score": 0.7},  # zero width: dropped
        ]
        return httpx.Response(200, json={"model": "sam3.1", "detections": dets})

    regions = segment_with(handler, Settings())
    assert seen["url"] == "https://example--birr-sam31-segment.modal.run"
    assert seen["headers"]["Modal-Key"] == "wk-test"
    assert seen["headers"]["Modal-Secret"] == "ws-test"
    assert seen["body"]["prompt"] == "banknote"
    assert seen["body"]["image"]  # base64 JPEG
    assert len(regions) == 2
    assert regions[0].box == pytest.approx((0.0, 0.0, 0.5, 0.5))
    assert regions[1].box == pytest.approx((420 / 800, 10 / 600, 380 / 800, 290 / 600))
    assert regions[1].score == pytest.approx(0.82)


def test_modal_without_url_is_a_sam_error(monkeypatch):
    monkeypatch.setenv("SAM_PROVIDER", "modal")
    monkeypatch.delenv("SAM_MODAL_URL", raising=False)
    with pytest.raises(sam.SamError):
        segment_with(lambda request: httpx.Response(200, json={}), Settings())


@pytest.mark.parametrize("response", [httpx.Response(503), httpx.Response(200, text="not json")])
def test_modal_failures_raise_sam_error(monkeypatch, response):
    monkeypatch.setenv("SAM_PROVIDER", "modal")
    monkeypatch.setenv("SAM_MODAL_URL", "https://example.modal.run")
    with pytest.raises(sam.SamError):
        segment_with(lambda request: response, Settings())


def test_prompt_is_configurable_for_roboflow(monkeypatch):
    monkeypatch.delenv("SAM_PROVIDER", raising=False)
    monkeypatch.setenv("SAM_PROMPT", "paper money")
    seen = {}

    def handler(request):
        seen["body"] = json.loads(request.content)
        return httpx.Response(200, json={"prompt_results": []})

    assert segment_with(handler, Settings()) == []
    assert seen["body"]["prompts"] == [{"type": "text", "text": "paper money"}]


def test_off_provider_refuses_to_segment(monkeypatch):
    monkeypatch.setenv("SAM_PROVIDER", "off")
    with pytest.raises(sam.SamError):
        segment_with(lambda request: httpx.Response(200, json={}), Settings())


def test_health_reports_provider(client, monkeypatch):
    monkeypatch.setenv("SAM_PROVIDER", "modal")
    assert client.get("/health").json()["sam"] == "modal"
