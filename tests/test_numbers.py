"""Numbers as words for the voice. DRAFT spellings: these are the cases for a native speaker."""

import pytest

from birr.voice.numbers import amharic, oromo


@pytest.mark.parametrize(
    "n, words",
    [
        (5, "አምስት"),
        (10, "አሥር"),
        (11, "አሥራ አንድ"),
        (20, "ሃያ"),
        (50, "ሃምሳ"),
        (75, "ሰባ አምስት"),
        (100, "መቶ"),
        (115, "መቶ አሥራ አምስት"),
        (200, "ሁለት መቶ"),
        (350, "ሦስት መቶ ሃምሳ"),
        (555, "አምስት መቶ ሃምሳ አምስት"),
        (1000, "አንድ ሺህ"),
        (1250, "አንድ ሺህ ሁለት መቶ ሃምሳ"),
        (20000, "ሃያ ሺህ"),
    ],
)
def test_amharic(n, words):
    assert amharic(n) == words


@pytest.mark.parametrize(
    "n, words",
    [
        (5, "shan"),
        (10, "kudhan"),
        (15, "kudha shan"),
        (21, "digdamii tokko"),
        (50, "shantama"),
        (55, "shantamii shan"),
        (100, "dhibba"),
        (115, "dhibba fi kudha shan"),
        (200, "dhibba lama"),
        (350, "dhibba sadii fi shantama"),
        (1000, "kuma"),
        (1250, "kuma fi dhibba lama fi shantama"),
    ],
)
def test_oromo(n, words):
    assert oromo(n) == words


@pytest.mark.parametrize("words", [amharic, oromo])
def test_no_digits_in_any_amount(words):
    for n in range(1, 3001):
        assert not any(ch.isdigit() for ch in words(n)), n
