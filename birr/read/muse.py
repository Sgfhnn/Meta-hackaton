"""Muse note reader. OpenAI-compatible chat completions.

Primary reader: Muse Spark Open (meta-models/muse-spark-open-1026) on Baseten.
Optional fallback: Muse Spark 1.3 contributor via the Cline API (MUSE_FALLBACK=cline).
"""

from __future__ import annotations

import base64
import json
from pathlib import Path

import httpx

from birr.config import VALID_DENOMINATIONS, Settings
from birr.read.prompt import PROMPT

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


# The repeat check (birr/scan.py, REPEAT_CHECK=1): two reads of one photo can share a misread,
# typically one extra note of a colour that appears twice. One narrow question per repeated value.
NOTE_LOOKS = {
    5: "grey-blue, the front with a green tint; a boxed 5; Ge'ez ፭; coffee picker; kudu, wild cat",
    10: "bright green; Ge'ez ፲; camels and a coffee picker; four people joining hands, mesob",
    50: "red/pink; Ge'ez ፶; tractor ploughing; factory with three chimneys",
    100: "periwinkle blue, the back mint/teal with a peach-orange cave; Ge'ez ፻; castle and "
    "obelisk; Sof Omar cave and Harar gate",
    200: "purple/lilac; Ge'ez ፪፻; white dove; Walia ibex",
}
COUNT_PROMPT = """You are checking a count for a blind user. The photo shows Ethiopian birr \
banknotes, often held in a hand, fanned, folded or overlapping.

Count ONLY the {value}-birr notes ({looks}). Count whole physical notes: a note that a fold, a \
finger or another note splits into two visible pieces is ONE note, and two layers are two notes \
only when each has its own edge. Ignore every other value.

Reply with ONLY JSON: {{"count": <whole number>}}, or {{"count": null}} if you cannot tell."""


async def count_notes(
    client: httpx.AsyncClient, jpeg: bytes, value: int, settings: Settings
) -> int | None:
    """How many `value`-birr notes Muse counts in the photo (None if it cannot tell)."""
    text = COUNT_PROMPT.format(value=value, looks=NOTE_LOOKS[value])
    content = [{"type": "text", "text": text}, {"type": "text", "text": PHOTO_LABEL}, _image(jpeg)]
    body = {
        "model": settings.muse_model,
        "temperature": 0,
        "messages": [{"role": "user", "content": content}],
    }
    if settings.muse_reasoning_effort:
        body["reasoning_effort"] = settings.muse_reasoning_effort
    headers = {"Authorization": f"Bearer {settings.muse_key}"}
    try:
        resp = await client.post(settings.muse_url, json=body, headers=headers)
        resp.raise_for_status()
        reply = resp.json()["choices"][0]["message"]["content"]
    except (httpx.HTTPError, KeyError, IndexError, TypeError, ValueError) as exc:
        raise MuseError(f"Muse count failed: {type(exc).__name__}") from exc
    for obj in _json_objects(reply or ""):
        if isinstance(obj, dict) and "count" in obj:
            count = obj["count"]
            ok = isinstance(count, int) and not isinstance(count, bool) and count >= 0
            return count if ok else None
    raise MuseError("no JSON count in Muse reply")
