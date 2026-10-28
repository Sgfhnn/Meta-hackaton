"""Muse Spark Open on Baseten: read every note in the photo, one entry per note.

Muse never totals. It returns a per-note list, and the backend adds it up.
"""

from __future__ import annotations

import base64
import json
import os
import re

import httpx

from birr.agent.decide import Note

PROMPT = """You are reading Ethiopian birr banknotes in a photo for a blind user.
List every banknote you can see, one entry per physical note, even if it is
partly covered. For each note give:
- "denomination": 5, 10, 50, 100 or 200, or null if you cannot tell
- "confidence": 0 to 1
- "status": "read" if fully visible and sure, "partial" if covered or cut off,
  "unclear" if you cannot read it
Do not add up the notes. Reply with JSON only, in this shape:
{"notes": [{"denomination": 100, "confidence": 0.95, "status": "read"}]}"""

MAX_TOKENS = 1500


async def read_notes(client: httpx.AsyncClient, jpeg: bytes) -> list[Note]:
    image_url = "data:image/jpeg;base64," + base64.b64encode(jpeg).decode()
    payload = {
        "model": os.environ.get("MODEL_NAME", "meta-models/muse-spark-open-1026"),
        "max_tokens": MAX_TOKENS,
        "messages": [
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": PROMPT},
                    {"type": "image_url", "image_url": {"url": image_url}},
                ],
            }
        ],
    }
    base_url = os.environ.get("MODEL_BASE_URL", "https://inference.baseten.co/v1")
    headers = {"Authorization": f"Bearer {os.environ['MODEL_API_KEY']}"}
    resp = await client.post(f"{base_url}/chat/completions", json=payload, headers=headers)
    resp.raise_for_status()
    return parse(resp.json()["choices"][0]["message"]["content"])


def parse(content: str) -> list[Note]:
    """Parse the model's JSON. Anything malformed becomes one unclear note."""
    match = re.search(r"\{.*\}", content, re.DOTALL)
    try:
        data = json.loads(match.group(0)) if match else {}
        notes = []
        for raw in data["notes"]:
            denomination = raw.get("denomination")
            status = raw.get("status")
            if status not in ("read", "partial", "unclear"):
                status = "unclear"
            notes.append(
                Note(
                    denomination=int(denomination) if denomination is not None else None,
                    confidence=float(raw.get("confidence", 0.0)),
                    status=status,
                )
            )
        return notes
    except (KeyError, TypeError, ValueError, json.JSONDecodeError):
        return [Note(denomination=None, confidence=0.0, status="unclear")]
