"""Muse Spark Open per-photo note reader (Baseten, OpenAI-compatible).

The prompt carries the birr knowledge pack (docs/birr-knowledge.md). Muse returns one
object per note with the signals it used; a note only counts when two signals agree.
"""

from __future__ import annotations

import base64
import json

import httpx

from birr.config import VALID_DENOMINATIONS, Settings

PROMPT = """You are counting cash for a blind user. Look at this photo of banknotes.

Ethiopian birr notes in circulation: 5, 10, 50, 100, 200.
5   = grey-blue (front has green tint); boxed "5"; Ge'ez ፭; front: coffee picker; back: kudu + wild cat; older design with a triangle mark.
10  = bright green; Ge'ez ፲; front: camels + coffee picker; back: four people joining hands + mesob basket.
50  = red/pink; Ge'ez ፶; front: tractor ploughing; back: factory with three chimneys.
100 = blue (back also teal + orange-brown cave); Ge'ez ፻; front: castle + obelisk; back: Sof Omar cave + Harar gate.
200 = purple; Ge'ez ፪፻; front: white dove; back: Walia ibex.
Every back shows the Ge'ez numeral, "ብር" and the Latin numeral in the top-right and bottom-left corners: look there first.
Lion head and Ethiopia map are on every front: they do NOT identify a note.
Count a note once even if a fold or another note splits it into two visible pieces.
A note needs two agreeing signals from: "numeral", "geez", "text", "picture", "colour". Colour alone = "unclear". An edge strip with no numeral or picture = "unclear".
A note that is not Ethiopian birr: value null, status "unclear".

Reply with ONLY JSON, one entry per physical note, and never add up the notes:
{"notes": [{"value": 100, "evidence": ["numeral", "colour"], "status": "read"}]}
"status" is "read" (sure), "partial" (covered or cut off) or "unclear"."""

SIGNALS = frozenset({"numeral", "geez", "text", "picture", "colour"})


class MuseError(RuntimeError):
    pass


def _json_objects(text: str):
    """Yield every JSON object that starts at a '{' in the text, including nested ones."""
    decoder = json.JSONDecoder()
    for i, ch in enumerate(text):
        if ch == "{":
            try:
                obj, _ = decoder.raw_decode(text, i)
            except json.JSONDecodeError:
                continue
            yield obj


def label_for(note) -> str:
    """Turn one Muse note into a label: its value if identified by two signals, else 'unclear'."""
    if not isinstance(note, dict):
        return str(note).strip().lower()  # older reply format: a bare label
    value = note.get("value")
    evidence = {str(e).strip().lower() for e in note.get("evidence") or []} & SIGNALS
    try:
        value = int(value)
    except (TypeError, ValueError):
        return "unclear"
    if note.get("status") != "read" or value not in VALID_DENOMINATIONS or len(evidence) < 2:
        return "unclear"
    return str(value)


def parse_labels(text: str) -> list[str]:
    """Pull the note labels out of the model reply. Raises MuseError if none can be parsed."""
    for obj in _json_objects(text or ""):
        notes = obj.get("notes") if isinstance(obj, dict) else None
        if isinstance(notes, list):
            return [label_for(n) for n in notes]
    raise MuseError("no JSON notes object in Muse reply")


async def read_notes(client: httpx.AsyncClient, jpeg: bytes, settings: Settings) -> list[str]:
    b64 = base64.b64encode(jpeg).decode()
    body = {
        "model": settings.muse_model,
        "temperature": 0,
        "messages": [
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": PROMPT},
                    {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{b64}"}},
                ],
            }
        ],
    }
    headers = {"Authorization": f"Bearer {settings.muse_key}"}
    try:
        resp = await client.post(settings.muse_url, json=body, headers=headers)
        resp.raise_for_status()
        text = resp.json()["choices"][0]["message"]["content"]
    except (httpx.HTTPError, KeyError, IndexError, ValueError) as exc:
        raise MuseError(f"Muse call failed: {type(exc).__name__}") from exc
    return parse_labels(text)
