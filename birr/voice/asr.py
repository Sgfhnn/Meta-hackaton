"""Speech to text with Meta Omnilingual ASR (omniASR_CTC_300M_v2, Apache 2.0). Mocked in tests.

The model runs as a small local service on the box, in its own Python environment, because it
needs an older PyTorch than MMS. Contract (docs/api.md section 1.2):
POST {ASR_URL}/transcribe?lang=amh_Ethi with the audio exactly as the app uploaded it
-> {"text": "...", "lang": "amh_Ethi", "ms": 612}.
"""

from __future__ import annotations

import asyncio
import io
import logging
import wave

import httpx

from birr.config import Settings

# Omnilingual language codes. The CTC model ignores them today; they are sent for the LLM models.
LANG_CODES = {"am": "amh_Ethi", "om": "orm_Latn", "en": "eng_Latn"}


# The app records AAC at about 16 KB per second (expo-audio HIGH_QUALITY). The CPU model takes
# about 0.25 s per second of audio when warm; give longer clips more time, capped so the whole
# /assist turn still answers inside the app's 30 s wait.
BYTES_PER_EXTRA_S = 16_000
MAX_EXTRA_S = 12.0
log = logging.getLogger(__name__)


class AsrError(RuntimeError):
    pass


def timeout_for(nbytes: int, settings: Settings) -> float:
    """ASR_TIMEOUT_S, plus a second per ~second of audio (at most MAX_EXTRA_S)."""
    return settings.asr_timeout_s + min(MAX_EXTRA_S, nbytes / BYTES_PER_EXTRA_S)


def _silence_wav(seconds: float = 0.5) -> bytes:
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(16_000)
        w.writeframes(b"\x00\x00" * int(16_000 * seconds))
    return buf.getvalue()


async def keep_warm(client: httpx.AsyncClient, settings: Settings) -> None:
    """Send the ASR service half a second of silence now and every ASR_KEEPALIVE_S, so the first
    question after a quiet spell is not the one that pays for a cold model (a 5 s clip once took
    over 10 s after minutes idle and the turn failed). Costs ~0.1 s of CPU per call."""
    if not settings.asr_url or settings.asr_keepalive_s <= 0:
        return
    clip = _silence_wav()
    while True:
        try:
            await client.post(
                f"{settings.asr_url}/transcribe",
                params={"lang": LANG_CODES["en"]},
                content=clip,
                headers={"Content-Type": "audio/wav"},
                timeout=30,
            )
        except httpx.HTTPError as exc:  # the next real call reports a down service
            log.warning("ASR keep-warm call failed: %s", type(exc).__name__)
        await asyncio.sleep(settings.asr_keepalive_s)


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
            timeout=timeout_for(len(audio), settings),
        )
        resp.raise_for_status()
        text = resp.json()["text"]
    except (httpx.HTTPError, ValueError, KeyError, TypeError) as exc:
        raise AsrError(f"ASR failed: {type(exc).__name__}") from exc
    if not isinstance(text, str):
        raise AsrError("ASR answered without text")
    return text.strip()
