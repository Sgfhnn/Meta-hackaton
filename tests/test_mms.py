"""Meta MMS-TTS helpers. The real model runs only with the `tts` extra and RUN_MMS=1 (it downloads
the weights); CI checks the WAV packing and the error path."""

import io
import os
import wave

import pytest

from birr.voice import mms


def test_to_wav_packs_16_bit_mono():
    np = pytest.importorskip("numpy")
    data = mms.to_wav(np.array([0.0, 0.5, -1.0, 2.0], dtype="float32"), 16000)
    with wave.open(io.BytesIO(data)) as w:
        assert (w.getnchannels(), w.getsampwidth(), w.getframerate(), w.getnframes()) == (
            1, 2, 16000, 4,
        )  # fmt: skip
        frames = w.readframes(4)
    assert frames[-2:] == (32767).to_bytes(2, "little", signed=True)  # clipped at full scale


def test_unknown_language_is_an_mms_error():
    with pytest.raises(mms.MmsError):
        mms.Mms({"am": "facebook/mms-tts-amh"}).synthesize("ሰላም", "xx")


@pytest.mark.skipif(not os.getenv("RUN_MMS"), reason="downloads the MMS weights; set RUN_MMS=1")
def test_real_mms_speaks_amharic():
    pytest.importorskip("torch")
    engine = mms.Mms({"am": "facebook/mms-tts-amh", "om": "facebook/mms-tts-orm"})
    for lang, text in [("am", "ሦስት መቶ ሃምሳ ብር አለዎት።"), ("om", "Waliigala qarshii dhibba qabda.")]:
        data = engine.synthesize(text, lang)
        with wave.open(io.BytesIO(data)) as w:
            assert w.getframerate() == 16000 and w.getnframes() > 8000  # over half a second
