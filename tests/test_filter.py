from birr.agent.decide import Region
from birr.segment.filter import filter_regions, iou


def r(box, conf=0.95):
    return Region(box=box, confidence=conf)


def test_drops_low_confidence_fragments():
    kept = filter_regions([r((0, 0, 0.3, 0.3)), r((0.5, 0.5, 0.3, 0.3), conf=0.6)])
    assert len(kept) == 1


def test_drops_tiny_regions():
    assert filter_regions([r((0, 0, 0.05, 0.05))]) == []


def test_dedupes_overlapping_masks_keeping_most_confident():
    best = r((0, 0, 0.4, 0.4), conf=0.98)
    dup = r((0.01, 0.01, 0.4, 0.4), conf=0.9)
    assert filter_regions([dup, best]) == [best]


def test_keeps_separate_notes():
    assert len(filter_regions([r((0, 0, 0.3, 0.3)), r((0.6, 0.6, 0.3, 0.3))])) == 2


def test_iou_disjoint_is_zero():
    assert iou((0, 0, 0.1, 0.1), (0.5, 0.5, 0.1, 0.1)) == 0.0
