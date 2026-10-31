"""Voice: Gemini intent requests (mocked HTTP), Amharic/Oromo answers from templates, MMS clips
(a fake engine), and the voice endpoints. No network, no keys, no model downloads.
"""

import asyncio
import base64
import io
import json
import wave

import httpx
import pytest
from conftest import post_scan
from fastapi.testclient import TestClient

from birr import api
from birr.config import Settings
from birr.voice import asr, gemini, localize, mms, understand
from birr.voice import speech as say
from birr.voice.service import Voice, numbers_kept

SHORT_M4A = b"\x00\x00\x00\x18ftypM4A fake audio"


def run(coro):
    return asyncio.run(coro)


def with_mock(handler, call):
    async def go():
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            return await call(client)

    return run(go())


def generated(obj) -> dict:
    """A generateContent answer whose text is `obj` as JSON."""
    text = json.dumps(obj, ensure_ascii=False)
    return {"candidates": [{"content": {"parts": [{"text": text}]}}]}


def wav_bytes(seconds=0.1) -> bytes:
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(16000)
        w.writeframes(b"\x00\x00" * int(16000 * seconds))
    return buf.getvalue()


class FakeMms:
    """Stands in for birr.voice.mms.Mms: records what it was asked to say."""

    def __init__(self, fail=False):
        self.said, self.loaded, self.fail = [], [], fail

    def load(self, lang):
        self.loaded.append(lang)

    def synthesize(self, text, lang):
        if self.fail:
            raise mms.MmsError("down")
        self.said.append((lang, text))
        return wav_bytes()


@pytest.fixture
def voice_env(monkeypatch, tmp_path):
    monkeypatch.setenv("GEMINI_API_KEY", "test-gemini-key")
    monkeypatch.setenv("VOICE_CACHE_DIR", str(tmp_path / "voice"))
    monkeypatch.delenv("TTS_LANGS", raising=False)
    monkeypatch.delenv("GEMINI_THINKING_LEVEL", raising=False)
    return tmp_path


# --- Gemini: hearing the question ------------------------------------------------------------


def test_understand_request_shape(voice_env):
    seen = {}

    def handler(request):
        seen["url"] = str(request.url)
        seen["key"] = request.headers["x-goog-api-key"]
        seen["body"] = json.loads(request.content)
        answer = {"transcript": "...", "lang": "am", "intent": "change", "paid": 500, "price": 320}
        return httpx.Response(200, json=generated(answer))

    heard = with_mock(handler, lambda c: gemini.understand(c, SHORT_M4A, "audio/m4a", Settings()))
    assert heard == {"lang": "am", "intent": "change", "paid": 500, "price": 320}
    assert seen["url"] == (
        "https://generativelanguage.googleapis.com/v1beta/models/gemini-3.8-flash:generateContent"
    )
    assert seen["key"] == "test-gemini-key"
    parts = seen["body"]["contents"][0]["parts"]
    assert parts[0]["text"] == gemini.INTENT_PROMPT
    assert parts[1]["inlineData"]["mimeType"] == "audio/m4a"
    assert base64.b64decode(parts[1]["inlineData"]["data"]) == SHORT_M4A
    config = seen["body"]["generationConfig"]
    assert config["responseMimeType"] == "application/json"
    assert config["responseSchema"] == gemini.INTENT_SCHEMA
    assert "thinkingConfig" not in config


def test_thinking_level_is_optional(voice_env, monkeypatch):
    monkeypatch.setenv("GEMINI_THINKING_LEVEL", "low")
    seen = {}

    def handler(request):
        seen["body"] = json.loads(request.content)
        answer = {"transcript": "", "lang": "en", "intent": "count", "paid": None, "price": None}
        return httpx.Response(200, json=generated(answer))

    with_mock(handler, lambda c: gemini.understand(c, SHORT_M4A, "audio/m4a", Settings()))
    assert seen["body"]["generationConfig"]["thinkingConfig"] == {"thinkingLevel": "low"}


@pytest.mark.parametrize(
    "answer, expected",
    [
        ({"lang": "xx", "intent": "count", "paid": None, "price": None},
         {"lang": None, "intent": "count", "paid": None, "price": None}),
        ({"lang": "om", "intent": "dance", "paid": 5, "price": 2},
         {"lang": "om", "intent": "unknown", "paid": 5, "price": 2}),
        ({"lang": "en", "intent": "change", "paid": -5, "price": True},
         {"lang": "en", "intent": "change", "paid": None, "price": None}),
        ({"lang": "en", "intent": "change", "paid": "500", "price": 10**7},
         {"lang": "en", "intent": "change", "paid": None, "price": None}),
    ],
)  # fmt: skip
def test_understand_cleans_answers(voice_env, answer, expected):
    answer = {"transcript": "", **answer}
    handler = lambda request: httpx.Response(200, json=generated(answer))  # noqa: E731
    heard = with_mock(handler, lambda c: gemini.understand(c, SHORT_M4A, "audio/m4a", Settings()))
    assert heard == expected


@pytest.mark.parametrize(
    "response",
    [
        httpx.Response(500),
        httpx.Response(200, text="not json"),
        httpx.Response(200, json={"candidates": []}),
        httpx.Response(200, json={"candidates": [{"content": {"parts": [{"text": "[1]"}]}}]}),
    ],
)
def test_understand_failures_raise(voice_env, response):
    with pytest.raises(gemini.GeminiError):
        with_mock(
            lambda request: response,
            lambda c: gemini.understand(c, SHORT_M4A, "audio/m4a", Settings()),
        )


@pytest.mark.parametrize(
    "filename, content_type, expected",
    [
        ("q.m4a", "audio/mp4", "audio/m4a"),
        ("q.m4a", "application/octet-stream", "audio/m4a"),
        ("q.webm", None, "audio/webm"),
        ("q", "audio/x-wav", "audio/wav"),
        ("photo.jpg", "image/jpeg", None),
    ],
)
def test_audio_mime(filename, content_type, expected):
    assert gemini.audio_mime(filename, content_type) == expected


# --- Answers in Amharic and Oromo, and their clips ---------------------------------------------


@pytest.mark.parametrize(
    "en, text, ok",
    [
        ("You have 350 birr: one 200, one 100 and one 50.", "350 ብር፤ 200፣ 100 እና 50።", True),
        ("You have 350 birr: one 200, one 100 and one 50.", "305 ብር፤ 200፣ 100 እና 50።", False),
        ("You have 300 birr: three 100s.", "300 ብር: 3 x 100", True),
        ("Counting.", "እየቆጠርኩ ነው።", True),
    ],
)
def test_numbers_kept(en, text, ok):
    assert numbers_kept(en, text) is ok


def test_speech_needs_no_key(monkeypatch, tmp_path):
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    monkeypatch.setenv("TTS_ENGINE", "off")
    fields = Voice(Settings()).speech(say.COUNT_PROMPT, "am")
    assert fields == {"speech": {"en": say.COUNT_PROMPT, "am": localize.render(say.COUNT_PROMPT,
                                                                             "am")[0]}}  # fmt: skip


def test_clip_is_made_before_the_answer(voice_env):
    engine = FakeMms()
    voice = Voice(Settings(), engine=engine)
    en = say.total_text(350, [200, 100, 50])
    fields = run(voice.localize(en, "am"))
    shown, spoken = localize.render(en, "am")
    assert fields["speech"] == {"en": en, "am": shown}
    assert fields["speech_audio"].startswith("/speak/")
    assert engine.said == [("am", spoken)]  # words, not digits: MMS reads no digits
    assert "350" in shown and "350" not in spoken


def test_no_clip_for_a_language_not_spoken(voice_env, monkeypatch):
    monkeypatch.setenv("TTS_LANGS", "am")
    fields = run(Voice(Settings(), engine=FakeMms()).localize(say.RESCAN, "om"))
    assert fields["speech"]["om"] == localize.render(say.RESCAN, "om")[0]
    assert "speech_audio" not in fields


def test_failed_clip_leaves_text_only(voice_env):
    fields = run(Voice(Settings(), engine=FakeMms(fail=True)).localize(say.RESCAN, "am"))
    assert "speech_audio" not in fields and fields["speech"]["am"]


def test_unknown_sentence_stays_english(voice_env):
    fields = Voice(Settings(), engine=FakeMms()).speech("Something new.", "am")
    assert fields["speech"] == {"en": "Something new.", "am": "Something new."}
    assert "speech_todo" in fields and "speech_audio" not in fields


def test_oromo_voice_is_off_by_default(voice_env):
    voice = Voice(Settings(), engine=FakeMms())
    assert voice.speaks("am") and not voice.speaks("om")


def test_warm_loads_voices_and_makes_fixed_clips(voice_env, monkeypatch):
    monkeypatch.setenv("TTS_LANGS", "am,om")
    engine = FakeMms()
    voice = Voice(Settings(), engine=engine)
    run(voice.warm([say.RESCAN, say.STILL_COUNTING]))
    assert engine.loaded == ["am", "om"]
    assert len(engine.said) == 4
    run(voice.warm([say.RESCAN]))  # cached on disk: nothing new to say
    assert len(engine.said) == 4


# --- Endpoints -----------------------------------------------------------------------------


@pytest.fixture
def voice_client(voice_env, monkeypatch):
    """A client with Gemini 'configured' and a fake MMS voice."""
    monkeypatch.setenv("TRACE_DIR", str(voice_env))
    monkeypatch.delenv("MUSE_ONLY_TOTALS", raising=False)
    engine = FakeMms()
    real_init = Voice.__init__

    def init(self, settings, engine_arg=None):
        real_init(self, settings, engine=engine)

    monkeypatch.setattr(Voice, "__init__", init)
    state = {"heard": None, "engine": engine}

    async def understand(client, audio, mime, settings):
        if isinstance(state["heard"], Exception):
            raise state["heard"]
        return state["heard"]

    monkeypatch.setattr(gemini, "understand", understand)
    with TestClient(api.app) as c:
        c.state = state
        c.trace_dir = voice_env
        yield c


def post_intent(client, lang="am", audio=SHORT_M4A, filename="q.m4a", content_type="audio/mp4"):
    files = {"audio": (filename, audio, content_type)}
    return client.post("/intent", data={"lang": lang}, files=files)


def heard(intent, lang="am", paid=None, price=None):
    return {"lang": lang, "intent": intent, "paid": paid, "price": price}


def test_intent_without_gemini_is_501(client):
    r = post_intent(client)
    assert r.status_code == 501
    assert r.json()["error"] == "not_implemented"


@pytest.mark.parametrize(
    "answer, step, text",
    [
        (heard("count"), "scan", say.COUNT_PROMPT),
        (heard("change", paid=500), "ask", say.NEED_PRICE),
        (heard("change", paid=100, price=320), "ask", say.PRICE_OVER_PAID),
        (heard("change", paid=500, price=320), "scan", say.change_prompt(500, 320)),
        (heard("change", paid=320, price=320), "done", say.change_prompt(320, 320)),
        (heard("unknown"), "ask", say.INTENT_UNKNOWN),
    ],
)
def test_intent_next_step_and_speech(voice_client, answer, step, text):
    voice_client.state["heard"] = answer
    r = post_intent(voice_client)
    assert r.status_code == 200
    body = r.json()
    assert body["intent"] == answer["intent"]
    assert body["next"] == step
    assert body["lang"] == "am"
    assert (body["paid"], body["price"]) == (answer["paid"], answer["price"])
    assert body["speech"] == {"en": text, "am": localize.render(text, "am")[0]}
    assert body["speech_audio"].startswith("/speak/")
    trace = json.loads((voice_client.trace_dir / f"{body['trace_id']}.json").read_text())
    assert trace["outcome"] == answer["intent"] and trace["next"] == step
    assert "transcript" not in json.dumps(trace)


def test_intent_falls_back_to_the_app_language(voice_client):
    voice_client.state["heard"] = heard("count", lang=None)
    body = post_intent(voice_client, lang="om").json()
    assert body["lang"] == "om"
    assert body["speech"]["om"] == localize.render(say.COUNT_PROMPT, "om")[0]


@pytest.mark.parametrize(
    "kwargs",
    [
        {"audio": b"", "filename": "q.m4a"},
        {"filename": "photo.jpg", "content_type": "image/jpeg"},
    ],
)
def test_intent_rejects_bad_audio(voice_client, kwargs):
    voice_client.state["heard"] = heard("count")
    r = post_intent(voice_client, **kwargs)
    assert r.status_code == 400
    assert r.json()["speech"]["en"] == say.BAD_AUDIO


def test_intent_rejects_long_audio(voice_client, monkeypatch):
    monkeypatch.setenv("MAX_AUDIO_BYTES", "10")
    voice_client.state["heard"] = heard("count")
    assert post_intent(voice_client).status_code == 400


def test_intent_gemini_failure_is_502(voice_client):
    voice_client.state["heard"] = gemini.GeminiError("down")
    r = post_intent(voice_client)
    assert r.status_code == 502
    assert r.json()["speech"]["en"] == say.NOT_HEARD


def test_speak_serves_and_caches_clips(voice_client):
    voice_client.state["heard"] = heard("count")
    link = post_intent(voice_client).json()["speech_audio"]
    first = voice_client.get(link)
    assert first.status_code == 200
    assert first.headers["content-type"] == "audio/wav"
    assert first.content[:4] == b"RIFF"
    assert voice_client.get(link).content == first.content
    spoken = localize.render(say.COUNT_PROMPT, "am")[1]
    assert voice_client.state["engine"].said.count(("am", spoken)) == 1  # made once, then cached


@pytest.mark.parametrize("path", ["/speak/" + "0" * 32, "/speak/not-a-clip", "/speak/..%2Fx"])
def test_speak_unknown_clip_is_404(voice_client, path):
    assert voice_client.get(path).status_code == 404


def test_speak_mms_failure_is_502(voice_client):
    voice_client.state["engine"].fail = True
    clip = api.app.state.voice.clip_id("am", "ገና ያልተሰራ")
    assert voice_client.get(f"/speak/{clip}").status_code == 502


def test_phrases(voice_client):
    am = voice_client.get("/phrases", params={"lang": "am"}).json()
    assert set(am["phrases"]) == set(say.APP_PHRASES)
    assert am["phrases"]["counting"]["text"] == "እየቆጠርኩ ነው።"
    assert am["phrases"]["counting"]["audio"].startswith("/speak/")
    en = voice_client.get("/phrases", params={"lang": "en"}).json()
    assert en["phrases"]["counting"] == {"text": "Counting.", "audio": None}


def test_scan_answer_in_amharic(voice_client, fake):
    fake["labels"] = ["100", "50"]
    fake["regions"] = []
    body = post_scan(voice_client, lang="am").json()
    assert body["speech"]["am"] == localize.render(body["speech"]["en"], "am")[0]
    assert body["speech_audio"].startswith("/speak/")
    assert "speech_todo" not in body


def test_errors_use_templates(voice_client):
    files = {"image": ("x.jpg", b"not an image", "image/jpeg")}
    data = {"intent": "count", "lang": "am", "wait": "true"}
    r = voice_client.post("/scan", data=data, files=files)
    assert r.status_code == 400
    assert r.json()["speech"]["am"] == localize.render(say.BAD_REQUEST, "am")[0]


def test_health_reports_voice(voice_client, monkeypatch):
    assert voice_client.get("/health").json()["voice"] == {
        "hears": "gemini", "intent": True, "translates": True, "tts": "mms", "speaks": ["am"],
    }  # fmt: skip
    monkeypatch.setenv("ASR_URL", "http://127.0.0.1:8002")
    assert voice_client.get("/health").json()["voice"]["hears"] == "omnilingual"


def test_health_without_any_voice_engine(client):
    assert client.get("/health").json()["voice"] == {
        "hears": "off", "intent": False, "translates": True, "tts": "off", "speaks": [],
    }  # fmt: skip


def test_a_localize_crash_keeps_the_scan_answer(voice_client, fake, monkeypatch):
    async def broken(body, lang):
        raise RuntimeError("bug")

    monkeypatch.setattr(api.app.state.voice, "localize_body", broken)
    fake["labels"] = ["100", "50"]
    fake["regions"] = []
    r = post_scan(voice_client, lang="am")
    assert r.status_code == 200
    assert r.json()["speech"]["en"]  # English answer, not a crash


# --- Omnilingual ASR + Muse (the default voice path when ASR_URL is set) ---------------------


def completion(content: str) -> dict:
    return {"choices": [{"message": {"role": "assistant", "content": content}}]}


def test_asr_request_shape(voice_env, monkeypatch):
    monkeypatch.setenv("ASR_URL", "http://127.0.0.1:8002/")
    seen = {}

    def handler(request):
        seen["url"] = str(request.url)
        seen["type"] = request.headers["content-type"]
        seen["body"] = request.content
        return httpx.Response(200, json={"text": "  ሰላም  ", "lang": "amh_Ethi", "ms": 600})

    text = with_mock(handler, lambda c: asr.transcribe(c, SHORT_M4A, "audio/m4a", "am", Settings()))
    assert text == "ሰላም"
    assert seen["url"] == "http://127.0.0.1:8002/transcribe?lang=amh_Ethi"
    assert seen["type"] == "audio/m4a" and seen["body"] == SHORT_M4A


@pytest.mark.parametrize(
    "response",
    [httpx.Response(500), httpx.Response(200, text="nope"), httpx.Response(200, json={"x": 1})],
)
def test_asr_failures_raise(voice_env, monkeypatch, response):
    monkeypatch.setenv("ASR_URL", "http://127.0.0.1:8002")
    with pytest.raises(asr.AsrError):
        with_mock(
            lambda request: response,
            lambda c: asr.transcribe(c, SHORT_M4A, "audio/m4a", "om", Settings()),
        )


def test_muse_intent_request_and_cleaning(voice_env, monkeypatch):
    monkeypatch.setenv("BASETEN_API_KEY", "test-key")
    seen = {}

    def handler(request):
        seen["url"] = str(request.url)
        seen["body"] = json.loads(request.content)
        reply = 'Sure: {"lang": "am", "intent": "change", "paid": 500, "price": "320"}'
        return httpx.Response(200, json=completion(reply))

    heard = with_mock(handler, lambda c: understand.from_text(c, "አ5 መቶብር ከፍዬ", Settings()))
    assert heard == {"lang": "am", "intent": "change", "paid": 500, "price": None}  # "320": str
    assert seen["url"] == "https://inference.baseten.co/v1/chat/completions"
    body = seen["body"]
    assert body["model"] == "meta-models/muse-spark-open-1026"
    assert body["messages"][0]["content"] == understand.PROMPT + "አ5 መቶብር ከፍዬ"


@pytest.mark.parametrize(
    "response",
    [httpx.Response(502), httpx.Response(200, json=completion("no json here"))],
)
def test_muse_intent_failures_raise(voice_env, response):
    with pytest.raises(understand.UnderstandError):
        with_mock(lambda request: response, lambda c: understand.from_text(c, "hi", Settings()))


@pytest.fixture
def omni_client(voice_client, monkeypatch):
    """voice_client with ASR_URL set: Omnilingual + Muse hear the question (both faked)."""
    monkeypatch.setenv("ASR_URL", "http://127.0.0.1:8002")
    state = voice_client.state
    state.update(transcript="birri dhibba shankafalee", muse=None, asr_calls=[])

    async def transcribe(client, audio, mime, lang, settings):
        state["asr_calls"].append((mime, lang))
        if isinstance(state["transcript"], Exception):
            raise state["transcript"]
        return state["transcript"]

    async def from_text(client, transcript, settings):
        if isinstance(state["muse"], Exception):
            raise state["muse"]
        return state["muse"]

    async def no_gemini(*args):
        raise AssertionError("Gemini must not be called when ASR_URL is set")

    monkeypatch.setattr(asr, "transcribe", transcribe)
    monkeypatch.setattr(understand, "from_text", from_text)
    monkeypatch.setattr(gemini, "understand", no_gemini)
    return voice_client


def test_omnilingual_path(omni_client):
    omni_client.state["muse"] = heard("change", lang="om", paid=500, price=320)
    body = post_intent(omni_client, lang="om").json()
    got = (body["intent"], body["next"], body["paid"], body["price"])
    assert got == ("change", "scan", 500, 320)
    assert body["speech"]["om"] == localize.render(say.change_prompt(500, 320), "om")[0]
    assert "speech_audio" not in body  # Oromo is text only by default
    assert omni_client.state["asr_calls"] == [("audio/m4a", "om")]
    trace = json.loads((omni_client.trace_dir / f"{body['trace_id']}.json").read_text())
    assert trace["engine"] == "omnilingual" and trace["heard_chars"] == 24
    assert set(trace["timing_ms"]) == {"asr", "intent", "total"}
    assert "shankafalee" not in json.dumps(trace)  # no transcript in traces


def test_nothing_heard_asks_again(omni_client):
    omni_client.state["transcript"] = ""
    body = post_intent(omni_client).json()
    assert (body["intent"], body["next"]) == ("unknown", "ask")
    assert body["speech"]["en"] == say.NOT_HEARD


@pytest.mark.parametrize("failing", ["transcript", "muse"])
def test_asr_or_muse_failure_is_502(omni_client, failing):
    omni_client.state["muse"] = heard("count")
    error = asr.AsrError("down") if failing == "transcript" else understand.UnderstandError("x")
    omni_client.state[failing] = error
    r = post_intent(omni_client)
    assert r.status_code == 502
    assert r.json()["speech"]["en"] == say.NOT_HEARD
