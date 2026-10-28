import json

import pytest

from birr.read.muse import PROMPT, MuseError, label_for, parse_labels


def reply(notes):
    return "Here you go:\n```json\n" + json.dumps({"notes": notes}) + "\n```"


def test_two_agreeing_signals_identify_a_note():
    notes = [{"value": 100, "evidence": ["numeral", "colour"], "status": "read"}]
    assert parse_labels(reply(notes)) == ["100"]


def test_colour_alone_is_unclear():
    # The L20 colour-only rerun invented two 5s this way.
    notes = [{"value": 5, "evidence": ["colour"], "status": "read"}]
    assert parse_labels(reply(notes)) == ["unclear"]


def test_repeated_signal_counts_once():
    assert (
        label_for({"value": 200, "evidence": ["colour", "colour"], "status": "read"}) == "unclear"
    )


def test_unknown_signals_are_ignored():
    assert label_for({"value": 50, "evidence": ["vibes", "colour"], "status": "read"}) == "unclear"


def test_partial_note_is_unclear_even_with_signals():
    assert (
        label_for({"value": 10, "evidence": ["geez", "picture"], "status": "partial"}) == "unclear"
    )


def test_invalid_or_missing_value_is_unclear():
    assert label_for({"value": 20, "evidence": ["numeral", "text"], "status": "read"}) == "unclear"
    assert label_for({"value": None, "evidence": ["colour"], "status": "unclear"}) == "unclear"
    assert label_for({"evidence": ["numeral", "geez"], "status": "read"}) == "unclear"


def test_mixed_pile_like_l12():
    # L12 truth: 100, 10, 10, 50, 200 = 370; one note seen by colour alone stays unclear.
    notes = [
        {"value": 100, "evidence": ["numeral", "colour"], "status": "read"},
        {"value": 10, "evidence": ["picture", "colour"], "status": "read"},
        {"value": 10, "evidence": ["geez", "colour"], "status": "read"},
        {"value": 50, "evidence": ["picture", "colour"], "status": "read"},
        {"value": 200, "evidence": ["colour"], "status": "read"},
    ]
    assert parse_labels(reply(notes)) == ["100", "10", "10", "50", "unclear"]


def test_nested_json_is_parsed():
    text = '{"notes": [{"value": 200, "evidence": ["geez", "picture"], "status": "read"}]}'
    assert parse_labels(text) == ["200"]


def test_older_bare_label_replies_still_work():
    assert parse_labels('{"notes": ["100", "Unclear"]}') == ["100", "unclear"]


def test_no_json_raises():
    with pytest.raises(MuseError):
        parse_labels("I can see some money.")


def test_prompt_carries_the_knowledge_pack():
    for fact in ("፪፻", "ibex", "Harar gate", "three chimneys", "camels", "Colour alone"):
        assert fact in PROMPT
