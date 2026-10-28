"""Turn SAM regions and Muse note reads into a scan outcome.

Implements the core rules in docs/api.md: totals and change are computed here
in code, and a total is only returned when SAM's count agrees with Muse's.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal

DENOMINATIONS = frozenset({5, 10, 50, 100, 200})

Status = Literal["read", "partial", "unclear"]
Outcome = Literal["total", "guide", "rescan"]


@dataclass(frozen=True)
class Note:
    denomination: int | None
    confidence: float
    status: Status


@dataclass(frozen=True)
class Region:
    """A SAM region after filtering. Box is [x, y, w, h], normalized 0-1."""

    box: tuple[float, float, float, float]
    confidence: float


@dataclass
class Decision:
    outcome: Outcome
    total: int | None = None
    change: dict[str, int] | None = None
    target: Region | None = None
    reasons: list[str] = field(default_factory=list)


def decide(
    regions: list[Region] | None,
    notes: list[Note],
    intent: str = "count",
    paid: int | None = None,
    price: int | None = None,
) -> Decision:
    """Pick total, guide or rescan. `regions` is None when SAM was unavailable."""
    if regions is None:
        return Decision("rescan", reasons=["sam_unavailable"])
    if not notes and not regions:
        return Decision("rescan", reasons=["no_notes"])

    if any(n.status == "unclear" for n in notes):
        return Decision("rescan", reasons=["unclear_note"])
    if any(n.status == "read" and n.denomination not in DENOMINATIONS for n in notes):
        return Decision("rescan", reasons=["out_of_scope"])
    if any(n.status == "partial" for n in notes):
        return Decision("guide", target=_most_covered(regions), reasons=["partial_note"])

    if len(regions) > len(notes):
        return Decision("guide", target=_most_covered(regions), reasons=["sam_found_more"])
    if len(regions) < len(notes):
        return Decision("rescan", reasons=["sam_found_fewer"])

    total = sum(n.denomination for n in notes)  # type: ignore[misc]
    change = None
    if intent == "change" and paid is not None and price is not None:
        expected = paid - price
        change = {"expected": expected, "counted": total, "difference": total - expected}
    return Decision("total", total=total, change=change)


def _most_covered(regions: list[Region]) -> Region | None:
    """The region most likely to be a covered note: the smallest visible area."""
    if not regions:
        return None
    return min(regions, key=lambda r: r.box[2] * r.box[3])
