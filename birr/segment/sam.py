"""SAM clients: one text prompt in, normalized boxes out.

Two providers, picked by SAM_PROVIDER:
- roboflow: Roboflow's hosted SAM 3 (concept_segment, polygons back). The default.
- modal: our own SAM 3.1 endpoint on Modal (modal_sam/sam31_app.py), boxes back in pixels.
"""

from __future__ import annotations

import base64

import httpx

from birr.config import Settings
from birr.segment.filter import Region

PROVIDERS = ("roboflow", "modal", "off")


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


def regions_from_modal(data: dict, width: int, height: int) -> list[Region]:
    """Turn the Modal endpoint's pixel boxes ([x0, y0, x1, y1] on our image) into regions."""
    regions: list[Region] = []
    for det in data.get("detections", []):
        x0, y0, x1, y1 = (float(v) for v in det["box"])
        x0, y0 = max(x0, 0.0), max(y0, 0.0)
        x1, y1 = min(x1, float(width)), min(y1, float(height))
        if x1 <= x0 or y1 <= y0:
            continue
        box = (x0 / width, y0 / height, (x1 - x0) / width, (y1 - y0) / height)
        regions.append(Region(box=box, score=float(det.get("score", 0.0))))
    return regions


async def _segment_roboflow(client, jpeg, width, height, settings: Settings) -> list[Region]:
    body = {
        "image": {"type": "base64", "value": base64.b64encode(jpeg).decode()},
        "prompts": [{"type": "text", "text": settings.sam_prompt}],
        "output_prob_thresh": 0.5,
        "format": "polygon",
    }
    headers = {"Authorization": f"Bearer {settings.sam_key}"}
    resp = await client.post(
        settings.sam_url, json=body, headers=headers, timeout=settings.sam_timeout_s
    )
    resp.raise_for_status()
    return regions_from_response(resp.json(), width, height)


async def _segment_modal(client, jpeg, width, height, settings: Settings) -> list[Region]:
    if not settings.sam_modal_url:
        raise SamError("SAM_PROVIDER=modal but SAM_MODAL_URL is not set")
    body = {
        "image": base64.b64encode(jpeg).decode(),
        "prompt": settings.sam_prompt,
        "threshold": 0.5,
    }
    headers = {}
    if settings.sam_modal_key and settings.sam_modal_secret:
        headers = {"Modal-Key": settings.sam_modal_key, "Modal-Secret": settings.sam_modal_secret}
    resp = await client.post(
        settings.sam_modal_url, json=body, headers=headers, timeout=settings.sam_modal_timeout_s
    )
    resp.raise_for_status()
    return regions_from_modal(resp.json(), width, height)


async def segment(
    client: httpx.AsyncClient, jpeg: bytes, width: int, height: int, settings: Settings
) -> list[Region]:
    provider = settings.sam_provider
    if provider not in ("roboflow", "modal"):
        raise SamError(f"SAM provider {provider!r} cannot segment")
    run = _segment_modal if provider == "modal" else _segment_roboflow
    try:
        return await run(client, jpeg, width, height, settings)
    except (httpx.HTTPError, ValueError, TypeError, KeyError) as exc:
        raise SamError(f"SAM call failed ({provider}): {type(exc).__name__}") from exc
