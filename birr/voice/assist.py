"""The voice assistant's turn (POST /assist): Muse Spark Open decides, code checks and speaks.

One turn: Meta Omnilingual ASR writes down what the user said (birr/voice/asr.py), then one Muse
call with a strict tool schema returns the action (scan, change, set_lang, repeat, help, stop or
none), any amounts it heard, and a short reply in English and Amharic. Code then decides what is
said:

- For every action, the spoken text is a fixed sentence from birr/voice/speech.py (Amharic from
  templates, numbers written by code). Only `none` (a question, small talk, "what did I have?")
  speaks the model's own reply, and only when every number in it is one the user said, one the
  app already told them, or a birr denomination. Otherwise the fixed "I can count your money..."
  is said instead, so the model can never put a new amount in a blind user's ear.
- The language is the one the user chose. Only `set_lang` changes it.
- Amounts the model heard are read back by the change prompt before any scan.

If Muse fails or times out, a small keyword matcher handles the obvious requests (count, change,
switch language, repeat, help). The last few turns of each session are kept in memory for 30
minutes so the model can follow a conversation ("and the price was 320"). Nothing is written to
disk: traces hold sizes, the action and timings, never the words.
"""

from __future__ import annotations

import json
import re
import time
from collections import OrderedDict, deque
from dataclasses import dataclass, field

import httpx

from birr.config import Settings
from birr.read.muse import _json_objects
from birr.voice import speech as say

ACTIONS = ("none", "scan", "change", "set_lang", "repeat", "help", "stop", "capture")
LANGS = ("en", "am")
DENOMINATIONS = {1, 5, 10, 50, 100, 200}
MAX_TURNS = 6  # user+assistant pairs kept per session
SESSION_TTL_S = 30 * 60
MAX_SESSIONS = 1000
_DIGITS = re.compile(r"\d+")

TOOL = {
    "type": "function",
    "function": {
        "name": "respond",
        "description": "Decide what the Birr app does next and what it says.",
        "parameters": {
            "type": "object",
            "properties": {
                "action": {"type": "string", "enum": list(ACTIONS)},
                "lang": {"type": "string", "enum": list(LANGS)},
                "paid": {"type": ["integer", "null"]},
                "price": {"type": ["integer", "null"]},
                "needs": {"type": ["string", "null"], "enum": ["ask", None]},
                "reply_en": {"type": "string"},
                "reply_am": {"type": "string"},
            },
            "required": ["action", "lang", "paid", "price", "needs", "reply_en", "reply_am"],
            "additionalProperties": False,
        },
    },
}

SYSTEM = """You are Birr, a voice assistant inside a phone app that helps blind and low-vision \
people in Ethiopia handle cash. The user cannot see the screen. They tap and speak; you answer \
by voice. What they said reaches you through speech recognition, which joins words, writes digits \
inside words ("አ5 መቶብር") and misspells words ("ber" for birr), so read through that.

What the app can do (pick exactly one action and call `respond`):
- scan: the user wants to know how much money they hold or what a note is ("count my money", \
"how much is this", "what note is this", "ብሬን ቁጠር", "ይህ ስንት ብር ነው", "ስንት ብር አለኝ"). The app \
opens the camera, guides them and counts. Choose scan whenever counting or reading notes would \
answer them; never tell them to tap a button.
- change: the user wants to check the change they got. Fill paid (birr they handed over) and price \
(what it cost) only with amounts they actually said, now or earlier in this conversation. If an \
amount is missing or only partly heard, use null and set needs="ask".
- set_lang: the user asks to switch language. Set lang to the language they asked for (en = \
English, am = Amharic). Only for an explicit request; never because of the language they spoke in.
- repeat: they want the last answer again.
- help: they ask what you can do or how to use the app.
- stop: they want you to stop, cancel or be quiet; while the camera is open this closes it \
("stop", "cancel", "close the camera", "አቁም", "ተወው").
- capture: only while the camera is open (camera_open is true below): take the photo now \
("take it", "now", "take the picture", "ready", "አንሳ", "አሁን", "ፎቶ አንሳ").
- none: anything else, such as a question about money handling, the notes in use (5, 10, 50, \
100 and 200 birr), or their last result. Answer it in reply_en/reply_am.

Rules:
- Never invent or guess an amount. Never say a total or a change you were not given below.
- Keep replies short: at most two short spoken sentences (under 30 words), plain words, no \
lists, no emoji, no markdown.
- Write reply_en in English and reply_am in natural Amharic (Ge'ez script, polite form) with the \
same meaning. Write numbers as digits.
- lang: the user's current language unless action is set_lang.
- Stay on the task of handling cash. For unrelated requests, say briefly what you can do.

App state: """


class AssistError(RuntimeError):
    pass


@dataclass
class State:
    """What the app tells us about the conversation so far (all optional)."""

    last_total: int | None = None
    last_notes: list[int] = field(default_factory=list)
    pending_paid: int | None = None
    pending_price: int | None = None
    camera_open: bool = False  # live guidance is running: "take it" / "stop" act on the camera

    @classmethod
    def parse(cls, raw: str | None) -> State:
        try:
            data = json.loads(raw) if raw else {}
        except ValueError:
            data = {}
        if not isinstance(data, dict):
            data = {}
        notes = data.get("last_notes") or []
        return cls(
            last_total=_amount(data.get("last_total")),
            last_notes=[n for n in notes if _amount(n)][:30] if isinstance(notes, list) else [],
            pending_paid=_amount(data.get("pending_paid", data.get("paid"))),
            pending_price=_amount(data.get("pending_price", data.get("price"))),
            camera_open=data.get("camera_open") is True,
        )

    def describe(self, lang: str) -> str:
        return json.dumps(
            {
                "language": {"en": "English", "am": "Amharic"}[lang],
                "last_total_birr": self.last_total,
                "last_notes": self.last_notes or None,
                "paid_said_earlier": self.pending_paid,
                "price_said_earlier": self.pending_price,
                "camera_open": self.camera_open,
            }
        )

    def numbers(self) -> set[int]:
        out = {n for n in (self.last_total, self.pending_paid, self.pending_price) if n}
        return out | set(self.last_notes)


def _amount(value) -> int | None:
    ok = isinstance(value, int) and not isinstance(value, bool) and 0 < value < 1_000_000
    return value if ok else None


class Sessions:
    """The last few turns per session_id, in memory only, forgotten after 30 idle minutes."""

    def __init__(self, ttl_s: float = SESSION_TTL_S, max_turns: int = MAX_TURNS):
        self.ttl_s, self.max_turns = ttl_s, max_turns
        self._data: OrderedDict[str, tuple[float, deque]] = OrderedDict()

    def _prune(self, now: float) -> None:
        while self._data:
            sid, (at, _) = next(iter(self._data.items()))
            if now - at <= self.ttl_s and len(self._data) <= MAX_SESSIONS:
                break
            self._data.pop(sid)

    def history(self, sid: str | None) -> list[dict]:
        now = time.monotonic()
        self._prune(now)
        if not sid or sid not in self._data:
            return []
        return list(self._data[sid][1])

    def add(self, sid: str | None, user: str, assistant: str) -> None:
        if not sid:
            return
        now = time.monotonic()
        turns = self._data.pop(sid, (now, deque(maxlen=2 * self.max_turns)))[1]
        turns.append({"role": "user", "content": user})
        turns.append({"role": "assistant", "content": assistant})
        self._data[sid] = (now, turns)
        self._prune(now)


def _decision(data: dict, lang: str) -> dict:
    action = data.get("action")
    target = data.get("lang")
    return {
        "action": action if action in ACTIONS else "none",
        "lang": target if target in LANGS else lang,
        "paid": _amount(data.get("paid")),
        "price": _amount(data.get("price")),
        "needs": "ask" if data.get("needs") == "ask" else None,
        "reply_en": str(data.get("reply_en") or "").strip(),
        "reply_am": str(data.get("reply_am") or "").strip(),
    }


async def decide(
    client: httpx.AsyncClient,
    heard: str,
    lang: str,
    state: State,
    history: list[dict],
    settings: Settings,
) -> dict:
    """One Muse call -> the model's decision (not yet checked)."""
    messages = [{"role": "system", "content": SYSTEM + state.describe(lang)}]
    messages += history
    messages.append({"role": "user", "content": heard})
    body = {
        "model": settings.muse_model,
        "temperature": 0,
        "messages": messages,
        "tools": [TOOL],
        "tool_choice": {"type": "function", "function": {"name": "respond"}},
    }
    if settings.muse_reasoning_effort:
        body["reasoning_effort"] = settings.muse_reasoning_effort
    headers = {"Authorization": f"Bearer {settings.muse_key}"}
    try:
        resp = await client.post(
            settings.muse_url, json=body, headers=headers, timeout=settings.assist_timeout_s
        )
        resp.raise_for_status()
        message = resp.json()["choices"][0]["message"]
    except (httpx.HTTPError, KeyError, IndexError, TypeError, ValueError) as exc:
        raise AssistError(f"Muse assist call failed: {type(exc).__name__}") from exc
    data = None
    for call in message.get("tool_calls") or []:
        try:
            data = json.loads(call["function"]["arguments"])
            break
        except (KeyError, TypeError, ValueError):
            continue
    if data is None:  # some servers answer in the content instead of a tool call
        found = (o for o in _json_objects(message.get("content") or "") if "action" in o)
        data = next(found, None)
    if not isinstance(data, dict):
        raise AssistError("no decision in Muse reply")
    return _decision(data, lang)


_KEYWORDS = [
    ("set_lang:am", ("amharic", "አማርኛ", "amharigna", "በአማርኛ")),
    ("set_lang:en", ("english", "እንግሊዝኛ", "ingilizigna", "በእንግሊዝኛ")),
    ("repeat", ("repeat", "again", "ድገም", "ደግመው", "እንደገና በል")),
    ("help", ("help", "what can you do", "እርዳኝ", "ምን ትችላለህ")),
    ("stop", ("stop", "quiet", "ዝም", "አቁም")),
    ("change", ("change", "መልስ", "ዝርዝር")),
    ("scan", ("count", "how much", "money", "ቁጠር", "ቁጠሪ", "ስንት", "ብር", "ber", "birr")),
]


def keywords(heard: str, lang: str) -> dict:
    """The fallback when Muse is down: the obvious requests by keyword. Never any amounts."""
    text = heard.lower()
    action, target = "none", lang
    for name, words in _KEYWORDS:
        if any(w in text for w in words):
            action, _, maybe = name.partition(":")
            target = maybe or lang
            break
    return {
        "action": action, "lang": target, "paid": None, "price": None,
        "needs": "ask" if action == "change" else None, "reply_en": "", "reply_am": "",
    }  # fmt: skip


# While the camera is open, a short command acts at once, without a model call (the user is
# holding the phone still and waiting). Matched on the whole utterance, so "now count my change"
# still goes to Muse.
_CAPTURE = {
    "take it", "take", "now", "take it now", "take the photo", "take the picture", "take a photo",
    "take a picture", "ready", "okay take it", "ok take it", "capture", "shoot", "go",
    "አንሳ", "አሁን", "አሁን አንሳ", "ፎቶ አንሳ", "ፎቶውን አንሳ", "አንሺ", "ያዝ", "ዝግጁ",
}  # fmt: skip
_STOP = {
    "stop", "cancel", "close", "close it", "close the camera", "never mind", "nevermind",
    "stop it", "quit", "አቁም", "አቁሚ", "ተወው", "ተዪው", "ዝጋ", "ካሜራውን ዝጋ", "ይቅር", "በቃ",
}  # fmt: skip
_PUNCT = re.compile(r"[^\w\s]|[\u1360-\u1368]")  # Latin and Ethiopic punctuation


def camera_command(heard: str) -> str | None:
    """capture / stop for a short command said while the camera is open, else None."""
    text = " ".join(_PUNCT.sub(" ", heard.lower()).split())
    text = re.sub(r"^(please|ok|okay|birr|እባክህ|እባክሽ|እባክዎ)\s+", "", text)
    text = re.sub(r"\s+(please|now please|እባክህ|እባክዎ)$", "", text)
    if text in _CAPTURE:
        return "capture"
    if text in _STOP:
        return "stop"
    return None


def numbers_allowed(text: str, heard: str, state: State, extra: set[int]) -> bool:
    """Every number in a model reply was said by the user, told to them by the app (state), heard
    as an amount, or is a birr denomination."""
    allowed = {int(n) for n in _DIGITS.findall(heard)} | state.numbers() | extra | DENOMINATIONS
    return all(int(n) in allowed for n in _DIGITS.findall(text))


_ETHIOPIC = re.compile(r"[\u1200-\u137f]")
_LATIN = re.compile(r"[A-Za-z]")
_OTHER_SCRIPT = re.compile(r"[^\u1200-\u137f\u0000-\u024f\u2000-\u206f]")  # e.g. Arabic, emoji
_SENTENCE_END = re.compile(r"(?<=[.!?\u1362\u1367\u1368])\s+")
MAX_SENTENCES = 2
MAX_CHARS = 240


def looks_amharic(text: str) -> bool:
    ok = bool(text) and not _OTHER_SCRIPT.search(text)
    return ok and len(_ETHIOPIC.findall(text)) > 2 * len(_LATIN.findall(text))


def first_sentences(text: str, n: int = MAX_SENTENCES) -> str:
    """The first n sentences (English . ! ? or Amharic ። ፧ ፨)."""
    return " ".join(_SENTENCE_END.split(text.strip())[:n])


@dataclass
class Turn:
    """What the endpoint answers: action and amounts, plus the English text to speak, or a model
    reply (en + am) for `none`."""

    action: str
    lang: str
    intent: str | None = None
    paid: int | None = None
    price: int | None = None
    needs: str | None = None
    text: str = ""  # English sentence from speech.py (localized by templates)
    free_en: str | None = None  # model reply, spoken only when checked
    free_am: str | None = None


def resolve(d: dict, heard: str, lang: str, state: State) -> Turn:
    """Model decision -> what the app does and says, with every rule applied in code."""
    action = d["action"]
    if action == "set_lang":
        target = d["lang"] if d["lang"] in LANGS else lang
        return Turn("set_lang", target, text=say.LANG_SET_AM if target == "am" else say.LANG_SET_EN)
    if action == "scan":
        return Turn("scan", lang, intent="count", text=say.ASSIST_SCAN)
    if action == "change":
        paid = d["paid"] or state.pending_paid
        price = d["price"] or state.pending_price
        if paid is None or price is None:
            return Turn("none", lang, paid=paid, price=price, needs="ask", text=say.NEED_PRICE)
        if paid < price:
            return Turn("none", lang, needs="ask", text=say.PRICE_OVER_PAID)
        text = say.change_prompt(paid, price)
        if paid == price:
            return Turn("none", lang, paid=paid, price=price, text=text)
        return Turn("change", lang, intent="change", paid=paid, price=price, text=text)
    if action == "repeat":
        return Turn("repeat", lang, text=say.ASSIST_REPEAT)
    if action == "help":
        return Turn("help", lang, text=say.ASSIST_HELP)
    if action == "capture":
        if state.camera_open:
            return Turn("capture", lang, text=say.ASSIST_CAPTURE)
        return Turn("scan", lang, intent="count", text=say.ASSIST_SCAN)  # no camera yet: open it
    if action == "stop":
        if state.camera_open:
            return Turn("stop", lang, text=say.ASSIST_CLOSED)
        return Turn("stop", lang, text=say.ASSIST_STOP)
    # none: the model's own words, if they pass the checks
    en, am = first_sentences(d["reply_en"]), first_sentences(d["reply_am"])
    extra = {n for n in (d["paid"], d["price"]) if n}
    ok = bool(en) and len(en) <= MAX_CHARS and not _OTHER_SCRIPT.search(en)
    ok = ok and numbers_allowed(en, heard, state, extra)
    if ok and lang == "am":
        ok = looks_amharic(am) and len(am) <= MAX_CHARS
        ok = ok and numbers_allowed(am, heard, state, extra)
        ok = ok and sorted(_DIGITS.findall(en)) == sorted(_DIGITS.findall(am))
    if not ok:
        return Turn("none", lang, needs=d["needs"], text=say.ASSIST_OFF_TOPIC)
    return Turn("none", lang, needs=d["needs"], free_en=en, free_am=am if lang == "am" else None)
