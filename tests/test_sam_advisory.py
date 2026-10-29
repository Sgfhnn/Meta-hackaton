from birr.agent.decide import decide
from birr.segment.filter import Region, filter_regions

R = Region(box=(0.1, 0.1, 0.3, 0.3), score=0.9)


def _d(reads, regions, advisory):
    return decide(reads, regions, intent="count", paid=None, price=None, attempt=1,
                  max_attempts=3, muse_only_totals=False, sam_advisory=advisory)  # fmt: skip


def test_advisory_speaks_agreeing_reads_despite_sam_count():
    reads = [["10", "100", "200", "10"], ["200", "10", "10", "100"]]
    regions = [R] * 5
    assert _d(reads, regions, False)["total"] is None
    out = _d(reads, regions, True)
    assert out["total"] == 320 and out["path"] == "agree_sam_advisory"


def test_advisory_never_speaks_disagreement_or_unclear():
    assert _d([["50", "5"], ["50", "10"]], [R, R], True)["total"] is None
    assert _d([["50", "unclear"], ["50", "unclear"]], [R, R], True)["total"] is None


def test_advisory_needs_two_reads_and_sam_up():
    assert _d([["50", "10"]], [R, R], True)["total"] is None
    assert _d([["50", "10"], ["10", "50"]], None, True)["total"] is None


def test_filter_thresholds_configurable():
    low = Region(box=(0.5, 0.5, 0.1, 0.08), score=0.55)
    kept, _ = filter_regions([R, low])
    assert len(kept) == 1
    kept, _ = filter_regions([R, low], min_score=0.5, min_area=0.005)
    assert len(kept) == 2


def test_sam_off_skips_call(monkeypatch):
    import asyncio

    from birr import scan
    from birr.config import Settings

    monkeypatch.setenv("SAM_OFF", "1")
    called = []

    async def boom(*a, **k):
        called.append(1)

    monkeypatch.setattr(scan.sam, "segment", boom)
    out = asyncio.run(scan._sam(None, b"", 1, 1, Settings()))
    assert out["ok"] is False and out["error"] == "disabled" and not called


def test_sam_off_with_muse_only_totals_speaks_agreement():
    out = decide([["50", "10"], ["10", "50"]], None, intent="count", paid=None, price=None,
                 attempt=1, max_attempts=3, muse_only_totals=True, sam_advisory=True)  # fmt: skip
    assert out["total"] == 60
