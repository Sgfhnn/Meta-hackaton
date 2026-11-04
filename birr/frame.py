"""Fast framing check for live camera guidance (docs/api.md section 7). No model, no network.

The app sends a small, low-quality JPEG about once a second while the camera is open. This module
answers in a few milliseconds whether the picture is good enough to count, and if not, the single
most useful thing to fix: light, glare, blur, nothing in view, notes too far, or notes cut off at
an edge. Only Pillow is used (no OpenCV, no numpy), on a 320-pixel copy of the frame.

These are rules on simple image statistics, so they are hints, not judgements: a frame they call
OK can still be unreadable (Muse decides that on the full photo), and they lean towards OK, because
a hint that never goes away is worse for a blind user than one photo too many. Thresholds were
tuned on the team's private dev and locked photos plus darkened, blurred, shrunk and cropped copies
of them (the confusion table is in the PR); every locked photo comes out OK.
"""

from __future__ import annotations

import io
from dataclasses import dataclass

from PIL import Image, ImageFilter, ImageOps, ImageStat

SIDE = 320  # pixels on the long side of the copy we measure
GRID = 8  # the frame is cut into GRID x GRID cells for the "where are the notes" map
_LAPLACIAN = ImageFilter.Kernel((3, 3), [0, 1, 0, 1, -4, 1, 0, 1, 0], scale=1, offset=128)

# Thresholds (tuned in the PR; see the module docstring).
DARK_P90 = 60  # 90% of pixels darker than this: too dark to read
DARK_MEAN = 38
BRIGHT_MEAN = 232  # the whole frame washed out (a white cloth is about 215)
GLARE_SHARE = 0.22  # this share of pixels blown out (>= 250)
BLUR_VAR = 240.0  # variance of the Laplacian in the busy cells below this: blurry
SHARP_CELLS = 4  # with no busy cell, the sharpest quarter of the cells is measured
EDGE_LEVEL = 24  # edge strength that counts as detail
CELL_DETAIL = 0.10  # a cell with this share of detail pixels has something printed in it
EMPTY_DETAIL = 0.035  # whole-frame detail below this (and flat colour): nothing in view
EMPTY_STD = 22.0
CUT_FLAT = 0.45  # cut_off needs this share of the frame to be plain table
CUT_BORDER = 5  # ... and this many busy cells along the edge the notes run off
FAR_AREA = 0.27  # notes' bounding box smaller than this share of the frame: too far

STATUSES = ("ok", "dark", "bright", "blurry", "no_notes", "far", "cut_off")


class BadFrame(ValueError):
    pass


@dataclass
class Check:
    status: str
    side: str | None = None  # for cut_off: "left", "right", "top" or "bottom" of the frame
    stats: dict | None = None

    @property
    def ready(self) -> bool:
        """Good enough to take the real photo now."""
        return self.status == "ok"


def _load(raw: bytes) -> Image.Image:
    try:
        im = Image.open(io.BytesIO(raw))
        im = ImageOps.exif_transpose(im).convert("RGB")
    except Exception as exc:  # noqa: BLE001 - Pillow raises many kinds for a broken file
        raise BadFrame("not an image") from exc
    im.thumbnail((SIDE, SIDE))
    return im


def _cells(gray: Image.Image) -> tuple[list[list[float]], list[float]]:
    """Share of detail (edge) pixels in each grid cell, and each cell's Laplacian variance."""
    edges = gray.filter(ImageFilter.FIND_EDGES).point(lambda v: 255 if v > EDGE_LEVEL else 0)
    lap = gray.filter(_LAPLACIAN)
    w, h = edges.size
    out, sharp = [], []
    for r in range(GRID):
        row = []
        for c in range(GRID):
            box = (c * w // GRID, r * h // GRID, (c + 1) * w // GRID, (r + 1) * h // GRID)
            row.append(ImageStat.Stat(edges.crop(box)).mean[0] / 255)
            sharp.append(ImageStat.Stat(lap.crop(box)).var[0])
        out.append(row)
    return out, sharp


def measure(im: Image.Image) -> dict:
    gray = im.convert("L")
    stat = ImageStat.Stat(gray)
    hist = gray.histogram()
    n = sum(hist)
    running, p90 = 0, 255
    for value, count in enumerate(hist):
        running += count
        if running >= 0.9 * n:
            p90 = value
            break
    cells, sharp = _cells(gray)
    busy = [v for v, d in zip(sharp, (d for row in cells for d in row), strict=True)
            if d >= CELL_DETAIL]  # fmt: skip
    top = busy or sorted(sharp, reverse=True)[: len(sharp) // SHARP_CELLS]
    return {
        "mean": stat.mean[0],
        "std": stat.stddev[0],
        "p90": p90,
        "glare": sum(hist[250:]) / n,
        "sharp": sum(top) / len(top),
        "detail": sum(map(sum, cells)) / GRID**2,
        "cells": cells,
    }


def _cut_side(full: list[list[bool]]) -> str | None:
    """The edge the notes run off: busy cells all along one border while the opposite border is
    empty. Hand-held photos often fill the frame, which is fine, so both conditions are needed."""
    rows = [sum(r) for r in full]
    cols = [sum(full[r][c] for r in range(GRID)) for c in range(GRID)]
    sides = {
        "left": (cols[0], cols[-1]),
        "right": (cols[-1], cols[0]),
        "top": (rows[0], rows[-1]),
        "bottom": (rows[-1], rows[0]),
    }
    flat = sum(not v for row in full for v in row) / GRID**2
    if flat < CUT_FLAT:  # notes, a hand or grass fill the frame: nothing tells us what is cut
        return None
    for side, (here, opposite) in sides.items():
        if here >= CUT_BORDER and opposite == 0:
            return side
    return None


def classify(m: dict) -> Check:
    stats = {k: round(v, 3) for k, v in m.items() if k != "cells"}
    if m["p90"] < DARK_P90 or m["mean"] < DARK_MEAN:
        return Check("dark", stats=stats)
    if m["mean"] > BRIGHT_MEAN or m["glare"] > GLARE_SHARE:
        return Check("bright", stats=stats)
    full = [[v >= CELL_DETAIL for v in row] for row in m["cells"]]
    hit = [(r, c) for r in range(GRID) for c in range(GRID) if full[r][c]]
    if not hit:  # no detail anywhere: an empty table, or light and dark areas out of focus
        flat = m["detail"] < EMPTY_DETAIL and m["std"] < EMPTY_STD
        return Check("no_notes" if flat else "blurry", stats=stats)
    if m["sharp"] < BLUR_VAR:
        return Check("blurry", stats=stats)
    rs, cs = [r for r, _ in hit], [c for _, c in hit]
    area = (max(rs) - min(rs) + 1) * (max(cs) - min(cs) + 1) / GRID**2
    stats["area"] = round(area, 3)
    if area < FAR_AREA:
        return Check("far", stats=stats)
    side = _cut_side(full)
    if side:
        return Check("cut_off", side=side, stats=stats)
    return Check("ok", stats=stats)


def check(raw: bytes) -> Check:
    """A JPEG (or PNG) frame -> what to tell the user. Raises BadFrame for a file that isn't one."""
    return classify(measure(_load(raw)))
