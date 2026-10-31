"""Speech to text with Meta Omnilingual ASR (omniASR_CTC_300M_v2, Apache 2.0). Mocked in tests.

The model runs as a small local service on the box, in its own Python environment, because it
needs an older PyTorch than MMS. Contract (docs/api.md section 1.2):
POST {ASR_URL}/transcribe?lang=amh_Ethi with the audio exactly as the app uploaded it
-> {"text": "...", "lang": "amh_Ethi", "ms": 612}.
"""

from __future__ import annotations

import httpx

from birr.config import Settings

# Omnilingual language codes. The CTC model ignores them today; they are sent for the LLM models.
LANG_CODES = {"am": "amh_Ethi", "om": "orm_Latn", "en": "eng_Latn"}


class AsrError(RuntimeError):
    pass


async def transcribe(
    client: httpx.AsyncClient, audio: bytes, mime: str, lang: str, settings: Settings
) -> str:
    """Audio -> transcript (may be empty when nothing was said)."""
    try:
        resp = await client.post(
            f"{settings.asr_url}/transcribe",
            params={"lang": LANG_CODES.get(lang, LANG_CODES["en"])},
            content=audio,
            headers={"Content-Type": mime},
            timeout=settings.asr_timeout_s,
        )
        resp.raise_for_status()
        text = resp.json()["text"]
    except (httpx.HTTPError, ValueError, KeyError, TypeError) as exc:
        raise AsrError(f"ASR failed: {type(exc).__name__}") from exc
    if not isinstance(text, str):
        raise AsrError("ASR answered without text")
    return text.strip()
