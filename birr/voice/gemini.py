"""Gemini calls for voice: speech to intent, translation, and text to speech. Mocked in tests.

Gemini never reads notes or computes totals (docs/api.md). It hears the user's question, translates
the answer the backend wrote, and speaks it. Intent and translation use generateContent with a
JSON schema. Speech uses the Interactions API, which answers with a complete WAV file.
"""

from __future__ import annotations

import base64
import io
import json
import os
import wave

import httpx

from birr.config import Settings

LANG_NAMES = {
    "am": "Amharic, in Ge'ez script",
    "om": "Afaan Oromo, in Latin (Qubee) script",
    "en": "English",
}

# Upload type -> Gemini audio MIME type. Gemini lists audio/m4a, not audio/mp4.
_BY_TYPE = {
    "audio/m4a": "audio/m4a",
    "audio/x-m4a": "audio/m4a",
    "audio/mp4": "audio/m4a",
    "audio/aac": "audio/aac",
    "audio/wav": "audio/wav",
    "audio/x-wav": "audio/wav",
    "audio/wave": "audio/wav",
    "audio/mpeg": "audio/mp3",
    "audio/mp3": "audio/mp3",
    "audio/ogg": "audio/ogg",
    "audio/webm": "audio/webm",
    "audio/flac": "audio/flac",
}
_BY_EXT = {
    ".m4a": "audio/m4a",
    ".mp4": "audio/m4a",
    ".aac": "audio/aac",
    ".wav": "audio/wav",
    ".mp3": "audio/mp3",
    ".ogg": "audio/ogg",
    ".webm": "audio/webm",
    ".flac": "audio/flac",
}

INTENT_PROMPT = """You will hear a short voice message from a blind or low-vision person in \
Ethiopia who uses a cash assistant app. They speak Amharic, Afaan Oromo or English.

Fill in:
- transcript: what they said, in the script of the language they spoke.
- lang: "am" for Amharic, "om" for Afaan Oromo, "en" for English.
- intent:
  - "count": they want to know how much money they are holding. For example "How much do I \
have?" or "ስንት ብር አለኝ?".
  - "change": they want to check the change they got after paying. For example "Is my change \
right?" or "I paid 500 for something that costs 320."
  - "unknown": anything else, silence or noise.
- paid and price, only for "change": whole birr as integers. paid is the money they handed \
over, price is what it cost. Use null for an amount they did not say. Never guess an amount."""

INTENT_SCHEMA = {
    "type": "OBJECT",
    "properties": {
        "transcript": {"type": "STRING"},
        "lang": {"type": "STRING", "enum": ["am", "om", "en"]},
        "intent": {"type": "STRING", "enum": ["count", "change", "unknown"]},
        "paid": {"type": "INTEGER", "nullable": True},
        "price": {"type": "INTEGER", "nullable": True},
    },
    "required": ["transcript", "lang", "intent", "paid", "price"],
}

TRANSLATE_SCHEMA = {
    "type": "OBJECT",
    "properties": {"texts": {"type": "ARRAY", "items": {"type": "STRING"}}},
    "required": ["texts"],
}


class GeminiError(RuntimeError):
    pass


def audio_mime(filename: str | None, content_type: str | None) -> str | None:
    """The Gemini MIME type for an upload, or None if it is not audio Gemini takes."""
    by_type = _BY_TYPE.get((content_type or "").split(";")[0].strip().lower())
    if by_type:
        return by_type
    return _BY_EXT.get(os.path.splitext(filename or "")[1].lower())


def _headers(settings: Settings) -> dict:
    return {"x-goog-api-key": settings.gemini_key}


async def _generate_json(
    client: httpx.AsyncClient, parts: list, schema: dict, settings: Settings, timeout: float
) -> dict:
    url = f"{settings.gemini_base_url}/models/{settings.gemini_model}:generateContent"
    config = {"temperature": 0, "responseMimeType": "application/json", "responseSchema": schema}
    if settings.gemini_thinking_level:
        config["thinkingConfig"] = {"thinkingLevel": settings.gemini_thinking_level}
    body = {"contents": [{"role": "user", "parts": parts}], "generationConfig": config}
    try:
        resp = await client.post(url, json=body, headers=_headers(settings), timeout=timeout)
        resp.raise_for_status()
        candidate = resp.json()["candidates"][0]
        text = "".join(p.get("text", "") for p in candidate["content"]["parts"])
        data = json.loads(text)
    except (httpx.HTTPError, ValueError, KeyError, IndexError, TypeError) as exc:
        raise GeminiError(f"generateContent failed: {type(exc).__name__}") from exc
    if not isinstance(data, dict):
        raise GeminiError("generateContent answered with no JSON object")
    return data


async def understand(
    client: httpx.AsyncClient, audio: bytes, mime: str, settings: Settings
) -> dict:
    """Speech -> {"lang", "intent", "paid", "price"}. The transcript is dropped here."""
    parts = [
        {"text": INTENT_PROMPT},
        {"inlineData": {"mimeType": mime, "data": base64.b64encode(audio).decode()}},
    ]
    data = await _generate_json(client, parts, INTENT_SCHEMA, settings, settings.gemini_timeout_s)

    def amount(value):
        ok = isinstance(value, int) and not isinstance(value, bool) and 0 < value < 1_000_000
        return value if ok else None

    intent = data.get("intent")
    return {
        "lang": data.get("lang") if data.get("lang") in LANG_NAMES else None,
        "intent": intent if intent in ("count", "change") else "unknown",
        "paid": amount(data.get("paid")),
        "price": amount(data.get("price")),
    }


async def translate(
    client: httpx.AsyncClient, texts: list[str], lang: str, settings: Settings
) -> list[str]:
    """English texts -> the same texts in `lang`, in order. Numbers are checked by the caller."""
    prompt = (
        f"Translate each message into {LANG_NAMES[lang]}. A cash assistant app speaks them "
        "aloud to a blind person, so use short, plain, everyday words. Keep every number that "
        "is written in digits exactly as written, in the same digits. Birr is the Ethiopian "
        "currency. Return one translation per message, in the same order.\n\nMessages:\n"
        + json.dumps(texts, ensure_ascii=False)
    )
    data = await _generate_json(
        client, [{"text": prompt}], TRANSLATE_SCHEMA, settings, settings.translate_timeout_s
    )
    out = data.get("texts")
    if not isinstance(out, list) or len(out) != len(texts):
        raise GeminiError("translation count does not match")
    if not all(isinstance(t, str) and t.strip() for t in out):
        raise GeminiError("empty translation")
    return [t.strip() for t in out]


def _wav_from_pcm(pcm: bytes, rate: int = 24000) -> bytes:
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(rate)
        w.writeframes(pcm)
    return buf.getvalue()


async def speak(client: httpx.AsyncClient, text: str, settings: Settings) -> bytes:
    """Text -> WAV bytes (24 kHz mono 16-bit). Gemini detects the language from the text."""
    url = f"{settings.gemini_base_url}/interactions"
    content = {"type": "text", "text": text}
    if settings.gemini_voice_style:
        content["annotations"] = [{"type": "speech_metadata", "style": settings.gemini_voice_style}]
    body = {
        "model": settings.gemini_tts_model,
        "input": [{"type": "user_input", "content": [content]}],
        "response_format": {"type": "audio"},
        "generation_config": {"speech_config": [{"voice": settings.gemini_voice}]},
    }
    try:
        resp = await client.post(
            url, json=body, headers=_headers(settings), timeout=settings.gemini_timeout_s
        )
        resp.raise_for_status()
        clips = [
            part
            for step in resp.json().get("steps", [])
            if step.get("type") == "model_output"
            for part in step.get("content", [])
            if part.get("type") == "audio"
        ]
        audio = base64.b64decode(clips[-1]["data"]) if clips else b""
    except (httpx.HTTPError, ValueError, KeyError, TypeError, AttributeError) as exc:
        raise GeminiError(f"speech failed: {type(exc).__name__}") from exc
    if not audio:
        raise GeminiError("speech answer had no audio")
    # The default answer is a full WAV file. Wrap raw 16-bit PCM in case a model sends that.
    return audio if audio[:4] == b"RIFF" else _wav_from_pcm(audio)
