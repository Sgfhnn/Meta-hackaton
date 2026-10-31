"""POST /assist: the voice assistant's turn. ASR and Muse are mocked; no network, no keys."""

import asyncio
import json

import httpx
import pytest
from fastapi.testclient import TestClient

from birr import api
from birr.config import Settings
from birr.voice import asr, assist, localize
from birr.voice import speech as say

M4A = b"\x00\x00\x00\x18ftypM4A fake audio"


def decision(action="none", lang="en", paid=None, price=None, needs=None, en="", am=""):
    return {"action": action, "lang": lang, "paid": paid, "price": price, "needs": needs,
            "reply_en": en, "reply_am": am}  # fmt: skip


@pytest.fixture
def ac(tmp_path, monkeypatch):
    """A client with the ASR service 'configured' and Muse's decision scripted per test."""
    monkeypatch.setenv("TRACE_DIR", str(tmp_path))
    monkeypatch.setenv("VOICE_CACHE_DIR", str(tmp_path / "voice"))
    monkeypatch.setenv("TTS_ENGINE", "off")
    monkeypatch.setenv("ASR_URL", "http://127.0.0.1:8002")
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    script = {"heard": "count my money", "decision": decision("scan"), "calls": []}

    async def transcribe(client, audio, mime, lang, settings):
        if isinstance(script["heard"], Exception):
            raise script["heard"]
        return script["heard"]

    async def decide(client, heard, lang, state, history, settings):
        script["calls"].append({"heard": heard, "lang": lang, "history": history, "state": state})
        if isinstance(script["decision"], Exception):
            raise script["decision"]
        return script["decision"]

    monkeypatch.setattr(asr, "transcribe", transcribe)
    monkeypatch.setattr(assist, "decide", decide)
    with TestClient(api.app) as c:
        c.script = script
        c.trace_dir = tmp_path
        yield c


def say_audio(c, lang="en", **data):
    files = {"audio": ("q.m4a", M4A, "audio/mp4")}
    return c.post("/assist", data={"lang": lang, **data}, files=files)


def test_count_opens_the_camera(ac):
    r = say_audio(ac)
    body = r.json()
    assert r.status_code == 200
    assert body["action"] == "scan" and body["intent"] == "count" and body["lang"] == "en"
    assert body["speech"] == {"en": say.ASSIST_SCAN}
    assert body["decided_by"] == "muse" and body["heard"] is True
    assert set(body["timing_ms"]) >= {"asr", "muse", "total"}


def test_amharic_stays_amharic_with_template_speech(ac):
    ac.script["heard"] = "ብሬን ቁጠርልኝ"
    ac.script["decision"] = decision("scan", lang="en")  # the model's language guess is ignored
    body = say_audio(ac, lang="am").json()
    assert body["lang"] == "am"
    assert body["speech"]["am"] == localize.render(say.ASSIST_SCAN, "am")[0]
    assert "speech_todo" not in body


def test_change_reads_amounts_back(ac):
    ac.script["decision"] = decision("change", paid=500, price=320)
    body = say_audio(ac).json()
    assert body["action"] == "change" and body["intent"] == "change"
    assert (body["paid"], body["price"]) == (500, 320)
    assert body["speech"]["en"] == say.change_prompt(500, 320)


def test_change_with_a_missing_amount_asks(ac):
    ac.script["decision"] = decision("change", paid=500, needs="ask")
    body = say_audio(ac).json()
    assert body["action"] == "none" and body["needs"] == "ask"
    assert body["paid"] == 500 and body["speech"]["en"] == say.NEED_PRICE


def test_change_uses_the_amount_said_earlier(ac):
    ac.script["decision"] = decision("change", price=320)
    state = json.dumps({"pending_paid": 500})
    body = say_audio(ac, state=state).json()
    assert body["action"] == "change" and (body["paid"], body["price"]) == (500, 320)


def test_price_over_paid_asks_again(ac):
    ac.script["decision"] = decision("change", paid=100, price=320)
    body = say_audio(ac).json()
    assert body["needs"] == "ask" and body["speech"]["en"] == say.PRICE_OVER_PAID


def test_switching_language(ac):
    ac.script["decision"] = decision("set_lang", lang="am")
    body = say_audio(ac, lang="en").json()
    assert body["action"] == "set_lang" and body["lang"] == "am"
    assert body["speech"]["am"] == "እሺ፣ ከአሁን ጀምሮ በአማርኛ እናገራለሁ።"


def test_a_free_answer_is_spoken_when_its_numbers_check_out(ac):
    ac.script["heard"] = "how much did I have"
    en, am = "You had 350 birr.", "350 ብር ነበረዎት።"
    ac.script["decision"] = decision("none", en=en, am=am)
    body = say_audio(ac, lang="am", state=json.dumps({"last_total": 350})).json()
    assert body["speech"] == {"en": en, "am": am}


def test_a_free_answer_with_an_invented_amount_is_replaced(ac):
    ac.script["decision"] = decision("none", en="You have 730 birr.", am="730 ብር አለዎት።")
    body = say_audio(ac, lang="am").json()
    assert body["speech"]["en"] == say.ASSIST_OFF_TOPIC


def test_a_free_answer_not_in_amharic_is_replaced(ac):
    ac.script["decision"] = decision("none", en="Keep notes flat.", am="Keep notes flat.")
    body = say_audio(ac, lang="am").json()
    assert body["speech"]["en"] == say.ASSIST_OFF_TOPIC


def test_muse_down_falls_back_to_keywords(ac):
    ac.script["heard"] = "please speak amharic"
    ac.script["decision"] = assist.AssistError("timeout")
    body = say_audio(ac).json()
    assert body["decided_by"] == "keywords" and body["action"] == "set_lang"
    assert body["lang"] == "am"


def test_silence(ac):
    ac.script["heard"] = ""
    body = say_audio(ac, lang="am").json()
    assert body["needs"] == "ask" and body["heard"] is False
    assert body["speech"]["en"] == say.NOT_HEARD
    assert ac.script["calls"] == []


def test_asr_down_is_a_spoken_502(ac):
    ac.script["heard"] = asr.AsrError("down")
    r = say_audio(ac)
    assert r.status_code == 502 and r.json()["speech"]["en"] == say.NOT_HEARD


def test_text_turns_and_session_history(ac):
    ac.post("/assist", data={"text": "I paid 500", "session_id": "s1"})
    ac.post("/assist", data={"text": "the price was 320", "session_id": "s1"})
    first, second = ac.script["calls"]
    assert first["history"] == []
    assert [m["role"] for m in second["history"]] == ["user", "assistant"]
    assert second["history"][0]["content"] == "I paid 500"


def test_no_audio_and_no_text(ac):
    r = ac.post("/assist", data={"lang": "en"})
    assert r.status_code == 400


def test_trace_never_holds_the_words(ac):
    ac.script["heard"] = "secret words 123"
    tid = say_audio(ac).json()["trace_id"]
    trace = (ac.trace_dir / f"{tid}.json").read_text()
    assert "secret" not in trace and '"outcome": "scan"' in trace


# ---- birr.voice.assist itself ----


def run_decide(handler, heard="count my money", lang="en"):
    async def go():
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            settings = Settings()
            return await assist.decide(client, heard, lang, assist.State(), [], settings)

    return asyncio.run(go())


def test_decide_reads_the_tool_call():
    seen = {}

    def handler(request):
        seen["body"] = json.loads(request.content)
        args = json.dumps(decision("change", paid=500, price=320.5))
        call = {"function": {"name": "respond", "arguments": args}}
        return httpx.Response(200, json={"choices": [{"message": {"tool_calls": [call]}}]})

    d = run_decide(handler)
    assert d["action"] == "change" and d["paid"] == 500 and d["price"] is None  # 320.5 dropped
    assert seen["body"]["tool_choice"]["function"]["name"] == "respond"
    assert seen["body"]["messages"][-1] == {"role": "user", "content": "count my money"}


def test_decide_reads_json_in_the_content():
    def handler(request):
        content = "ok " + json.dumps(decision("help"))
        return httpx.Response(200, json={"choices": [{"message": {"content": content}}]})

    assert run_decide(handler)["action"] == "help"


def test_decide_errors():
    with pytest.raises(assist.AssistError):
        run_decide(lambda r: httpx.Response(500))
    with pytest.raises(assist.AssistError):
        run_decide(
            lambda r: httpx.Response(200, json={"choices": [{"message": {"content": "hi"}}]})
        )


def test_keywords():
    assert assist.keywords("ብሬን ቁጠርልኝ", "am")["action"] == "scan"
    assert assist.keywords("switch to english", "am") == {
        **assist.keywords("x", "am"),
        "action": "set_lang",
        "lang": "en",
    }
    assert assist.keywords("check my change", "en")["needs"] == "ask"
    assert assist.keywords("what is the weather", "en")["action"] == "none"


def test_sessions_forget():
    s = assist.Sessions(ttl_s=0)
    s.add("a", "hi", "hello")
    assert s.history("a") == []
    s = assist.Sessions(max_turns=1)
    s.add("a", "1", "x")
    s.add("a", "2", "y")
    assert [m["content"] for m in s.history("a")] == ["2", "y"]


def test_state_parse_is_lenient():
    st = assist.State.parse('{"last_total": 350, "last_notes": [200, 100, 50, "x"], "paid": 500}')
    assert (st.last_total, st.last_notes, st.pending_paid) == (350, [200, 100, 50], 500)
    assert assist.State.parse("not json").last_total is None
