"""Transcript -> intent with Muse Spark Open (text only), the same model that reads the notes.

Speech recognition joins words, writes digits inside words ("አ5 መቶብር") and misspells birr as
"ber"; Muse reads through that. Code then checks the amounts, and the app reads them back to the
user before scanning, so a misheard number is caught by the user, not spoken as fact.
"""

from __future__ import annotations

import httpx

from birr.config import Settings
from birr.read.muse import _json_objects

PROMPT = """A blind or low-vision person in Ethiopia asked a cash assistant app a question by \
voice. Below is what speech recognition heard. It may join words, write digits inside words, or \
misspell words (for example "ber" for birr).

Reply with ONLY JSON:
{"lang": "am" | "om" | "en", "intent": "count" | "change" | "unknown", "paid": integer or null, \
"price": integer or null}
- lang: the language of the question: am = Amharic, om = Afaan Oromo, en = English.
- intent: "count" if they want to know how much money they are holding; "change" if they want to \
check the change they got after paying; "unknown" for anything else, or if nothing was said.
- paid: the whole birr they handed over. price: the whole birr it cost. Only for "change". Use \
null for an amount they did not say. Use null too when an amount is only partly heard, \
garbled or uncertain (for example a broken number word): never complete, round or guess an \
amount. The app will ask again.

Heard: """


class UnderstandError(RuntimeError):
    pass


def _amount(value) -> int | None:
    ok = isinstance(value, int) and not isinstance(value, bool) and 0 < value < 1_000_000
    return value if ok else None


async def from_text(client: httpx.AsyncClient, transcript: str, settings: Settings) -> dict:
    """Transcript -> {"lang", "intent", "paid", "price"} (lang None if Muse can't tell)."""
    body = {
        "model": settings.muse_model,
        "temperature": 0,
        "messages": [{"role": "user", "content": PROMPT + transcript}],
    }
    if settings.muse_reasoning_effort:
        body["reasoning_effort"] = settings.muse_reasoning_effort
    headers = {"Authorization": f"Bearer {settings.muse_key}"}
    try:
        resp = await client.post(
            settings.muse_url, json=body, headers=headers, timeout=settings.intent_timeout_s
        )
        resp.raise_for_status()
        text = resp.json()["choices"][0]["message"]["content"]
    except (httpx.HTTPError, KeyError, IndexError, TypeError, ValueError) as exc:
        raise UnderstandError(f"Muse intent call failed: {type(exc).__name__}") from exc
    found = (o for o in _json_objects(text or "") if isinstance(o, dict) and "intent" in o)
    data = next(found, None)
    if data is None:
        raise UnderstandError("no intent JSON in Muse reply")
    intent = data.get("intent")
    lang = data.get("lang")
    return {
        "lang": lang if lang in ("am", "om", "en") else None,
        "intent": intent if intent in ("count", "change") else "unknown",
        "paid": _amount(data.get("paid")),
        "price": _amount(data.get("price")),
    }
