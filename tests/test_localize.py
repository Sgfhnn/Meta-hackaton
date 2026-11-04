"""English answers -> Amharic and Oromo from templates. Every speech.py builder must round-trip."""

import itertools

import pytest

from birr.voice import localize
from birr.voice import speech as say
from birr.voice.templates import TEMPLATES

PILES = [[200, 100, 50], [100, 100, 100], [5], [10, 10, 5, 5, 5], [200] * 12, [50, 10]]
CHANGES = [
    {"counted": 180, "expected": 180, "difference": 0},
    {"counted": 150, "expected": 180, "difference": -30},
    {"counted": 200, "expected": 180, "difference": 20},
]


def english_answers():
    for pile in PILES:
        total = say.total_text(sum(pile), pile)
        yield total
        for chg in CHANGES:
            yield f"{total} {say.change_text(chg)}"
    for pos in localize.POSITIONS:
        for action, reason in itertools.product(
            ("slide_out", "lay_flat", "move_closer", "more_light"), ("covered", "merged", "hidden")
        ):
            yield say.guide_text(pos, action, reason)
    yield from (getattr(say, name) for name in localize.FIXED_NAMES)
    yield from say.APP_PHRASES.values()
    yield from (say.change_prompt(p, q) for p, q in [(500, 320), (320, 320), (1000, 5)])


@pytest.mark.parametrize("lang", ["am", "om"])
def test_every_backend_sentence_has_a_template(lang):
    for en in english_answers():
        rendered = localize.render(en, lang)
        assert rendered is not None, en
        shown, spoken = rendered
        assert shown and spoken
        assert not any(ch.isdigit() for ch in spoken), (en, spoken)  # MMS reads no digits


def test_total_parts():
    en = say.total_text(350, [200, 100, 50])
    assert localize.parse(en) == [
        ("total", {"amount": 350, "notes": [(1, 200), (1, 100), (1, 50)]})
    ]


def test_amharic_total_reads_right():
    shown, spoken = localize.render(say.total_text(350, [200, 100, 50]), "am")
    assert shown == "በአጠቃላይ 350 ብር አለዎት፦ አንድ ባለ 200 ብር፣ አንድ ባለ 100 ብር እና አንድ ባለ 50 ብር።"
    assert spoken.startswith("በአጠቃላይ ሦስት መቶ ሃምሳ ብር አለዎት፦ አንድ ባለ ሁለት መቶ ብር")


def test_change_after_total():
    en = f"{say.total_text(150, [100, 50])} {say.change_text(CHANGES[1])}"
    kinds = [kind for kind, _ in localize.parse(en)]
    assert kinds == ["total", "change"]
    shown, _ = localize.render(en, "am")
    assert "150" in shown and "180" in shown and "30" in shown


@pytest.mark.parametrize(
    "en",
    [
        "You have 350 birr: one 200 and one 100.",  # does not add up: keep English
        "You got 150 birr change. You should get 180 birr. You are 20 birr short.",
        "You paid 500 birr for 320 birr. Your change should be 100 birr. Spread it out, hold"
        " the phone over it and tap the screen.",
        "The note at the top shelf is folded. Lay it flat, then hold still.",  # unknown place
        "Something the templates have never seen.",
        "",
    ],
)
def test_anything_unexpected_stays_english(en):
    assert localize.render(en, "am") is None


def test_templates_cover_the_same_keys():
    am, om = TEMPLATES["am"], TEMPLATES["om"]
    assert set(am["fixed"]) == set(om["fixed"]) == set(localize.FIXED_NAMES)
    assert set(am["app"]) == set(om["app"]) == set(say.APP_PHRASES)
    assert set(am["positions"]) == set(om["positions"]) == set(localize.POSITIONS)


def test_permission_phrases():
    # First launch: said before the permission dialogs, and after both were allowed.
    assert "Swipe right to Allow" in say.APP_PHRASES["permissionsIntro"]
    assert say.APP_PHRASES["permissionsDone"] == "Thank you. All set."
    for lang in ("am", "om"):
        for key in ("permissionsIntro", "permissionsDone"):
            shown, spoken = localize.render(say.APP_PHRASES[key], lang)
            assert shown == TEMPLATES[lang]["app"][key] and spoken
