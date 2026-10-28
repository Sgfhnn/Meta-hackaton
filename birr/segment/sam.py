"""Roboflow serverless SAM 3 client: one text prompt, polygons back, boxes out."""

from __future__ import annotations

import base64

import httpx

from birr.config import Settings
from birr.segment.filter import Region


class SamError(RuntimeError):
    pass


def regions_from_response(data: dict, width: int, height: int) -> list[Region]:
    """Turn concept_segment polygons into normalized [x, y, w, h] boxes."""
    regions: list[Region] = []
    for prompt_result in data.get("prompt_results", []):
        for pred in prompt_result.get("predictions", []):
            points = [p for poly in pred.get("masks", []) for p in poly]
            if not points:
                continue
            xs = [float(p[0]) for p in points]
            ys = [float(p[1]) for p in points]
            x0, y0 = max(min(xs), 0.0), max(min(ys), 0.0)
            x1, y1 = min(max(xs), float(width)), min(max(ys), float(height))
            box = (x0 / width, y0 / height, (x1 - x0) / width, (y1 - y0) / height)
            regions.append(Region(box=box, score=float(pred.get("confidence", 0.0))))
    return regions


async def segment(
    client: httpx.AsyncClient, jpeg: bytes, width: int, height: int, settings: Settings
) -> list[Region]:
    body = {
        "image": {"type": "base64", "value": base64.b64encode(jpeg).decode()},
        "prompts": [{"type": "text", "text": "banknote"}],
        "output_prob_thresh": 0.5,
        "format": "polygon",
    }
    headers = {"Authorization": f"Bearer {settings.sam_key}"}
    try:
        resp = await client.post(
            settings.sam_url, json=body, headers=headers, timeout=settings.sam_timeout_s
        )
        resp.raise_for_status()
        return regions_from_response(resp.json(), width, height)
    except (httpx.HTTPError, ValueError, TypeError) as exc:
        raise SamError(f"SAM call failed: {type(exc).__name__}") from exc
