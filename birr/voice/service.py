"""Spoken answers in the user's language: fixed templates for the text, Meta MMS for the voice.

The backend writes every answer in English (birr/voice/speech.py). For Amharic and Oromo,
birr/voice/localize.py turns it into the same answer from fixed templates (birr/voice/templates.py),
with numbers written by code. No model translates anything, so nothing can change an amount. A
sentence without a template stays English, flagged in `speech_todo`.

Audio clips come from Meta MMS-TTS on the CPU (birr/voice/mms.py, the `tts` extra). A clip is
made before the answer returns, only for text the backend wrote, and cached as a WAV file in
VOICE_CACHE_DIR. Without the extra (or with TTS_ENGINE=off), answers carry text only and the app
speaks them with the phone's voice.
"""

from __future__ import annotations

import asyncio
import hashlib
import logging
import re
from collections import Counter, OrderedDict
from pathlib import Path

from birr.config import Settings
from birr.voice import localize, mms

LANGS = ("en", "am", "om")
TRANSLATED = ("am", "om")
MAX_CLIPS = 5000
_NUMBER = re.compile(r"\d+")
log = logging.getLogger(__name__)


def numbers_kept(en: str, text: str) -> bool:
    """Every number in the English is in the other text. Extra small numbers are allowed, because
    a note count may be written as a digit there."""
    want, got = Counter(_NUMBER.findall(en)), Counter(_NUMBER.findall(text))
    if any(got[n] < count for n, count in want.items()):
        return False
    return all(int(n) <= 10 for n in got - want)


class Voice:
    def __init__(self, settings: Settings, engine: mms.Mms | None = None):
        self.settings = settings
        self.dir = Path(settings.voice_cache_dir)
        self.models = {"am": settings.mms_model_am, "om": settings.mms_model_om}
        if engine is None and settings.tts_engine == "mms" and mms.installed():
            engine = mms.Mms(self.models)
        self.engine = engine
        self.clips: OrderedDict[str, tuple[str, str]] = OrderedDict()
        self._making: dict[str, asyncio.Task] = {}

    @property
    def tts(self) -> str:
        return "mms" if self.engine is not None else "off"

    def speaks(self, lang: str) -> bool:
        return self.engine is not None and lang in self.settings.tts_langs and lang in self.models

    def clip_id(self, lang: str, text: str) -> str:
        key = f"{lang}\n{self.models.get(lang)}\n{text}"
        clip = hashlib.sha256(key.encode()).hexdigest()[:32]
        self.clips[clip] = (lang, text)
        self.clips.move_to_end(clip)
        while len(self.clips) > MAX_CLIPS:
            self.clips.popitem(last=False)
        return clip

    def speech(self, en: str, lang: str) -> dict:
        """Body fields for an answer: speech, and speech_audio (a clip link) or speech_todo."""
        if lang not in TRANSLATED:
            return {"speech": {"en": en}}
        rendered = localize.render(en, lang)
        if rendered is None or not numbers_kept(en, rendered[0]):
            return {"speech": {"en": en, lang: en}, "speech_todo": f"{lang}: no template yet"}
        shown, spoken = rendered
        fields = {"speech": {"en": en, lang: shown}}
        if self.speaks(lang):
            fields["speech_audio"] = f"/speak/{self.clip_id(lang, spoken)}"
        return fields

    async def localize(self, en: str, lang: str) -> dict:
        """speech fields in `lang`, with the clip made before returning so the app can play it
        at once. If MMS can't make it, speech_audio is left out and the app uses its own voice."""
        fields = self.speech(en, lang)
        if "speech_audio" in fields:
            try:
                await self.audio(fields["speech_audio"].rsplit("/", 1)[-1])
            except mms.MmsError as exc:
                log.warning("speech clip failed: %s", exc)
                del fields["speech_audio"]
        return fields

    async def localize_body(self, body: dict, lang: str) -> dict:
        """Put the user's language into a finished answer that carries English speech."""
        en = (body.get("speech") or {}).get("en")
        if not en or lang not in TRANSLATED:
            return body
        rest = {k: v for k, v in body.items() if k not in ("speech", "speech_todo")}
        return {**rest, **(await self.localize(en, lang))}

    async def warm(self, texts: list[str]) -> None:
        """Load the voices and make the fixed phrases' clips, so prompts and errors need no wait."""
        for lang in TRANSLATED:
            if not self.speaks(lang):
                continue
            try:
                await asyncio.to_thread(self.engine.load, lang)
            except Exception as exc:  # noqa: BLE001 - a voice that won't load: text only
                log.warning("MMS voice %s did not load: %s", lang, exc)
                continue
            for en in texts:
                await self.localize(en, lang)

    async def audio(self, clip: str) -> bytes | None:
        """WAV for a clip id from this backend, or None if the id is unknown."""
        path = self.dir / "audio" / f"{clip}.wav"
        try:
            return path.read_bytes()
        except OSError:
            pass
        if clip not in self.clips or self.engine is None:
            return None
        if clip not in self._making:  # one synthesis per clip, however many ask at once
            self._making[clip] = asyncio.create_task(self._make(clip, path))
        try:
            return await asyncio.shield(self._making[clip])
        finally:
            if self._making.get(clip) and self._making[clip].done():
                self._making.pop(clip, None)

    async def _make(self, clip: str, path: Path) -> bytes:
        lang, text = self.clips[clip]
        wav = await asyncio.to_thread(self.engine.synthesize, text, lang)
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(wav)
        except OSError as exc:
            log.warning("could not cache a speech clip: %s", exc)
        return wav
