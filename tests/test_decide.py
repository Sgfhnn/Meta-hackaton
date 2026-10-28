from birr.agent.decide import Note, Region, decide


def note(d, status="read"):
    return Note(denomination=d, confidence=0.95, status=status)


def region(x=0.1, y=0.1, w=0.3, h=0.2):
    return Region(box=(x, y, w, h), confidence=0.97)


def test_total_when_counts_agree():
    d = decide([region(), region(0.5)], [note(100), note(50)])
    assert d.outcome == "total"
    assert d.total == 150


def test_five_birr_is_in_scope():
    d = decide([region()], [note(5)])
    assert (d.outcome, d.total) == ("total", 5)


def test_sam_down_always_rescans():
    d = decide(None, [note(100)])
    assert d.outcome == "rescan"
    assert d.total is None


def test_unclear_note_rescans():
    assert decide([region()], [note(None, "unclear")]).outcome == "rescan"


def test_out_of_scope_denomination_rescans():
    assert decide([region()], [note(20)]).outcome == "rescan"


def test_partial_note_guides_to_smallest_region():
    small = region(0.6, 0.6, 0.1, 0.1)
    d = decide([region(), small], [note(100), note(None, "partial")])
    assert d.outcome == "guide"
    assert d.target == small
    assert d.total is None


def test_sam_found_more_guides():
    d = decide([region(), region(0.5)], [note(100)])
    assert d.outcome == "guide"


def test_sam_found_fewer_rescans():
    d = decide([region()], [note(100), note(50)])
    assert d.outcome == "rescan"


def test_nothing_found_rescans():
    assert decide([], []).outcome == "rescan"


def test_change_check_short():
    d = decide([region(), region(0.5)], [note(100), note(50)], "change", paid=500, price=300)
    assert d.change == {"expected": 200, "counted": 150, "difference": -50}
