"""English answer -> the same answer in Amharic or Oromo, from fixed templates. No model involved.

The backend writes every answer in English with the builders in birr/voice/speech.py. This module
reads that English back into its parts (fixed phrase, total, change, hint, change prompt) and fills
in the templates of birr/voice/templates.py. It returns two versions: digits for the screen, and
words for the voice (MMS reads no digits). Any sentence it does not recognise, or whose numbers do
not add up, returns None, and the caller keeps English.
"""

from __future__ import annotations

import re
from collections.abc import Callable

from birr.voice import speech as say
from birr.voice.numbers import WORDS
from birr.voice.templates import TEMPLATES

FIXED_NAMES = (
    "RESCAN", "NO_NOTES", "GIVE_UP", "TRY_AGAIN", "TOO_SLOW", "SLOW_RESCAN", "STILL_COUNTING",
    "BAD_REQUEST", "NEED_PRICE", "VOICE_TODO", "COUNT_PROMPT", "INTENT_UNKNOWN", "PRICE_OVER_PAID",
    "BAD_AUDIO", "NOT_HEARD", "FRAME_OK", "FRAME_DARK", "FRAME_BRIGHT", "FRAME_BLURRY",
    "FRAME_NO_NOTES", "FRAME_FAR", "FRAME_CUT_LEFT", "FRAME_CUT_RIGHT", "FRAME_CUT_TOP",
    "FRAME_CUT_BOTTOM", "ASSIST_SCAN", "ASSIST_HELP", "ASSIST_REPEAT", "ASSIST_STOP",
    "ASSIST_OFF_TOPIC", "LANG_SET_EN", "LANG_SET_AM",
)  # fmt: skip
POSITIONS = (
    "far left", "far center", "far right", "middle left", "middle", "middle right",
    "near left", "near center", "near right",
)  # fmt: skip
_COUNT_WORDS = {"one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6, "seven": 7,
                "eight": 8, "nine": 9, "ten": 10}  # fmt: skip

_POS = "|".join(re.escape(p) for p in sorted(POSITIONS, key=len, reverse=True))
_TOTAL = re.compile(r"You have (\d+) birr: ([^.]+)\.")
_ITEM = re.compile(r"(one|two|three|four|five|six|seven|eight|nine|ten|\d+) (\d+)s?")
_CHANGE = re.compile(
    r"You got (\d+) birr change\. You should get (\d+) birr\. "
    r"(?:(Your change is correct\.)|You are (\d+) birr short\.|That is (\d+) birr more than "
    r"expected\.)"
)
_CHANGE_PROMPT = re.compile(
    r"You paid (\d+) birr for (\d+) birr\. (?:(You get no change\.)|Your change should be (\d+) "
    r"birr\. Spread it out, hold the phone over it and tap the screen\.)"
)
_GUIDES = [
    ("merged", re.compile(r"Spread the notes apart so none touch or overlap, then hold still\.")),
    ("covered", re.compile(
        rf"One note is covered, at the ({_POS})\. Slide it out so I can see all of it, then hold "
        r"still\.")),
    ("hidden", re.compile(
        rf"The note at the ({_POS}) is hard to see\. Slide it away from the others, then hold "
        r"still\.")),
    ("folded", re.compile(rf"The note at the ({_POS}) is folded\. Lay it flat, then hold still\.")),
    ("closer", re.compile(
        rf"Move the phone closer to the note at the ({_POS}), then hold still\.")),
    ("dark", re.compile(r"It is too dark\. Move to more light, then hold still\.")),
]  # fmt: skip


def _fixed_texts() -> dict[str, tuple[str, str]]:
    texts = {getattr(say, name): ("fixed", name) for name in FIXED_NAMES}
    texts.update({text: ("app", key) for key, text in say.APP_PHRASES.items()})
    return texts


def _breakdown(text: str) -> list[tuple[int, int]] | None:
    items = text.replace(" and ", ", ").split(", ")
    out = []
    for item in items:
        m = _ITEM.fullmatch(item)
        if not m:
            return None
        count = _COUNT_WORDS.get(m[1]) or int(m[1])
        out.append((count, int(m[2])))
    return out


def parse(en: str) -> list[tuple[str, dict]] | None:
    """English answer -> its parts, or None if any piece is not one of speech.py's sentences."""
    fixed = _fixed_texts()
    parts: list[tuple[str, dict]] = []
    rest = en.strip()
    while rest:
        for text, (kind, key) in sorted(fixed.items(), key=lambda kv: -len(kv[0])):
            if rest.startswith(text):
                parts.append((kind, {"key": key}))
                rest = rest[len(text) :].lstrip()
                break
        else:
            part, rest = _parse_one(rest)
            if part is None:
                return None
            parts.append(part)
    return parts or None


def _parse_one(rest: str) -> tuple[tuple[str, dict] | None, str]:
    if m := _TOTAL.match(rest):
        notes = _breakdown(m[2])
        amount = int(m[1])
        if notes is None or sum(c * d for c, d in notes) != amount:
            return None, rest
        return ("total", {"amount": amount, "notes": notes}), rest[m.end() :].lstrip()
    if m := _CHANGE.match(rest):
        counted, expected = int(m[1]), int(m[2])
        diff = 0 if m[3] else (-int(m[4]) if m[4] else int(m[5]))
        if diff != counted - expected or (diff == 0) != bool(m[3]):
            return None, rest
        part = ("change", {"counted": counted, "expected": expected, "diff": diff})
        return part, rest[m.end() :].lstrip()
    if m := _CHANGE_PROMPT.match(rest):
        paid, price = int(m[1]), int(m[2])
        if m[3] and paid != price or m[4] and int(m[4]) != paid - price:
            return None, rest
        return ("change_prompt", {"paid": paid, "price": price}), rest[m.end() :].lstrip()
    for kind, pattern in _GUIDES:
        if m := pattern.match(rest):
            position = m[1] if pattern.groups else None
            return ("guide", {"kind": kind, "position": position}), rest[m.end() :].lstrip()
    return None, rest


def _render_part(part: tuple[str, dict], t: dict, num: Callable[[int], str], words) -> str | None:
    kind, p = part
    if kind == "fixed":
        return t["fixed"].get(p["key"])
    if kind == "app":
        return t["app"].get(p["key"])
    if kind == "total":
        notes = ""
        if t["note"]:
            items = [t["note"].format(count=words(c), denom=num(d)) for c, d in p["notes"]]
            notes = (
                items[0] if len(items) == 1 else t["comma"].join(items[:-1]) + t["and"] + items[-1]
            )
        return t["total"].format(amount=num(p["amount"]), notes=notes)
    if kind == "change":
        head = t["change"].format(counted=num(p["counted"]), expected=num(p["expected"]))
        diff = p["diff"]
        if diff == 0:
            return f"{head} {t['change_ok']}"
        tail = t["change_short" if diff < 0 else "change_more"].format(diff=num(abs(diff)))
        return f"{head} {tail}"
    if kind == "change_prompt":
        paid, price = p["paid"], p["price"]
        if paid == price:
            return t["change_prompt_none"].format(paid=num(paid), price=num(price))
        return t["change_prompt"].format(paid=num(paid), price=num(price), change=num(paid - price))
    if kind == "guide":
        position = t["positions"].get(p["position"]) if p["position"] else None
        if p["position"] and position is None:
            return None
        return t["guide"][p["kind"]].format(position=position)
    return None


def render(en: str, lang: str) -> tuple[str, str] | None:
    """(text for the screen, text for the voice) in `lang`, or None to keep English."""
    t = TEMPLATES.get(lang)
    parts = parse(en) if t else None
    if not parts:
        return None
    words = WORDS[lang]
    shown, spoken = [], []
    for part in parts:
        a = _render_part(part, t, str, words)  # amounts as digits, note counts as words
        b = _render_part(part, t, words, words)  # everything as words
        if a is None or b is None:
            return None
        shown.append(a)
        spoken.append(b)
    return " ".join(shown), " ".join(spoken)
