"""Drop SAM fragments and duplicates before counting notes.

On overlapping piles SAM returns seam and fragment masks (13 masks for ~9
notes on dev), so the raw mask count must never feed the total.
"""

from __future__ import annotations

from birr.agent.decide import Region

MIN_CONFIDENCE = 0.85
MIN_AREA = 0.01  # fraction of the image
MAX_IOU = 0.6


def filter_regions(
    regions: list[Region],
    min_confidence: float = MIN_CONFIDENCE,
    min_area: float = MIN_AREA,
    max_iou: float = MAX_IOU,
) -> list[Region]:
    kept: list[Region] = []
    candidates = sorted(regions, key=lambda r: r.confidence, reverse=True)
    for region in candidates:
        if region.confidence < min_confidence:
            continue
        if region.box[2] * region.box[3] < min_area:
            continue
        if any(iou(region.box, k.box) > max_iou for k in kept):
            continue
        kept.append(region)
    return kept


def iou(a: tuple[float, ...], b: tuple[float, ...]) -> float:
    ax, ay, aw, ah = a
    bx, by, bw, bh = b
    ix = max(0.0, min(ax + aw, bx + bw) - max(ax, bx))
    iy = max(0.0, min(ay + ah, by + bh) - max(ay, by))
    inter = ix * iy
    union = aw * ah + bw * bh - inter
    return inter / union if union > 0 else 0.0
