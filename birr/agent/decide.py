"""The decision step: per-note reads + SAM regions -> total, guide or rescan.

Rules (docs/api.md): a total is spoken only when SAM's filtered count equals Muse's note count
and every note is a valid denomination. When SAM is unavailable, a Muse-only total is allowed
only if MUSE_ONLY_TOTALS is on and every label is valid; otherwise rescan, never guide.
"""

from __future__ import annotations

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


def decide(
    labels: list[str],
    regions: list[Region] | None,
    *,
    intent: str,
    paid: int | None,
    price: int | None,
    attempt: int,
    max_attempts: int,
    muse_only_totals: bool,
) -> dict:
    """Return outcome, total, change, notes, hint and English speech text."""
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
    all_valid = bool(values) and all(v is not None for v in values)
    sam_ok = regions is not None

    if sam_ok:
        counts_match = len(regions) == len(labels)
        if counts_match and all_valid:
            outcome = "total"
        elif not counts_match and regions:
            outcome = "guide"
        else:
            outcome = "rescan"
    else:
        outcome = "total" if (muse_only_totals and all_valid) else "rescan"

    result = {"outcome": outcome, "total": None, "change": None, "notes": notes, "hint": None}

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
        pos = position(target.box)
        notes.append(
            {
                "denomination": None,
                "confidence": round(target.score, 4),
                "box": [round(v, 4) for v in target.box],
                "status": "partial",
                "label": None,
            }
        )
        result["hint"] = {
            "note_index": len(notes) - 1,
            "position": pos,
            "covered_by": covered_by,
            "action": "slide_out",
        }
        text = say.guide_text(pos, "slide_out", reason)
    elif not labels and not regions:
        text = say.NO_NOTES
    else:
        text = say.RESCAN

    if outcome != "total" and attempt >= max_attempts:
        text = say.GIVE_UP
    result["speech_en"] = text
    return result
