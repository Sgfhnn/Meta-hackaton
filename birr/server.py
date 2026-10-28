"""Backend for the Expo app: POST /scan per docs/api.md.

Roboflow SAM 3 and Muse Spark run in parallel. Their results are combined in
code by birr.agent.decide. API keys stay on this server.

Run: uv run uvicorn birr.server:app --reload
"""

from __future__ import annotations

import asyncio
import io
import json
import os
import time
import uuid
from pathlib import Path

import httpx
from fastapi import FastAPI, File, Form, UploadFile
from fastapi.responses import JSONResponse
from PIL import Image, ImageOps, UnidentifiedImageError

from birr.agent.decide import Decision, decide
from birr.read import muse
from birr.segment import roboflow
from birr.segment.filter import filter_regions

IMAGE_MAX_PX = int(os.environ.get("IMAGE_MAX_PX", "768"))
TIMEOUT_S = 20.0
TRACE_DIR = Path(os.environ.get("TRACE_DIR", "traces"))

app = FastAPI(title="Birr cash assistant")


def error(status: int, code: str, en: str) -> JSONResponse:
    return JSONResponse(status_code=status, content={"error": code, "speech": {"en": en}})


def prepare(raw: bytes) -> tuple[bytes, int, int]:
    """Fix orientation, shrink to IMAGE_MAX_PX, and re-encode without EXIF."""
    image = ImageOps.exif_transpose(Image.open(io.BytesIO(raw))).convert("RGB")
    image.thumbnail((IMAGE_MAX_PX, IMAGE_MAX_PX))
    out = io.BytesIO()
    image.save(out, format="JPEG", quality=90)
    return out.getvalue(), image.width, image.height


async def timed(coro, timings: dict, key: str):
    start = time.perf_counter()
    try:
        return await coro
    finally:
        timings[key] = round((time.perf_counter() - start) * 1000)


@app.post("/scan")
async def scan(
    image: UploadFile = File(...),
    intent: str = Form("count"),
    lang: str = Form("en"),
    paid: int | None = Form(None),
    price: int | None = Form(None),
    attempt: int = Form(1),
    max_attempts: int = Form(3),
):
    if intent not in ("count", "change") or lang not in ("am", "om", "en"):
        return error(400, "bad_request", "Sorry, I didn't understand that request.")
    try:
        jpeg, width, height = prepare(await image.read())
    except UnidentifiedImageError:
        return error(400, "bad_request", "Sorry, I couldn't open that photo. Please try again.")

    trace_id = uuid.uuid4().hex
    timings: dict[str, int] = {}
    start = time.perf_counter()
    async with httpx.AsyncClient(timeout=TIMEOUT_S) as client:
        try:
            sam_result, notes = await asyncio.wait_for(
                asyncio.gather(
                    timed(roboflow.segment(client, jpeg, width, height), timings, "sam"),
                    timed(muse.read_notes(client, jpeg), timings, "muse"),
                    return_exceptions=True,
                ),
                timeout=TIMEOUT_S,
            )
        except TimeoutError:
            return error(504, "upstream_timeout", "Sorry, that took too long. Please try again.")
    timings["total"] = round((time.perf_counter() - start) * 1000)

    if isinstance(notes, BaseException):
        return error(502, "upstream_error", "Sorry, I couldn't check that. Please try again.")
    raw_regions = None if isinstance(sam_result, BaseException) else sam_result
    regions = None if raw_regions is None else filter_regions(raw_regions)

    decision = decide(regions, notes, intent, paid, price)
    if decision.outcome != "total" and attempt >= max_attempts:
        decision.reasons.append("max_attempts")

    body = {
        "outcome": decision.outcome,
        "total": decision.total,
        "change": decision.change,
        "notes": [
            {"denomination": n.denomination, "confidence": n.confidence, "status": n.status}
            for n in notes
        ],
        "hint": hint(decision),
        "speech": {"en": speech_en(decision, attempt >= max_attempts)},
        "trace_id": trace_id,
        "timing_ms": timings,
    }
    write_trace(trace_id, intent, lang, attempt, raw_regions, regions, decision, body)
    return body


def hint(decision: Decision) -> dict | None:
    """Basic hint from the target region's position. guide.py will replace this."""
    if decision.outcome != "guide" or decision.target is None:
        return None
    x, y, w, h = decision.target.box
    cx, cy = x + w / 2, y + h / 2
    depth = "near" if cy > 0.5 else "far"
    side = "left" if cx < 0.33 else "right" if cx > 0.66 else "center"
    return {"position": f"{depth} {side}", "action": "slide_out"}


def speech_en(decision: Decision, out_of_attempts: bool) -> str:
    if decision.outcome == "total":
        if decision.change is not None:
            diff = decision.change["difference"]
            if diff == 0:
                return f"Your change is correct: {decision.total} birr."
            if diff < 0:
                return f"You were given {decision.total} birr. You are short {-diff} birr."
            return f"You were given {decision.total} birr, {diff} birr more than expected."
        return f"You have {decision.total} birr."
    if out_of_attempts:
        return "Sorry, I can't count these notes. Please ask someone to help."
    if decision.outcome == "guide":
        pos = hint(decision)
        where = f" on the {pos['position']}" if pos else ""
        return f"I can't give a total yet. One note{where} is hidden. Slide it out and scan again."
    return "I can't give a total yet. Spread the notes out and scan again."


def write_trace(trace_id, intent, lang, attempt, raw_regions, regions, decision, body) -> None:
    TRACE_DIR.mkdir(exist_ok=True)
    trace = {
        "trace_id": trace_id,
        "intent": intent,
        "lang": lang,
        "attempt": attempt,
        "sam_raw_count": None if raw_regions is None else len(raw_regions),
        "sam_filtered_count": None if regions is None else len(regions),
        "reasons": decision.reasons,
        "response": body,
    }
    (TRACE_DIR / f"{trace_id}.json").write_text(json.dumps(trace, indent=2))
