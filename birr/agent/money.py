"""Totals and change, computed in code only. The model never states a total."""

from __future__ import annotations

from birr.config import VALID_DENOMINATIONS


def to_denomination(label: str) -> int | None:
    """Map a Muse label to a valid denomination, or None for not_birr/unclear/anything else."""
    text = str(label).strip().lower().replace("birr", "").strip()
    try:
        value = int(float(text))
    except ValueError:
        return None
    return value if value in VALID_DENOMINATIONS else None


def total(denominations: list[int]) -> int:
    return sum(denominations)


def change(paid: int, price: int, counted: int) -> dict:
    expected = paid - price
    return {"expected": expected, "counted": counted, "difference": counted - expected}
