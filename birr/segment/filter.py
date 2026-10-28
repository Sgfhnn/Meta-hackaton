"""Note filter: score threshold, minimum area, greedy NMS."""

from __future__ import annotations

from dataclasses import dataclass

MIN_SCORE = 0.6
MIN_AREA = 0.015  # fraction of the image
NMS_IOU = 0.6


@dataclass(frozen=True)
class Region:
    box: tuple[float, float, float, float]  # normalized x, y, w, h, top-left origin
    score: float

    @property
    def area(self) -> float:
        return self.box[2] * self.box[3]


def iou(a: Region, b: Region) -> float:
    ax, ay, aw, ah = a.box
    bx, by, bw, bh = b.box
    ix = max(0.0, min(ax + aw, bx + bw) - max(ax, bx))
    iy = max(0.0, min(ay + ah, by + bh) - max(ay, by))
    inter = ix * iy
    union = a.area + b.area - inter
    return inter / union if union > 0 else 0.0


def filter_regions(regions: list[Region]) -> tuple[list[Region], list[dict]]:
    """Return kept regions and a decision log for the trace."""
    decisions: list[dict] = []
    kept: list[Region] = []
    for r in sorted(regions, key=lambda r: r.score, reverse=True):
        entry = {"box": [round(v, 4) for v in r.box], "score": round(r.score, 4)}
        if r.score < MIN_SCORE:
            decisions.append({**entry, "kept": False, "reason": "low_score"})
        elif r.area < MIN_AREA:
            decisions.append({**entry, "kept": False, "reason": "small_area"})
        elif any(iou(r, k) >= NMS_IOU for k in kept):
            decisions.append({**entry, "kept": False, "reason": "duplicate"})
        else:
            kept.append(r)
            decisions.append({**entry, "kept": True, "reason": None})
    return kept, decisions
