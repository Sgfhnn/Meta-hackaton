"""Image intake: decode, drop metadata, resize, re-encode as JPEG."""

from __future__ import annotations

import io

from PIL import Image, UnidentifiedImageError


class BadImage(ValueError):
    pass


def prepare_jpeg(data: bytes, max_px: int) -> tuple[bytes, int, int]:
    """Return (jpeg_bytes, width, height) with the longest side at most max_px."""
    try:
        img = Image.open(io.BytesIO(data))
        if img.format != "JPEG":
            raise BadImage("image must be JPEG")
        img = img.convert("RGB")
    except (UnidentifiedImageError, OSError) as exc:
        raise BadImage("image could not be decoded") from exc
    img.thumbnail((max_px, max_px))
    out = io.BytesIO()
    img.save(out, format="JPEG", quality=90)  # re-encoding drops EXIF
    return out.getvalue(), img.width, img.height
