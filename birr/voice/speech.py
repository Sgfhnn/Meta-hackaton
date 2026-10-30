"""Spoken text, built in code, in English.

Amharic and Oromo come from birr/voice/service.py: Gemini translates these English phrases (numbers
checked) and speaks them. Until a phrase has a checked translation, lang "am" or "om" gets the
English text, flagged in `speech_todo`.
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
COUNT_PROMPT = "Spread your notes, hold the phone over them and tap the screen."
INTENT_UNKNOWN = (
    "Sorry, I did not understand. Ask how much money you have, "
    "or say what you paid and the price to check your change."
)
PRICE_OVER_PAID = (
    "The price you said is more than you paid. Tell me again how much you paid and the price."
)
BAD_AUDIO = "Sorry, I couldn't use that recording. Please ask again."
NOT_HEARD = "Sorry, I couldn't hear that. Please try again."


def change_prompt(paid: int, price: int) -> str:
    head = f"You paid {paid} birr for {price} birr."
    if paid == price:
        return f"{head} You get no change."
    change = f"Your change should be {paid - price} birr."
    return f"{head} {change} Spread it out, hold the phone over it and tap the screen."


# Every fixed backend phrase, translated ahead of time when Gemini is configured.
FIXED = [
    RESCAN, NO_NOTES, GIVE_UP, TRY_AGAIN, TOO_SLOW, SLOW_RESCAN, STILL_COUNTING, BAD_REQUEST,
    NEED_PRICE, VOICE_TODO, COUNT_PROMPT, INTENT_UNKNOWN, PRICE_OVER_PAID, BAD_AUDIO, NOT_HEARD,
]  # fmt: skip

# The app's own prompts (app/src/voice.ts PROMPTS, same keys and English). GET /phrases returns
# them translated, with audio, so the app can speak them even when the network is down later.
APP_PHRASES = {
    "counting": "Counting.",
    "stillCounting": "Still counting.",
    "failed": "Sorry, I could not count that. Please tap to try again.",
    "noNetwork": "I cannot reach the server. Check the internet connection and tap to try again.",
    "giveUp": "I cannot count these notes. Please spread them out flat and start again.",
    "busy": "Still counting, please wait.",
    "cameraNeeded": "This app needs the camera to count your money. Tap the screen to allow it.",
    "listening": "Listening.",
    "tooShort": "Hold the screen while you speak, then let go.",
    "micNeeded": "To ask by voice, allow the microphone. You can still tap to count.",
    "heardFailed": "Sorry, I couldn't hear that. Please try again.",
}


def speech(en: str, lang: str) -> tuple[dict, str | None]:
    """Return (speech dict, todo note). Non-English keys carry English until Gemini translates."""
    if lang in ("am", "om"):
        return {"en": en, lang: en}, f"{lang} translation pending: Gemini translates and speaks"
    return {"en": en}, None
