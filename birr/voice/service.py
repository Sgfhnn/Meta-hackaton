"""Spoken answers in the user's language: translations (cached, number-checked) and speech clips.

The backend writes every answer in English (birr/voice/speech.py). For Amharic and Oromo, Gemini
translates each phrase once, and the translation is cached in VOICE_CACHE_DIR. A translation
that drops or changes a number is thrown away, so the user hears English rather than a wrong
amount. To fix a wording, edit translations.<lang>.json there; edited lines are kept.

Speech clips are made on demand by GET /speak/{clip_id}, only for text the backend produced, and
cached as WAV files. Without GEMINI_API_KEY nothing is translated and answers stay English.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import re
from collections import Counter, OrderedDict
from pathlib import Path

import httpx

from birr.config import Settings
from birr.voice import gemini

LANGS = ("en", "am", "om")
TRANSLATED = ("am", "om")
MAX_CLIPS = 5000
_NUMBER = re.compile(r"\d+")
log = logging.getLogger(__name__)


def numbers_kept(en: str, text: str) -> bool:
    """Every number in the English is in the translation. Extra small numbers are allowed,
    because "two 100s" may come back with the count written as a digit."""
    want, got = Counter(_NUMBER.findall(en)), Counter(_NUMBER.findall(text))
    if any(got[n] < count for n, count in want.items()):
        return False
    return all(int(n) <= 10 for n in got - want)


class Voice:
    def __init__(self, settings: Settings):
        self.settings = settings
        self.dir = Path(settings.voice_cache_dir)
        self.translations: dict[str, dict[str, str]] = {lang: {} for lang in TRANSLATED}
        self.clips: OrderedDict[str, tuple[str, str]] = OrderedDict()
        self._making: dict[str, asyncio.Task] = {}
        for lang in TRANSLATED:
            path = self.dir / f"translations.{lang}.json"
            try:
                loaded = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                continue
            self.translations[lang] = {k: v for k, v in loaded.items() if numbers_kept(k, v)}

    @property
    def enabled(self) -> bool:
        return bool(self.settings.gemini_key)

    def speaks(self, lang: str) -> bool:
        return self.enabled and lang in self.settings.gemini_tts_langs

    def _save(self, lang: str) -> None:
        try:
            self.dir.mkdir(parents=True, exist_ok=True)
            data = json.dumps(self.translations[lang], ensure_ascii=False, indent=1, sort_keys=True)
            (self.dir / f"translations.{lang}.json").write_text(data, encoding="utf-8")
        except OSError as exc:  # a read-only disk only costs the cache
            log.warning("could not save translations: %s", exc)

    async def translate(self, client: httpx.AsyncClient, texts: list[str], lang: str) -> None:
        """Translate the texts not cached yet. Failures leave them English."""
        if lang not in TRANSLATED or not self.enabled:
            return
        todo = list(dict.fromkeys(t for t in texts if t and t not in self.translations[lang]))
        if not todo:
            return
        try:
            out = await gemini.translate(client, todo, lang, self.settings)
        except gemini.GeminiError as exc:
            log.warning("translation to %s failed: %s", lang, exc)
            return
        kept = {en: text for en, text in zip(todo, out, strict=True) if numbers_kept(en, text)}
        if kept:
            self.translations[lang].update(kept)
            self._save(lang)

    def clip_id(self, lang: str, text: str) -> str:
        s = self.settings
        key = f"{lang}\n{s.gemini_tts_model}\n{s.gemini_voice}\n{s.gemini_voice_style}\n{text}"
        clip = hashlib.sha256(key.encode()).hexdigest()[:32]
        self.clips[clip] = (lang, text)
        self.clips.move_to_end(clip)
        while len(self.clips) > MAX_CLIPS:
            self.clips.popitem(last=False)
        return clip

    def speech(self, en: str, lang: str) -> dict:
        """Body fields for an answer, from the cache only: speech, maybe speech_audio and
        speech_todo. English stands in for a missing translation."""
        if lang not in TRANSLATED:
            return {"speech": {"en": en}}
        text = self.translations[lang].get(en)
        if text is None:
            why = "Gemini is not configured" if not self.enabled else "no checked translation yet"
            return {"speech": {"en": en, lang: en}, "speech_todo": f"{lang}: {why}"}
        fields = {"speech": {"en": en, lang: text}}
        if self.speaks(lang):
            fields["speech_audio"] = f"/speak/{self.clip_id(lang, text)}"
        return fields

    async def localize(self, client: httpx.AsyncClient, en: str, lang: str) -> dict:
        await self.translate(client, [en], lang)
        return self.speech(en, lang)

    async def localize_body(self, client: httpx.AsyncClient, body: dict, lang: str) -> dict:
        """Put the user's language into a finished answer that carries English speech."""
        en = (body.get("speech") or {}).get("en")
        if not en or lang not in TRANSLATED:
            return body
        rest = {k: v for k, v in body.items() if k not in ("speech", "speech_todo")}
        return {**rest, **(await self.localize(client, en, lang))}

    async def audio(self, client: httpx.AsyncClient, clip: str) -> bytes | None:
        """WAV for a clip id from this backend, or None if the id is unknown."""
        path = self.dir / "audio" / f"{clip}.wav"
        try:
            return path.read_bytes()
        except OSError:
            pass
        if clip not in self.clips or not self.enabled:
            return None
        if clip not in self._making:  # one Gemini call per clip, however many ask at once
            self._making[clip] = asyncio.create_task(self._make(client, clip, path))
        try:
            return await asyncio.shield(self._making[clip])
        finally:
            if self._making.get(clip) and self._making[clip].done():
                self._making.pop(clip, None)

    async def _make(self, client: httpx.AsyncClient, clip: str, path: Path) -> bytes:
        _, text = self.clips[clip]
        wav = await gemini.speak(client, text, self.settings)
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(wav)
        except OSError as exc:
            log.warning("could not cache a speech clip: %s", exc)
        return wav
