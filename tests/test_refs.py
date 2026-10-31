"""Read B carries the two reference sheets; read A does not."""

import asyncio

import pytest

from birr.config import Settings
from birr.read import muse


def _texts(body):
    return [c.get("text") or c["type"] for c in body["messages"][0]["content"]]


def test_read_a_is_prompt_label_photo():
    body = muse.request_body(b"photo", "m", Settings())
    assert _texts(body) == [muse.PROMPT, muse.PHOTO_LABEL, "image_url"]


def test_read_b_order_matches_the_tested_request():
    body = muse.request_body(b"photo", "m", Settings(), refs=[b"clean", b"real"])
    assert _texts(body) == [
        muse.PROMPT,
        muse.REFS_INTRO,
        muse.REF_SHEETS[0][1],
        "image_url",
        muse.REF_SHEETS[1][1],
        "image_url",
        muse.PHOTO_LABEL,
        "image_url",
    ]


def test_load_refs_reads_both_sheets(tmp_path):
    (tmp_path / "clean_sheet.jpg").write_bytes(b"c")
    (tmp_path / "real_sheet.jpg").write_bytes(b"r")
    assert muse.load_refs(str(tmp_path)) == [b"c", b"r"]


def test_missing_refs_make_read_b_fail(tmp_path, monkeypatch):
    monkeypatch.setenv("REFS_DIR", str(tmp_path / "nope"))
    with pytest.raises(muse.MuseError):
        asyncio.run(muse.read_notes(None, b"photo", Settings(), with_refs=True))
