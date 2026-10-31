"""Meta MMS-TTS: spoken Amharic and Oromo on the CPU. Needs the `tts` extra (torch, transformers,
uroman): `uv sync --extra tts`. Without it the backend still answers in every language, as text.

Models: facebook/mms-tts-amh (expects romanized input, so Amharic goes through uroman first) and
facebook/mms-tts-orm (Latin script, read as is). License CC-BY-NC 4.0. The text must already have
numbers as words (birr/voice/numbers.py): the models have no digits. One sentence takes about
0.5-1.5 s on a CPU; loading a model takes about 8 s.
"""

from __future__ import annotations

import importlib.util
import io
import logging
import re
import threading
import wave

log = logging.getLogger(__name__)


PAUSE_S = 0.3  # between sentences
_SENTENCE_END = re.compile(r"(?<=[።.?!፧])\s+")


class MmsError(RuntimeError):
    pass


def split_sentences(text: str) -> list[str]:
    """Split after Amharic (።, ፧) or Latin (. ? !) sentence ends."""
    return [s for s in (part.strip() for part in _SENTENCE_END.split(text)) if s]


def installed() -> bool:
    return all(importlib.util.find_spec(m) for m in ("numpy", "torch", "transformers", "uroman"))


def to_wav(samples, rate: int) -> bytes:
    """Float samples in [-1, 1] -> 16-bit mono WAV bytes."""
    import numpy as np

    pcm = (np.clip(np.asarray(samples, dtype="float32"), -1.0, 1.0) * 32767).astype("<i2")
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(rate)
        w.writeframes(pcm.tobytes())
    return buf.getvalue()


class Mms:
    """Loads each language's model once and speaks one sentence at a time (CPU-bound)."""

    def __init__(self, models: dict[str, str], seed: int = 555):
        self.models = models
        self.seed = seed  # fixed, so the same sentence always sounds the same
        self._loaded: dict[str, tuple] = {}
        self._uroman = None
        self._lock = threading.Lock()

    def _model(self, lang: str):
        if lang not in self._loaded:
            from transformers import AutoTokenizer, VitsModel

            name = self.models[lang]
            self._loaded[lang] = (VitsModel.from_pretrained(name).eval(),
                                  AutoTokenizer.from_pretrained(name))  # fmt: skip
            log.info("MMS model %s loaded", name)
        return self._loaded[lang]

    def load(self, lang: str) -> None:
        with self._lock:
            self._model(lang)

    def synthesize(self, text: str, lang: str) -> bytes:
        """Text (numbers already as words) -> WAV bytes. Blocking: run it in a thread.

        Each sentence is spoken on its own and joined with a short pause: the model slows down
        more than linearly on long input (a total plus a change check: 4.8 s whole, less split)."""
        if lang not in self.models:
            raise MmsError(f"no MMS model for {lang!r}")
        try:
            with self._lock:
                import numpy as np
                import torch

                model, tokenizer = self._model(lang)
                rate = model.config.sampling_rate
                pieces = []
                for sentence in split_sentences(text):
                    if getattr(tokenizer, "is_uroman", False):
                        if self._uroman is None:
                            import uroman

                            self._uroman = uroman.Uroman()
                        sentence = self._uroman.romanize_string(sentence)
                    inputs = tokenizer(sentence, return_tensors="pt")
                    if inputs["input_ids"].shape[-1] == 0:
                        continue
                    torch.manual_seed(self.seed)
                    with torch.inference_mode():
                        pieces.append(model(**inputs).waveform[0].float().numpy())
                    pieces.append(np.zeros(int(rate * PAUSE_S), dtype="float32"))
                if not pieces:
                    raise MmsError("nothing left to say after the tokenizer")
                samples = np.concatenate(pieces[:-1])
        except MmsError:
            raise
        except Exception as exc:  # noqa: BLE001 - any model failure: the app speaks the text
            raise MmsError(f"MMS failed: {type(exc).__name__}") from exc
        return to_wav(samples, rate)
