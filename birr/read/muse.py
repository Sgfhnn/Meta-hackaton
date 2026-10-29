"""Muse note reader. OpenAI-compatible chat completions.

Primary reader: Muse Spark Open (meta-models/muse-spark-open-1026) on Baseten.
Optional fallback: Muse Spark 1.3 contributor via the Cline API (MUSE_FALLBACK=cline).
"""

from __future__ import annotations

import base64
import json

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


def request_body(jpeg: bytes, model: str, settings: Settings) -> dict:
    b64 = base64.b64encode(jpeg).decode()
    body = {
        "model": model,
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
    if settings.muse_reasoning_effort:
        body["reasoning_effort"] = settings.muse_reasoning_effort
    return body


async def read_notes(
    client: httpx.AsyncClient, jpeg: bytes, settings: Settings, reader: str = PRIMARY
) -> list[str]:
    url, model, key = _endpoint(settings, reader)
    headers = {"Authorization": f"Bearer {key}"}
    try:
        resp = await client.post(url, json=request_body(jpeg, model, settings), headers=headers)
        resp.raise_for_status()
        data = resp.json()
        if isinstance(data, dict) and "choices" not in data and isinstance(data.get("data"), dict):
            data = data["data"]  # the Cline API can wrap the completion in "data"
        text = data["choices"][0]["message"]["content"]
    except (httpx.HTTPError, KeyError, IndexError, TypeError, ValueError) as exc:
        raise MuseError(f"Muse call failed ({reader}): {type(exc).__name__}") from exc
    return parse_labels(text)
