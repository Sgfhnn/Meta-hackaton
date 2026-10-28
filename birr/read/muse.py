"""Muse Spark Open per-photo note reader (Baseten, OpenAI-compatible)."""

from __future__ import annotations

import base64
import json
import re

import httpx

from birr.config import Settings

PROMPT = (
    "You are counting cash for a blind user. Look at this photo. For every banknote visible, "
    "identify it. Only these are valid: Ethiopian birr notes of 5, 10, 50, 100, 200 birr. "
    'If a note is not Ethiopian birr, label it "not_birr". If you cannot tell a note\'s value '
    'with confidence, label it "unclear". Do not add totals. '
    'Reply with ONLY JSON: {"notes": [<label>, ...]}'
)

_JSON_OBJ = re.compile(r"\{.*?\}", re.DOTALL)


class MuseError(RuntimeError):
    pass


def parse_labels(text: str) -> list[str]:
    """Pull the note labels out of the model reply. Raises MuseError if none can be parsed."""
    for match in _JSON_OBJ.finditer(text or ""):
        try:
            obj = json.loads(match.group(0))
        except json.JSONDecodeError:
            continue
        notes = obj.get("notes") if isinstance(obj, dict) else None
        if isinstance(notes, list):
            return [str(n).strip().lower() for n in notes]
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
