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


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("TRACE_DIR", str(tmp_path))
    monkeypatch.delenv("MUSE_ONLY_TOTALS", raising=False)
    with TestClient(api.app) as c:
        c.trace_dir = tmp_path
        yield c


@pytest.fixture
def fake(monkeypatch):
    """Configure mocked Muse labels and SAM regions (or exceptions) for one call."""
    state = {"labels": [], "regions": [], "seen": {}}

    async def fake_muse(client, jpeg, settings):
        state["seen"]["muse_jpeg"] = jpeg
        if isinstance(state["labels"], Exception):
            raise state["labels"]
        return state["labels"]

    async def fake_sam(client, jpeg, width, height, settings):
        state["seen"]["size"] = (width, height)
        if isinstance(state["regions"], Exception):
            raise state["regions"]
        return state["regions"]

    monkeypatch.setattr(muse, "read_notes", fake_muse)
    monkeypatch.setattr(sam, "segment", fake_sam)
    return state


def post_scan(client, **fields):
    data = {"intent": "count", "lang": "en", "attempt": "1", **fields}
    files = {"image": ("pile.jpg", synthetic_jpeg(), "image/jpeg")}
    return client.post("/scan", data=data, files=files)
