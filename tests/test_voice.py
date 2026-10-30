"""Gemini voice: request shapes (mocked HTTP), the number check, caches, and the voice endpoints.

No network and no keys: Gemini calls go to httpx.MockTransport or to fakes.
"""

import asyncio
import base64
import io
import json
import time
import wave

import httpx
import pytest
from conftest import post_scan
from fastapi.testclient import TestClient

from birr import api
from birr.config import Settings
from birr.voice import gemini
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
        w.setframerate(24000)
        w.writeframes(b"\x00\x00" * int(24000 * seconds))
    return buf.getvalue()


def tts_answer(audio: bytes) -> dict:
    data = base64.b64encode(audio).decode()
    return {"steps": [{"type": "model_output", "content": [{"type": "audio", "data": data}]}]}


@pytest.fixture
def gemini_env(monkeypatch, tmp_path):
    monkeypatch.setenv("GEMINI_API_KEY", "test-gemini-key")
    monkeypatch.setenv("VOICE_CACHE_DIR", str(tmp_path / "voice"))
    monkeypatch.delenv("GEMINI_TTS_LANGS", raising=False)
    monkeypatch.delenv("GEMINI_THINKING_LEVEL", raising=False)
    return tmp_path


# --- Gemini client ------------------------------------------------------------------------


def test_understand_request_shape(gemini_env):
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
    body = seen["body"]
    parts = body["contents"][0]["parts"]
    assert parts[0]["text"] == gemini.INTENT_PROMPT
    assert parts[1]["inlineData"]["mimeType"] == "audio/m4a"
    assert base64.b64decode(parts[1]["inlineData"]["data"]) == SHORT_M4A
    config = body["generationConfig"]
    assert config["responseMimeType"] == "application/json"
    assert config["responseSchema"] == gemini.INTENT_SCHEMA
    assert "thinkingConfig" not in config


def test_thinking_level_is_optional(gemini_env, monkeypatch):
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
def test_understand_cleans_answers(gemini_env, answer, expected):
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
def test_understand_failures_raise(gemini_env, response):
    with pytest.raises(gemini.GeminiError):
        with_mock(
            lambda request: response,
            lambda c: gemini.understand(c, SHORT_M4A, "audio/m4a", Settings()),
        )


def test_translate_request_and_count_check(gemini_env):
    seen = {}

    def handler(request):
        seen["body"] = json.loads(request.content)
        return httpx.Response(200, json=generated({"texts": ["ሀ 350", "ለ"]}))

    texts = ["You have 350 birr.", "Counting."]
    out = with_mock(handler, lambda c: gemini.translate(c, texts, "am", Settings()))
    assert out == ["ሀ 350", "ለ"]
    prompt = seen["body"]["contents"][0]["parts"][0]["text"]
    assert "Amharic" in prompt and json.dumps(texts) in prompt
    assert seen["body"]["generationConfig"]["responseSchema"] == gemini.TRANSLATE_SCHEMA

    one = lambda request: httpx.Response(200, json=generated({"texts": ["only one"]}))  # noqa: E731
    with pytest.raises(gemini.GeminiError):
        with_mock(one, lambda c: gemini.translate(c, texts, "am", Settings()))


def test_speak_request_shape_and_wav(gemini_env):
    seen = {}
    clip = wav_bytes()

    def handler(request):
        seen["url"] = str(request.url)
        seen["body"] = json.loads(request.content)
        return httpx.Response(200, json=tts_answer(clip))

    assert with_mock(handler, lambda c: gemini.speak(c, "ሰላም", Settings())) == clip
    assert seen["url"] == "https://generativelanguage.googleapis.com/v1beta/interactions"
    body = seen["body"]
    assert body["model"] == "gemini-3.8-flash-tts"
    assert body["response_format"] == {"type": "audio"}
    assert body["generation_config"] == {"speech_config": [{"voice": "Kore"}]}
    content = body["input"][0]["content"][0]
    assert content["text"] == "ሰላም"
    assert content["annotations"][0]["type"] == "speech_metadata"


def test_speak_wraps_raw_pcm(gemini_env):
    pcm = b"\x01\x00" * 2400
    handler = lambda request: httpx.Response(200, json=tts_answer(pcm))  # noqa: E731
    out = with_mock(handler, lambda c: gemini.speak(c, "hi", Settings()))
    with wave.open(io.BytesIO(out)) as w:
        assert (w.getnchannels(), w.getsampwidth(), w.getframerate()) == (1, 2, 24000)
        assert w.readframes(w.getnframes()) == pcm


@pytest.mark.parametrize("response", [httpx.Response(429), httpx.Response(200, json={"steps": []})])
def test_speak_failures_raise(gemini_env, response):
    with pytest.raises(gemini.GeminiError):
        with_mock(lambda request: response, lambda c: gemini.speak(c, "hi", Settings()))


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


# --- Number check and caches ---------------------------------------------------------------


@pytest.mark.parametrize(
    "en, text, ok",
    [
        ("You have 350 birr: one 200, one 100 and one 50.", "350 ብር አለዎት፤ 200፣ 100 እና 50።", True),
        ("You have 350 birr: one 200, one 100 and one 50.", "305 ብር አለዎት፤ 200፣ 100 እና 50።", False),
        ("You have 350 birr: one 200, one 100 and one 50.", "350 ብር አለዎት።", False),
        ("You have 300 birr: three 100s.", "300 ብር: 3 x 100", True),
        ("You have 300 birr: three 100s.", "300 ብር: 3 x 100 እና 50", False),
        ("Counting.", "በመቁጠር ላይ።", True),
    ],
)
def test_numbers_kept(en, text, ok):
    assert numbers_kept(en, text) is ok


def fake_translate(prefix="AM"):
    calls = []

    async def translate(client, texts, lang, settings):
        calls.append((lang, list(texts)))
        return [f"{prefix}-{lang}: {t}" for t in texts]

    translate.calls = calls
    return translate


def test_translations_are_cached_on_disk(gemini_env, monkeypatch):
    fake = fake_translate()
    monkeypatch.setattr(gemini, "translate", fake)
    voice = Voice(Settings())
    run(voice.translate(None, ["Counting.", "You have 50 birr."], "am"))
    run(voice.translate(None, ["Counting."], "am"))  # cached: no second call
    assert len(fake.calls) == 1
    again = Voice(Settings())  # a restart reads the saved file
    assert again.speech("Counting.", "am")["speech"]["am"] == "AM-am: Counting."


def test_translation_that_changes_a_number_is_dropped(gemini_env, monkeypatch):
    async def bad(client, texts, lang, settings):
        return [t.replace("350", "530") for t in texts]

    monkeypatch.setattr(gemini, "translate", bad)
    voice = Voice(Settings())
    fields = run(voice.localize(None, "You have 350 birr: one 200, one 100 and one 50.", "am"))
    assert fields["speech"]["am"] == fields["speech"]["en"]  # English stands in
    assert "speech_todo" in fields and "speech_audio" not in fields


def test_speech_audio_only_for_spoken_languages(gemini_env, monkeypatch):
    spoken = []

    async def speak(client, text, settings):
        spoken.append(text)
        return wav_bytes()

    monkeypatch.setattr(gemini, "translate", fake_translate())
    monkeypatch.setattr(gemini, "speak", speak)
    voice = Voice(Settings())
    am = run(voice.localize(None, "Counting.", "am"))
    om = run(voice.localize(None, "Counting.", "om"))
    assert am["speech_audio"].startswith("/speak/")
    assert spoken == ["AM-am: Counting."]  # made before localize returned; Oromo is not spoken
    assert om["speech"]["om"] == "AM-om: Counting." and "speech_audio" not in om
    assert Voice(Settings()).speech("Counting.", "en") == {"speech": {"en": "Counting."}}


def test_without_a_key_nothing_is_translated(monkeypatch, tmp_path):
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    monkeypatch.setenv("VOICE_CACHE_DIR", str(tmp_path))

    async def boom(*args):
        raise AssertionError("Gemini must not be called without a key")

    monkeypatch.setattr(gemini, "translate", boom)
    fields = run(Voice(Settings()).localize(None, "Counting.", "am"))
    assert fields["speech"] == {"en": "Counting.", "am": "Counting."}
    assert "not configured" in fields["speech_todo"]


# --- Endpoints -----------------------------------------------------------------------------


@pytest.fixture
def voice_client(gemini_env, monkeypatch):
    """A client with Gemini 'configured': every Gemini call goes to a fake."""
    monkeypatch.setenv("TRACE_DIR", str(gemini_env))
    monkeypatch.delenv("MUSE_ONLY_TOTALS", raising=False)
    state = {"heard": None, "spoken": []}

    async def understand(client, audio, mime, settings):
        if isinstance(state["heard"], Exception):
            raise state["heard"]
        return state["heard"]

    async def speak(client, text, settings):
        state["spoken"].append(text)
        return wav_bytes()

    monkeypatch.setattr(gemini, "understand", understand)
    monkeypatch.setattr(gemini, "translate", fake_translate())
    monkeypatch.setattr(gemini, "speak", speak)
    with TestClient(api.app) as c:
        c.state = state
        c.trace_dir = gemini_env
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
    assert body["speech"] == {"en": text, "am": f"AM-am: {text}"}
    assert body["speech_audio"].startswith("/speak/")
    trace = json.loads((voice_client.trace_dir / f"{body['trace_id']}.json").read_text())
    assert trace["outcome"] == answer["intent"] and trace["next"] == step
    assert "transcript" not in json.dumps(trace)


def test_intent_falls_back_to_the_app_language(voice_client):
    voice_client.state["heard"] = heard("count", lang=None)
    body = post_intent(voice_client, lang="om").json()
    assert body["lang"] == "om"
    assert body["speech"]["om"] == f"AM-om: {say.COUNT_PROMPT}"


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
    # Made once, before /intent answered; both downloads came from the cache.
    assert voice_client.state["spoken"].count(f"AM-am: {say.COUNT_PROMPT}") == 1


@pytest.mark.parametrize("path", ["/speak/" + "0" * 32, "/speak/not-a-clip", "/speak/..%2Fx"])
def test_speak_unknown_clip_is_404(voice_client, path):
    assert voice_client.get(path).status_code == 404


def test_no_audio_link_when_gemini_cannot_speak(voice_client, monkeypatch):
    async def down(client, text, settings):
        raise gemini.GeminiError("down")

    monkeypatch.setattr(gemini, "speak", down)
    voice_client.state["heard"] = heard("change", paid=500, price=320)
    body = post_intent(voice_client).json()
    assert body["speech"]["am"] == f"AM-am: {say.change_prompt(500, 320)}"
    assert "speech_audio" not in body  # the app speaks the text instead


def test_speak_gemini_failure_is_502(voice_client, monkeypatch):
    async def down(client, text, settings):
        raise gemini.GeminiError("down")

    monkeypatch.setattr(gemini, "speak", down)
    clip = api.app.state.voice.clip_id("am", "AM-am: not made yet")
    assert voice_client.get(f"/speak/{clip}").status_code == 502


def test_phrases(voice_client):
    am = voice_client.get("/phrases", params={"lang": "am"}).json()
    assert set(am["phrases"]) == set(say.APP_PHRASES)
    assert am["phrases"]["counting"]["text"] == "AM-am: Counting."
    assert am["phrases"]["counting"]["audio"].startswith("/speak/")
    en = voice_client.get("/phrases", params={"lang": "en"}).json()
    assert en["phrases"]["counting"] == {"text": "Counting.", "audio": None}


def test_scan_answer_in_amharic(voice_client, fake):
    fake["labels"] = ["100", "50"]
    fake["regions"] = []
    r = post_scan(voice_client, lang="am")
    body = r.json()
    assert body["speech"]["am"].startswith("AM-am: ")
    assert body["speech"]["am"].endswith(body["speech"]["en"])
    assert body["speech_audio"].startswith("/speak/")
    assert "speech_todo" not in body


def test_errors_use_cached_translations(voice_client):
    # The startup warm-up translates the fixed phrases, so an error needs no Gemini call.
    for _ in range(100):
        if say.BAD_REQUEST in api.app.state.voice.translations["am"]:
            break
        time.sleep(0.01)
    r = voice_client.get("/scan/unknown-job")
    assert r.status_code == 404
    assert r.json()["speech"] == {"en": say.TRY_AGAIN}  # no lang on a poll for an unknown job
    files = {"image": ("x.jpg", b"not an image", "image/jpeg")}
    r = voice_client.post(
        "/scan", data={"intent": "count", "lang": "am", "wait": "true"}, files=files
    )
    assert r.status_code == 400
    assert r.json()["speech"]["am"] == f"AM-am: {say.BAD_REQUEST}"


def test_health_reports_voice(voice_client):
    assert voice_client.get("/health").json()["voice"] == {"gemini": True, "speaks": ["am"]}


def test_health_without_gemini(client):
    assert client.get("/health").json()["voice"] == {"gemini": False, "speaks": []}


def test_a_translation_crash_keeps_the_scan_answer(voice_client, fake, monkeypatch):
    async def broken(client, body, lang):
        raise RuntimeError("bug")

    monkeypatch.setattr(api.app.state.voice, "localize_body", broken)
    fake["labels"] = ["100", "50"]
    fake["regions"] = []
    r = post_scan(voice_client, lang="am")
    assert r.status_code == 200
    assert r.json()["speech"]["en"]  # English answer, not a crash
