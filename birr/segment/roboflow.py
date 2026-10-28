"""Roboflow hosted SAM 3 client (live app). The API key never leaves the server.

The request and response shapes follow @hark's working dev call: text prompt
"banknote", output_prob_thresh 0.5, polygon format. Masks come back as
polygons in pixels; we convert each to a normalized bounding box.
"""

from __future__ import annotations

import base64
import os

import httpx

from birr.agent.decide import Region

URL = "https://serverless.roboflow.com/sam3/concept_segment"
PROMPT = "banknote"


async def segment(client: httpx.AsyncClient, jpeg: bytes, width: int, height: int) -> list[Region]:
    payload = {
        "image": {"type": "base64", "value": base64.b64encode(jpeg).decode()},
        "prompts": [{"type": "text", "text": PROMPT}],
        "format": "polygon",
        "output_prob_thresh": 0.5,
    }
    headers = {"Authorization": f"Bearer {os.environ['ROBOFLOW_API_KEY']}"}
    resp = await client.post(URL, json=payload, headers=headers)
    resp.raise_for_status()
    return parse(resp.json(), width, height)


def parse(body: dict, width: int, height: int) -> list[Region]:
    regions = []
    for result in body.get("prompt_results", []):
        for pred in result.get("predictions", []):
            for polygon in pred.get("masks", []):
                if len(polygon) < 3:
                    continue
                xs = [p[0] for p in polygon]
                ys = [p[1] for p in polygon]
                box = (
                    min(xs) / width,
                    min(ys) / height,
                    (max(xs) - min(xs)) / width,
                    (max(ys) - min(ys)) / height,
                )
                regions.append(Region(box=box, confidence=float(pred.get("confidence", 0.0))))
    return regions
