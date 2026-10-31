"""Muse note reader. OpenAI-compatible chat completions.

Primary reader: Muse Spark Open (meta-models/muse-spark-open-1026) on Baseten.
Optional fallback: Muse Spark 1.3 contributor via the Cline API (MUSE_FALLBACK=cline).
"""

from __future__ import annotations

import base64
import json
import re
from pathlib import Path

import httpx

from birr.config import VALID_DENOMINATIONS, Settings
from birr.read.prompt import COUNT_PROMPT, PROMPT

PRIMARY = "baseten"
FALLBACK = "cline"


class MuseError(RuntimeError):
    pass


def _json_objects(text: str):
    """Yield every JSON object that starts at a '{' in the text, including nested ones.

    Taken from branch claude/knowledge-prompt (PR #9): the old regex could not read nested JSON.
    """
    decoder = json.JSONDecoder()
    for i, ch in enumerate(text):
        if ch == "{":
            try:
                obj, _ = decoder.raw_decode(text, i)
            except json.JSONDecodeError:
                continue
            yield obj


def label_for(note) -> str:
    """One Muse note -> label. Bare labels pass through; per-note objects use their value."""
    if not isinstance(note, dict):
        return str(note).strip().lower().replace("birr", "").strip()
    if str(note.get("status", "read")).strip().lower() not in ("read", ""):
        return "unclear"
    try:
        value = int(note.get("value"))
    except (TypeError, ValueError):
        return "unclear"
    return str(value) if value in VALID_DENOMINATIONS else "unclear"


def parse_labels(text: str) -> list[str]:
    """Pull the note labels out of the model reply. Raises MuseError if none can be parsed."""
    for obj in _json_objects(text or ""):
        notes = obj.get("notes") if isinstance(obj, dict) else None
        if isinstance(notes, list):
            return [label_for(n) for n in notes]
    raise MuseError("no JSON notes object in Muse reply")


def _endpoint(settings: Settings, reader: str) -> tuple[str, str, str]:
    if reader == FALLBACK:
        return settings.cline_url, settings.cline_model, settings.cline_key
    return settings.muse_url, settings.muse_model, settings.muse_key


REFS_INTRO = (
    "Reference images of Ethiopian birr notes follow. Use them to judge colours and pictures. "
    "They are NOT part of the photo to read."
)
REF_SHEETS = (
    (
        "clean_sheet.jpg",
        "Reference sheet 1: clean notes, each tile shows the front (top) and back (bottom). "
        "Each tile is labelled with its value.",
    ),
    (
        "real_sheet.jpg",
        "Reference sheet 2: real, worn notes photographed in daylight and in warm indoor light. "
        "Each tile is labelled. Note how the 100 looks pale blue with a peach cave, the worn 5 is "
        "grey-blue on whitish or yellowed paper, the 50 turns orange in warm light, and the 200 "
        "turns pink in warm light.",
    ),
)
PHOTO_LABEL = "Photo to read:"

_refs_cache: dict[str, list[bytes]] = {}


def load_refs(refs_dir: str) -> list[bytes] | None:
    """The two reference sheet JPEGs from REFS_DIR (outside the repo), or None if missing."""
    if not refs_dir:
        return None
    if refs_dir in _refs_cache:
        return _refs_cache[refs_dir]
    try:
        sheets = [(Path(refs_dir) / name).read_bytes() for name, _ in REF_SHEETS]
    except OSError:
        return None
    _refs_cache[refs_dir] = sheets
    return sheets


def _image(jpeg: bytes) -> dict:
    b64 = base64.b64encode(jpeg).decode()
    return {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{b64}"}}


def request_body(
    jpeg: bytes, model: str, settings: Settings, refs: list[bytes] | None = None
) -> dict:
    """Read A: prompt, "Photo to read:", photo. Read B adds the two reference sheets first."""
    content: list[dict] = [{"type": "text", "text": PROMPT}]
    if refs:
        content.append({"type": "text", "text": REFS_INTRO})
        for (_, caption), sheet in zip(REF_SHEETS, refs, strict=True):
            content.append({"type": "text", "text": caption})
            content.append(_image(sheet))
    content.append({"type": "text", "text": PHOTO_LABEL})
    content.append(_image(jpeg))
    body = {
        "model": model,
        "temperature": 0,
        "messages": [{"role": "user", "content": content}],
    }
    if settings.muse_reasoning_effort:
        body["reasoning_effort"] = settings.muse_reasoning_effort
    return body


async def read_notes(
    client: httpx.AsyncClient,
    jpeg: bytes,
    settings: Settings,
    reader: str = PRIMARY,
    with_refs: bool = False,
) -> list[str]:
    refs = None
    if with_refs:
        refs = load_refs(settings.refs_dir)
        if refs is None:
            # Config error: read B without its sheets would repeat read A, so it never counts.
            raise MuseError("reference sheets missing (REFS_DIR)")
    url, model, key = _endpoint(settings, reader)
    headers = {"Authorization": f"Bearer {key}"}
    try:
        resp = await client.post(
            url, json=request_body(jpeg, model, settings, refs), headers=headers
        )
        resp.raise_for_status()
        data = resp.json()
        if isinstance(data, dict) and "choices" not in data and isinstance(data.get("data"), dict):
            data = data["data"]  # the Cline API can wrap the completion in "data"
        text = data["choices"][0]["message"]["content"]
    except (httpx.HTTPError, KeyError, IndexError, TypeError, ValueError) as exc:
        raise MuseError(f"Muse call failed ({reader}): {type(exc).__name__}") from exc
    return parse_labels(text)


_WORDS = {
    "zero": 0, "none": 0, "no": 0, "one": 1, "two": 2, "three": 3, "four": 4, "five": 5,
    "six": 6, "seven": 7, "eight": 8, "nine": 9, "ten": 10,
}  # fmt: skip


def parse_count(text: str, denomination: int) -> int:
    """Pull one note count out of the reply to the count prompt. Raises MuseError if unsure.

    Accepts "2", "2.", "**2**", '{"count": 2}', "There are two notes", "100-birr notes: 2".
    A mention of the denomination itself ("100 birr", "100-birr") is not taken as the count.
    """
    raw = (text or "").strip()
    for obj in _json_objects(raw):
        if isinstance(obj, dict):
            for key in ("count", "notes", "answer", "value"):
                if isinstance(obj.get(key), int) and not isinstance(obj.get(key), bool):
                    return obj[key]
    cleaned = re.sub(rf"\b{denomination}\s*-?\s*(birr|br|ብር)", " ", raw, flags=re.I)
    numbers = {int(n) for n in re.findall(r"(?<![\d.])\d+(?![\d.]*\d)", cleaned)}
    if len(numbers) > 1:
        numbers.discard(denomination)  # "two 100 notes": the 100 names the note, not the count
    if len(numbers) == 1:
        return numbers.pop()
    if not numbers:
        words = {_WORDS[w] for w in re.findall(r"[a-z]+", cleaned.lower()) if w in _WORDS}
        if len(words) == 1:
            return words.pop()
    raise MuseError("no single count in Muse reply")


async def count_notes(
    client: httpx.AsyncClient, jpeg: bytes, settings: Settings, denomination: int
) -> int:
    """Ask Muse how many notes of one denomination the photo holds (COUNT_CHECK)."""
    url, model, key = _endpoint(settings, PRIMARY)
    content = [
        {"type": "text", "text": COUNT_PROMPT.format(d=denomination)},
        _image(jpeg),
    ]
    body = {"model": model, "temperature": 0, "messages": [{"role": "user", "content": content}]}
    if settings.muse_reasoning_effort:
        body["reasoning_effort"] = settings.muse_reasoning_effort
    try:
        resp = await client.post(url, json=body, headers={"Authorization": f"Bearer {key}"})
        resp.raise_for_status()
        text = resp.json()["choices"][0]["message"]["content"]
    except (httpx.HTTPError, KeyError, IndexError, TypeError, ValueError) as exc:
        raise MuseError(f"Muse count call failed: {type(exc).__name__}") from exc
    return parse_count(text, denomination)
