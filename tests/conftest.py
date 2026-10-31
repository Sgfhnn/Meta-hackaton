import asyncio
import io

import pytest
from fastapi.testclient import TestClient
from PIL import Image

from birr import api
from birr.read import muse
from birr.segment import sam
from birr.segment.filter import Region


def synthetic_jpeg(width=1600, height=1200) -> bytes:
    """A blank generated image. No real photos in tests."""
    buf = io.BytesIO()
    Image.new("RGB", (width, height), (120, 140, 90)).save(buf, format="JPEG")
    return buf.getvalue()


def boxes(*specs):
    return [Region(box=b, score=s) for b, s in specs]


@pytest.fixture(autouse=True)
def _no_asr_keepalive(monkeypatch):
    """Tests never ping a real ASR service from the app's lifespan."""
    monkeypatch.setenv("ASR_KEEPALIVE_S", "0")


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("TRACE_DIR", str(tmp_path))
    monkeypatch.setenv("VOICE_CACHE_DIR", str(tmp_path / "voice"))
    monkeypatch.delenv("MUSE_ONLY_TOTALS", raising=False)
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)  # /intent answers 501 unless a test sets it
    monkeypatch.setenv("TTS_ENGINE", "off")  # never load MMS in tests, even where it is installed
    with TestClient(api.app) as c:
        c.trace_dir = tmp_path
        yield c


@pytest.fixture
def fake(monkeypatch):
    """Configure mocked Muse reads and SAM regions (or exceptions) for one scan.

    `labels` is returned by every Muse read. `reads` (optional) is a list consumed one per
    call, each item a label list, an exception, or ("slow", seconds, labels).
    """
    state = {"labels": [], "reads": None, "regions": [], "seen": {"readers": []}}

    async def fake_muse(client, jpeg, settings, reader="baseten", with_refs=False):
        state["seen"]["muse_jpeg"] = jpeg
        state["seen"]["readers"].append(reader)
        item = state["labels"] if state["reads"] is None else state["reads"].pop(0)
        if isinstance(item, tuple) and item[0] == "slow":
            await asyncio.sleep(item[1])
            item = item[2]
        if isinstance(item, Exception):
            raise item
        return item

    async def fake_sam(client, jpeg, width, height, settings):
        state["seen"]["size"] = (width, height)
        if state.get("sam_delay"):
            await asyncio.sleep(state["sam_delay"])
        if isinstance(state["regions"], Exception):
            raise state["regions"]
        return state["regions"]

    monkeypatch.setattr(muse, "read_notes", fake_muse)
    monkeypatch.setattr(sam, "segment", fake_sam)
    return state


def post_scan(client, **fields):
    """POST /scan with wait=true: the job runs and the result comes back in the same call."""
    data = {"intent": "count", "lang": "en", "attempt": "1", "wait": "true", **fields}
    files = {"image": ("pile.jpg", synthetic_jpeg(), "image/jpeg")}
    return client.post("/scan", data=data, files=files)
