"""Build the Birr logo SVGs: a yellow banknote with ብር on it, sound waves coming off it, on green.

Usage: python -I make_logo.py <font.ttf> <out_dir>
The glyphs are converted to paths, so the SVGs need no font.
"""

import math
import sys
from pathlib import Path

from fontTools.pens.boundsPen import BoundsPen
from fontTools.pens.svgPathPen import SVGPathPen
from fontTools.pens.transformPen import TransformPen
from fontTools.ttLib import TTFont

GREEN = "#0B3B2D"
YELLOW = "#FFD23F"
WHITE = "#FFFFFF"

# Mark geometry on a 1024 canvas, before scaling. The group is centered later.
STYLE = "bubble"  # "bubble": the note is a speech bubble; "waves": sound waves beside the note
DY = 16  # the tail hangs below the bubble, so nudge the whole mark down to look centered
NOTE_W, NOTE_H, NOTE_R = 520, 340, 46
BORDER_INSET, BORDER_W, BORDER_R = 26, 12, 26
GAP = 34  # note edge to wave center
WAVES = (78, 150)  # radii
WAVE_W = 40
WAVE_DEG = 46  # half-angle of each arc
TEXT_H = 196  # glyph height inside the note


def glyph_paths(font_path: str, text: str, height: float):
    """Return (path d, width, height) for `text`, y-down, top-left at (0, 0)."""
    font = TTFont(font_path)
    cmap, glyphs = font.getBestCmap(), font.getGlyphSet()
    hmtx = font["hmtx"]
    # Measure ink bounds of the whole run in font units.
    x = 0
    runs = []
    for ch in text:
        name = cmap[ord(ch)]
        runs.append((name, x))
        x += hmtx[name][0]
    bounds = BoundsPen(glyphs)
    for name, dx in runs:
        glyphs[name].draw(TransformPen(bounds, (1, 0, 0, 1, dx, 0)))
    x0, y0, x1, y1 = bounds.bounds
    scale = height / (y1 - y0)
    pen = SVGPathPen(glyphs)
    for name, dx in runs:
        # font units (y up) -> svg (y down), ink box moved to the origin
        t = (scale, 0, 0, -scale, (dx - x0) * scale, y1 * scale)
        glyphs[name].draw(TransformPen(pen, t))
    return pen.getCommands(), (x1 - x0) * scale, height


def arc(cx, cy, r, deg):
    a = math.radians(deg)
    x0, y0 = cx + r * math.cos(-a), cy + r * math.sin(-a)
    x1, y1 = cx + r * math.cos(a), cy + r * math.sin(a)
    return f"M{x0:.1f} {y0:.1f} A{r} {r} 0 0 1 {x1:.1f} {y1:.1f}"


def bubble(font_path: str, note_fill: str, ink: str, knockout: bool = False):
    """The note as a speech bubble with ብር on it, centered on (0, 0)."""
    w, h, r = 640, 400, 64
    tail_h = 120
    d_text, tw, th = glyph_paths(font_path, "ብር", 236)
    left, top = -w / 2, -(h + tail_h) / 2
    bottom = top + h
    note = (
        f'<rect x="{left:.1f}" y="{top:.1f}" width="{w}" height="{h}" rx="{r}" '
        f'fill="{note_fill}"/>'
        # tail: leaves the bottom edge near the left corner and points down-left
        f'<path d="M{left + 96:.1f} {bottom - 4:.1f} L{left + 236:.1f} {bottom - 4:.1f} '
        f'L{left + 70:.1f} {bottom + tail_h:.1f} Z" fill="{note_fill}" '
        f'stroke="{note_fill}" stroke-width="18" stroke-linejoin="round"/>'
    )
    inset, bw = 30, 13
    border = (
        f'<rect x="{left + inset:.1f}" y="{top + inset:.1f}" width="{w - 2 * inset}" '
        f'height="{h - 2 * inset}" rx="{r - inset + 6}" fill="none" stroke="{ink}" '
        f'stroke-width="{bw}"/>'
    )
    tx, ty = left + (w - tw) / 2, top + (h - th) / 2
    text = f'<path transform="translate({tx:.1f} {ty:.1f})" d="{d_text}" fill="{ink}"/>'
    if knockout:
        mask = (
            '<mask id="cut" maskUnits="userSpaceOnUse" x="-512" y="-512" width="1024" '
            'height="1024"><rect x="-512" y="-512" width="1024" height="1024" fill="#fff"/>'
            + border.replace(f'stroke="{ink}"', 'stroke="#000"')
            + text.replace(f'fill="{ink}"', 'fill="#000"')
            + "</mask>"
        )
        return mask + f'<g mask="url(#cut)">{note}</g>'
    return note + border + text


def mark(font_path: str, note_fill: str, ink: str, waves: str, knockout: bool = False):
    """The mark as SVG elements, centered on (0, 0) in a 1024 design space.

    knockout: draw the text and border as holes in the note (for one-colour icons)."""
    if STYLE == "bubble":
        return bubble(font_path, note_fill, ink, knockout)
    d_text, tw, th = glyph_paths(font_path, "ብር", TEXT_H)
    wave_out = WAVES[-1] + WAVE_W / 2
    total_w = NOTE_W + GAP + wave_out
    left = -total_w / 2
    top = -NOTE_H / 2
    cx, cy = left + NOTE_W + GAP, 0
    tx, ty = left + (NOTE_W - tw) / 2, -th / 2
    note = (
        f'<rect x="{left:.1f}" y="{top:.1f}" width="{NOTE_W}" height="{NOTE_H}" '
        f'rx="{NOTE_R}" fill="{note_fill}"/>'
    )
    bx, by = left + BORDER_INSET, top + BORDER_INSET
    bw, bh = NOTE_W - 2 * BORDER_INSET, NOTE_H - 2 * BORDER_INSET
    border = (
        f'<rect x="{bx:.1f}" y="{by:.1f}" width="{bw}" height="{bh}" rx="{BORDER_R}" '
        f'fill="none" stroke="{ink}" stroke-width="{BORDER_W}"/>'
    )
    text = f'<path transform="translate({tx:.1f} {ty:.1f})" d="{d_text}" fill="{ink}"/>'
    arcs = "".join(
        f'<path d="{arc(cx, cy, r, WAVE_DEG)}" fill="none" stroke="{waves}" '
        f'stroke-width="{WAVE_W}" stroke-linecap="round"/>'
        for r in WAVES
    )
    if knockout:
        mask = (
            '<mask id="cut" maskUnits="userSpaceOnUse" x="-512" y="-512" width="1024" '
            'height="1024"><rect x="-512" y="-512" width="1024" height="1024" fill="#fff"/>'
            + border.replace(f'stroke="{ink}"', 'stroke="#000"')
            + text.replace(f'fill="{ink}"', 'fill="#000"')
            + "</mask>"
        )
        return mask + f'<g mask="url(#cut)">{note}</g>' + arcs
    return note + border + text + arcs


def svg(body: str, size: int = 1024) -> str:
    return (
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{size}" height="{size}" '
        f'viewBox="0 0 1024 1024">{body}</svg>\n'
    )


def placed(inner: str, scale: float, dx: float = 0, dy: float = 0) -> str:
    return f'<g transform="translate({512 + dx} {512 + dy}) scale({scale})">{inner}</g>'


def main():
    global STYLE
    font, out = sys.argv[1], Path(sys.argv[2])
    if len(sys.argv) > 3:
        STYLE = sys.argv[3]
    out.mkdir(parents=True, exist_ok=True)
    colour = mark(font, YELLOW, GREEN, YELLOW)
    files = {
        # iOS / universal icon: full-bleed green, the OS rounds the corners
        "icon.svg": svg(f'<rect width="1024" height="1024" fill="{GREEN}"/>' + placed(colour, 1.0, dy=DY)),
        # README / web: rounded square
        "logo.svg": svg(
            f'<rect width="1024" height="1024" rx="230" fill="{GREEN}"/>' + placed(colour, 1.0, dy=DY)
        ),
        # Android adaptive icon: the mark inside the safe circle, on its own layer
        "android-icon-foreground.svg": svg(placed(colour, 0.74, dy=DY * 0.74)),
        "android-icon-background.svg": svg(f'<rect width="1024" height="1024" fill="{GREEN}"/>'),
        # Android 13 themed icon: one colour, text cut out
        "android-icon-monochrome.svg": svg(
            placed(mark(font, WHITE, WHITE, WHITE, True), 0.74, dy=DY * 0.74)
        ),
        # Splash: the mark alone on transparent; app.json sets the green background
        "splash-icon.svg": svg(placed(colour, 1.0, dy=DY)),
    }
    for name, text in files.items():
        (out / name).write_text(text, encoding="utf-8")
        print("wrote", out / name)


if __name__ == "__main__":
    main()
