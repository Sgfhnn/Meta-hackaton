"""Numbers as words, in code, for spoken Amharic and Oromo.

The voice (Meta MMS-TTS) has no digits, and an amount a blind user hears must never depend on a
model. Draft spellings: a native speaker checks them (tests/test_numbers.py lists the cases).
"""

from __future__ import annotations

_AM_UNITS = ["", "አንድ", "ሁለት", "ሦስት", "አራት", "አምስት", "ስድስት", "ሰባት", "ስምንት", "ዘጠኝ"]
_AM_TENS = ["", "አሥር", "ሃያ", "ሠላሳ", "አርባ", "ሃምሳ", "ስልሳ", "ሰባ", "ሰማንያ", "ዘጠና"]

_OM_UNITS = ["", "tokko", "lama", "sadii", "afur", "shan", "jaha", "torba", "saddeet", "sagal"]
_OM_TENS = ["", "kudhan", "digdama", "soddoma", "afurtama", "shantama", "jaatama", "torbaatama",
            "saddeettama", "sagaltama"]  # fmt: skip

LIMIT = 1_000_000  # larger numbers stay digits; no birr pile gets near this


def amharic(n: int) -> str:
    """350 -> "ሦስት መቶ ሃምሳ", 115 -> "መቶ አሥራ አምስት", 1250 -> "አንድ ሺህ ሁለት መቶ ሃምሳ"."""
    if n == 0:
        return "ዜሮ"
    if not 0 < n < LIMIT:
        return str(n)
    parts = []
    thousands, rest = divmod(n, 1000)
    if thousands:
        parts.append(f"{amharic(thousands)} ሺህ")
    hundreds, rest = divmod(rest, 100)
    if hundreds:
        parts.append("መቶ" if hundreds == 1 else f"{_AM_UNITS[hundreds]} መቶ")
    tens, units = divmod(rest, 10)
    if tens == 1 and units:
        parts.append(f"አሥራ {_AM_UNITS[units]}")
    else:
        if tens:
            parts.append(_AM_TENS[tens])
        if units:
            parts.append(_AM_UNITS[units])
    return " ".join(parts)


def oromo(n: int) -> str:
    """350 -> "dhibba sadii fi shantama", 21 -> "digdamii tokko"."""
    if n == 0:
        return "zeeroo"
    if not 0 < n < LIMIT:
        return str(n)
    parts = []
    thousands, rest = divmod(n, 1000)
    if thousands:
        parts.append("kuma" if thousands == 1 else f"kuma {oromo(thousands)}")
    hundreds, rest = divmod(rest, 100)
    if hundreds:
        parts.append("dhibba" if hundreds == 1 else f"dhibba {_OM_UNITS[hundreds]}")
    tens, units = divmod(rest, 10)
    if tens == 1:
        parts.append("kudhan" if not units else f"kudha {_OM_UNITS[units]}")
    elif tens:
        # digdama + tokko -> digdamii tokko
        parts.append(_OM_TENS[tens] if not units else f"{_OM_TENS[tens][:-1]}ii {_OM_UNITS[units]}")
    elif units:
        parts.append(_OM_UNITS[units])
    return " fi ".join(parts)


WORDS = {"am": amharic, "om": oromo}
