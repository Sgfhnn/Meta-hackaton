import os

from fastapi.testclient import TestClient


def test_lab_off_without_token(monkeypatch):
    monkeypatch.delenv("LAB_TOKEN", raising=False)
    import importlib

    import birr.api as api

    importlib.reload(api)
    assert TestClient(api.app).get("/lab").status_code == 404


def test_lab_needs_token(monkeypatch, tmp_path):
    monkeypatch.setenv("LAB_TOKEN", "secret")
    monkeypatch.setenv("LAB_DIR", str(tmp_path))
    import importlib

    import birr.api as api

    importlib.reload(api)
    c = TestClient(api.app)
    assert c.get("/lab").status_code == 401
    assert c.get("/lab", headers={"X-Lab-Token": "secret"}).status_code == 200
    os.environ.pop("LAB_TOKEN")
    importlib.reload(api)


def test_decide_rules():
    from birr.lab import _decide

    a = {"ok": True, "labels": ["100", "50"]}
    b = {"ok": True, "labels": ["50", "100"]}
    assert _decide([a, b], {"ok": True, "kept": 2}, True)["total"] == 150
    assert _decide([a, b], {"ok": True, "kept": 3}, True)["total"] is None
    assert _decide([a, {"ok": True, "labels": ["50", "5"]}], None, False)["total"] is None
    assert _decide([{"ok": True, "labels": ["unclear"]}], None, False)["total"] is None
