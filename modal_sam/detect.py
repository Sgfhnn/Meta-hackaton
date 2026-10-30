"""Request checks and box conversion for the Modal SAM endpoint. Pure Python, no GPU code.

The endpoint answers {"detections": [{"box": [x0, y0, x1, y1], "score": s}, ...]} with boxes in
pixels of the photo it received, best score first. birr/segment/sam.py reads that shape.
"""

from __future__ import annotations

import base64
import binascii

MODELS = ("sam3.1", "sam3")
MAX_IMAGE_BYTES = 10 * 1024 * 1024
MAX_PROMPT_CHARS = 60


class BadRequest(ValueError):
    pass


def parse_request(body: dict) -> tuple[bytes, str, float]:
    """Return (image bytes, prompt, threshold) from {"image": base64, "prompt", "threshold"}."""
    if not isinstance(body, dict):
        raise BadRequest("body must be a JSON object")
    data = body.get("image")
    if not isinstance(data, str) or not data:
        raise BadRequest("image must be a base64 string")
    try:
        image = base64.b64decode(data, validate=True)
    except (binascii.Error, ValueError) as exc:
        raise BadRequest("image is not valid base64") from exc
    if len(image) > MAX_IMAGE_BYTES:
        raise BadRequest("image too large")
    prompt = body.get("prompt", "banknote")
    if not isinstance(prompt, str) or not prompt.strip() or len(prompt) > MAX_PROMPT_CHARS:
        raise BadRequest("prompt must be a short text")
    threshold = body.get("threshold", 0.5)
    if isinstance(threshold, bool) or not isinstance(threshold, int | float):
        raise BadRequest("threshold must be a number from 0 to 1")
    if not 0 <= threshold <= 1:
        raise BadRequest("threshold must be a number from 0 to 1")
    return image, prompt.strip(), float(threshold)


def _keep(boxes_xyxy, scores, width: int, height: int, threshold: float) -> list[dict]:
    found = []
    for (x0, y0, x1, y1), score in zip(boxes_xyxy, scores, strict=True):
        x0, y0 = max(float(x0), 0.0), max(float(y0), 0.0)
        x1, y1 = min(float(x1), float(width)), min(float(y1), float(height))
        if x1 <= x0 or y1 <= y0 or float(score) < threshold:
            continue
        box = [round(x0, 1), round(y0, 1), round(x1, 1), round(y1, 1)]
        found.append({"box": box, "score": round(float(score), 4)})
    return sorted(found, key=lambda d: d["score"], reverse=True)


def from_xyxy(boxes, scores, width: int, height: int, threshold: float) -> list[dict]:
    """SAM 3 image model (Sam3Processor): boxes are [x0, y0, x1, y1] in pixels."""
    return _keep(boxes, scores, width, height, threshold)


def from_xywh_normalized(boxes, scores, width: int, height: int, threshold: float) -> list[dict]:
    """SAM 3.1 predictor (out_boxes_xywh): boxes are [x, y, w, h] as fractions of the photo."""
    xyxy = [
        (x * width, y * height, (x + w) * width, (y + h) * height)
        for x, y, w, h in ((float(v) for v in b) for b in boxes)
    ]
    return _keep(xyxy, scores, width, height, threshold)
