"""The decision step: Muse reads + SAM regions -> total, guide or rescan.

Rules (docs/api.md):
- Two reads (normal path): a total needs both reads to list the same notes (same multiset of
  valid denominations) AND SAM's filtered count to equal that note count.
- One read (the retry after a slow or failed two-read stage): never gives a total. It ends as
  guide when SAM's count differs, else rescan (single read + SAM spoke wrong totals in tests).
- SAM_ADVISORY on (Muse's narrowed design, Oct 30): two agreeing reads give the total and SAM's
  count is logged only (path agree_sam_advisory). Disagreement still ends as guide or rescan.
- SAM unavailable: a Muse-only total is allowed only if MUSE_ONLY_TOTALS is on and two reads
  agree; otherwise rescan, never guide.
"""

from __future__ import annotations

from collections import Counter

from birr.agent import money
from birr.segment.filter import Region
from birr.voice import speech as say


def position(box: tuple[float, float, float, float]) -> str:
    """User's point of view: image top is the far side, image bottom is near the user."""
    cx, cy = box[0] + box[2] / 2, box[1] + box[3] / 2
    depth = "far" if cy < 1 / 3 else "near" if cy > 2 / 3 else "middle"
    side = "left" if cx < 1 / 3 else "right" if cx > 2 / 3 else "center"
    if depth == "middle" and side == "center":
        return "middle"
    return f"{depth} {side}"


def _overlap(a: Region, b: Region) -> float:
    """Intersection over the smaller box: how much of one note sits under the other."""
    ax, ay, aw, ah = a.box
    bx, by, bw, bh = b.box
    ix = max(0.0, min(ax + aw, bx + bw) - max(ax, bx))
    iy = max(0.0, min(ay + ah, by + bh) - max(ay, by))
    smaller = min(a.area, b.area)
    return ix * iy / smaller if smaller > 0 else 0.0


def pick_target(regions: list[Region], muse_count: int) -> tuple[int, int | None, str]:
    """Return (region index, covered_by index or None, reason) for one hint."""
    if len(regions) < muse_count:
        # SAM sees fewer notes than Muse: likely two notes merged into one region.
        return max(range(len(regions)), key=lambda i: regions[i].area), None, "merged"
    best = (0.0, None, None)
    for i, a in enumerate(regions):
        for j, b in enumerate(regions):
            if i < j and (ov := _overlap(a, b)) > best[0]:
                under, top = (i, j) if a.area <= b.area else (j, i)
                best = (ov, under, top)
    if best[1] is not None:
        return best[1], best[2], "covered"
    return min(range(len(regions)), key=lambda i: regions[i].area), None, "hidden"


def reads_agree(reads: list[list[str]]) -> bool:
    """True when every read lists the same multiset of valid denominations (order ignored)."""
    if not reads:
        return False
    values = [[money.to_denomination(label) for label in r] for r in reads]
    if any(not v or any(x is None for x in v) for v in values):
        return False
    first = Counter(values[0])
    return all(Counter(v) == first for v in values[1:])


def decide(
    reads: list[list[str]],
    regions: list[Region] | None,
    *,
    intent: str,
    paid: int | None,
    price: int | None,
    attempt: int,
    max_attempts: int,
    muse_only_totals: bool,
    sam_advisory: bool = False,
) -> dict:
    """Return outcome, total, change, notes, hint and English speech text.

    `reads` holds one or two Muse reads of the same photo. Notes are reported from the first.
    """
    labels = reads[0] if reads else []
    values = [money.to_denomination(label) for label in labels]
    notes = [
        {
            "denomination": v,
            "confidence": None,  # the per-photo Muse prompt returns no confidence
            "box": None,  # the per-photo read is not localized, so notes are not matched to boxes
            "status": "read" if v is not None else "unclear",
            "label": label,
        }
        for label, v in zip(labels, values, strict=True)
    ]
    agreed = reads_agree(reads)  # with one read: every note valid
    same_count = len({len(r) for r in reads}) == 1
    sam_ok = regions is not None

    two_reads = len(reads) >= 2
    path = None
    if sam_advisory and two_reads and agreed and sam_ok:
        # Muse's narrowed design: two agreeing reads speak; SAM's count is logged only.
        outcome = "total"
        path = "agree_sam_match" if sam_ok and len(regions) == len(labels) else "agree_sam_advisory"
    elif sam_ok:
        counts_match = len(regions) == len(labels)
        if counts_match and agreed and two_reads:
            outcome = "total"
            path = "agree_sam_match"
        elif same_count and not counts_match and regions:
            outcome = "guide"
        else:
            outcome = "rescan"
    else:
        outcome = "total" if (muse_only_totals and two_reads and agreed) else "rescan"
        path = "agree_no_sam" if outcome == "total" else None

    result = {"outcome": outcome, "total": None, "change": None, "notes": notes, "hint": None,
              "path": path}  # fmt: skip

    if outcome == "total":
        amount = money.total(values)
        result["total"] = amount
        text = say.total_text(amount, values)
        if intent == "change":
            result["change"] = money.change(paid, price, amount)
            text = f"{text} {say.change_text(result['change'])}"
    elif outcome == "guide":
        idx, covered_by, reason = pick_target(regions, len(labels))
        target = regions[idx]
        action = "lay_flat" if reason == "merged" else "slide_out"
        pos = position(target.box)
        result["hint"] = {
            "note_index": None,  # the region has no per-note read, so no synthetic note is added
            "position": pos,
            "covered_by": covered_by,
            "action": action,
        }
        text = say.guide_text(pos, action, reason)
    elif not labels and not regions:
        text = say.NO_NOTES
    else:
        text = say.RESCAN

    if outcome != "total" and attempt >= max_attempts:
        text = say.GIVE_UP
    result["speech_en"] = text
    return result
