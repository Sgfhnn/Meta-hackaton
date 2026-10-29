"""Spoken text, built in code. English only for now.

Amharic and Oromo are produced by Gemini (translation + TTS) on the app side per the team plan,
so for lang "am" or "om" the backend returns the same English text and flags it in `speech_todo`.
"""

from __future__ import annotations

from collections import Counter

_NUM = {1: "one", 2: "two", 3: "three", 4: "four", 5: "five", 6: "six", 7: "seven",
        8: "eight", 9: "nine", 10: "ten"}  # fmt: skip


def _join(parts: list[str]) -> str:
    if len(parts) == 1:
        return parts[0]
    return ", ".join(parts[:-1]) + " and " + parts[-1]


def breakdown(denominations: list[int]) -> str:
    counts = Counter(denominations)
    parts = []
    for value in sorted(counts, reverse=True):
        n = counts[value]
        parts.append(f"{_NUM.get(n, str(n))} {value}" + ("s" if n > 1 else ""))
    return _join(parts)


def total_text(amount: int, denominations: list[int]) -> str:
    return f"You have {amount} birr: {breakdown(denominations)}."


def change_text(chg: dict) -> str:
    counted, expected, diff = chg["counted"], chg["expected"], chg["difference"]
    head = f"You got {counted} birr change. You should get {expected} birr."
    if diff == 0:
        return f"{head} Your change is correct."
    if diff < 0:
        return f"{head} You are {-diff} birr short."
    return f"{head} That is {diff} birr more than expected."


def guide_text(position: str, action: str, reason: str) -> str:
    where = f"at the {position}"
    if action == "lay_flat" and reason == "merged":
        text = "Spread the notes apart so none touch or overlap"
    elif action == "slide_out" and reason == "covered":
        text = f"One note is covered, {where}. Slide it out so I can see all of it"
    elif action == "slide_out":
        text = f"The note {where} is hard to see. Slide it away from the others"
    elif action == "lay_flat":
        text = f"The note {where} is folded. Lay it flat"
    elif action == "move_closer":
        text = f"Move the phone closer to the note {where}"
    else:
        text = "It is too dark. Move to more light"
    return text + ", then hold still."


RESCAN = "I could not read all the notes. Spread them out flat and hold the phone above them."
NO_NOTES = "I do not see any notes. Hold the phone above your notes and try again."
GIVE_UP = "Sorry, I cannot count these notes. Please ask someone you trust for help."
TRY_AGAIN = "Sorry, I couldn't check that. Please try again."
TOO_SLOW = "Sorry, that took too long. Please try again."
SLOW_RESCAN = "That took too long. Spread the notes out flat, hold the phone still and scan again."
STILL_COUNTING = "Still counting."
BAD_REQUEST = "Sorry, I couldn't use that photo. Please take it again."
NEED_PRICE = "Tell me how much you paid and the price, then scan your change."
VOICE_TODO = "Voice questions are not ready yet. Tap scan to count your notes."


def speech(en: str, lang: str) -> tuple[dict, str | None]:
    """Return (speech dict, todo note). Non-English keys carry English until Gemini translates."""
    if lang in ("am", "om"):
        return {"en": en, lang: en}, f"{lang} translation pending: Gemini translates and speaks"
    return {"en": en}, None
