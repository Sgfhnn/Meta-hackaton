import io

import pytest
from fastapi.testclient import TestClient
from PIL import Image

from birr import server
from birr.agent.decide import Note, Region


def jpeg():
    out = io.BytesIO()
    Image.new("RGB", (1600, 1200), "white").save(out, format="JPEG")
    return out.getvalue()


@pytest.fixture
def client(monkeypatch, tmp_path):
    monkeypatch.setattr(server, "TRACE_DIR", tmp_path)
    return TestClient(server.app)


def fake_sam(regions):
    async def segment(client, data, width, height):
        assert max(width, height) <= server.IMAGE_MAX_PX
        if isinstance(regions, Exception):
            raise regions
        return regions

    return segment


def fake_muse(notes):
    async def read_notes(client, data):
        return notes

    return read_notes


def post(client, **form):
    return client.post("/scan", files={"image": ("p.jpg", jpeg(), "image/jpeg")}, data=form)


def test_scan_total(client, monkeypatch):
    regions = [Region((0.1, 0.1, 0.3, 0.2), 0.97), Region((0.6, 0.6, 0.3, 0.2), 0.96)]
    notes = [Note(200, 0.95, "read"), Note(100, 0.94, "read")]
    monkeypatch.setattr(server.roboflow, "segment", fake_sam(regions))
    monkeypatch.setattr(server.muse, "read_notes", fake_muse(notes))
    body = post(client).json()
    assert body["outcome"] == "total"
    assert body["total"] == 300
    assert body["speech"]["en"] == "You have 300 birr."
    assert set(body["timing_ms"]) == {"sam", "muse", "total"}


def test_scan_sam_down_rescans(client, monkeypatch):
    monkeypatch.setattr(server.roboflow, "segment", fake_sam(RuntimeError("down")))
    monkeypatch.setattr(server.muse, "read_notes", fake_muse([Note(100, 0.9, "read")]))
    body = post(client).json()
    assert body["outcome"] == "rescan"
    assert body["total"] is None


def test_scan_bad_image(client):
    r = client.post("/scan", files={"image": ("p.jpg", b"not an image", "image/jpeg")})
    assert r.status_code == 400
    assert r.json()["error"] == "bad_request"
