"""FastAPI backend for the birr cash assistant. Contract: docs/api.md.

Run: uv run uvicorn birr.api:app --reload
"""

from __future__ import annotations

import asyncio
import time
from contextlib import asynccontextmanager
from typing import Annotated

import httpx
from fastapi import FastAPI, File, Form, Request, UploadFile
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from birr.agent.decide import decide
from birr.agent.trace import new_trace_id, write_trace
from birr.config import get_settings
from birr.image import BadImage, prepare_jpeg
from birr.read import muse
from birr.segment import sam
from birr.segment.filter import filter_regions
from birr.voice import speech as say


@asynccontextmanager
async def lifespan(app: FastAPI):
    app.state.http = httpx.AsyncClient(timeout=get_settings().scan_timeout_s)
    yield
    await app.state.http.aclose()


app = FastAPI(title="Birr backend", lifespan=lifespan)


def _error(status: int, error: str, text: str, lang: str = "en", trace_id: str | None = None):
    spoken, todo = say.speech(text, lang)
    body = {"error": error, "speech": spoken, "trace_id": trace_id}
    if todo:
        body["speech_todo"] = todo
    return JSONResponse(status_code=status, content=body)


@app.exception_handler(RequestValidationError)
async def _validation_error(request: Request, exc: RequestValidationError):
    return _error(400, "bad_request", say.BAD_REQUEST)


async def _timed(coro) -> tuple[object, int]:
    start = time.perf_counter()
    result = await coro
    return result, int((time.perf_counter() - start) * 1000)


@app.post("/scan")
async def scan(
    image: Annotated[UploadFile, File()],
    intent: Annotated[str, Form()],
    lang: Annotated[str, Form()] = "en",
    paid: Annotated[int | None, Form()] = None,
    price: Annotated[int | None, Form()] = None,
    attempt: Annotated[int, Form()] = 1,
    max_attempts: Annotated[int, Form()] = 3,
):
    settings = get_settings()
    trace_id = new_trace_id()
    started = time.perf_counter()
    lang = lang if lang in ("en", "am", "om") else "en"
    trace: dict = {
        "endpoint": "/scan",
        "inputs": {"intent": intent, "lang": lang, "paid": paid, "price": price,
                   "attempt": attempt, "max_attempts": max_attempts},
    }  # fmt: skip

    def fail(status: int, error: str, text: str, detail: str):
        trace.update(outcome=error, detail=detail, speech_en=text)
        write_trace(settings.trace_dir, trace_id, trace)
        return _error(status, error, text, lang, trace_id)

    if intent not in ("count", "change"):
        return fail(400, "bad_request", say.BAD_REQUEST, "intent must be count or change")
    if intent == "change" and (paid is None or price is None):
        return fail(400, "bad_request", say.NEED_PRICE, "change needs paid and price")
    raw = await image.read()
    if len(raw) > settings.max_upload_bytes:
        return fail(400, "bad_request", say.BAD_REQUEST, "image too large")
    try:
        jpeg, width, height = prepare_jpeg(raw, settings.image_max_px)
    except BadImage as exc:
        return fail(400, "bad_request", say.BAD_REQUEST, str(exc))
    trace["image"] = {"width": width, "height": height}

    client: httpx.AsyncClient = app.state.http

    async def run_sam():
        try:
            return await _timed(sam.segment(client, jpeg, width, height, settings))
        except (TimeoutError, sam.SamError) as exc:
            trace["sam_error"] = str(exc) or type(exc).__name__
            return None, None

    try:
        (labels, muse_ms), (raw_regions, sam_ms) = await asyncio.wait_for(
            asyncio.gather(_timed(muse.read_notes(client, jpeg, settings)), run_sam()),
            timeout=settings.scan_timeout_s,
        )
    except TimeoutError:
        return fail(504, "upstream_timeout", say.TOO_SLOW, "scan exceeded timeout")
    except muse.MuseError as exc:
        return fail(502, "upstream_error", say.TRY_AGAIN, str(exc))

    regions = None
    if raw_regions is not None:
        regions, decisions = filter_regions(raw_regions)
        trace["sam"] = {"raw_count": len(raw_regions), "kept": len(regions), "filter": decisions}
    trace["muse"] = {"labels": labels}

    result = decide(
        labels,
        regions,
        intent=intent,
        paid=paid,
        price=price,
        attempt=attempt,
        max_attempts=max_attempts,
        muse_only_totals=settings.muse_only_totals,
    )
    text = result.pop("speech_en")
    spoken, todo = say.speech(text, lang)
    timing = {"muse": muse_ms, "sam": sam_ms, "total": int((time.perf_counter() - started) * 1000)}
    body = {**result, "speech": spoken, "trace_id": trace_id, "timing_ms": timing}
    if todo:
        body["speech_todo"] = todo
    trace.update(
        sam_available=regions is not None,
        muse_only_totals=settings.muse_only_totals,
        outcome=result["outcome"],
        total=result["total"],
        change=result["change"],
        hint=result["hint"],
        speech_en=text,
        timing_ms=timing,
    )
    write_trace(settings.trace_dir, trace_id, trace)
    return body


@app.post("/intent", status_code=501)
async def intent_stub(lang: Annotated[str, Form()] = "en"):
    """Not implemented here on purpose.

    Per the team plan, voice and intent go through Gemini (speech-to-text, intent extraction,
    translation and TTS), pending Claude's final decision. Muse is not used for audio.
    """
    settings = get_settings()
    lang = lang if lang in ("en", "am", "om") else "en"
    trace_id = new_trace_id()
    write_trace(settings.trace_dir, trace_id, {"endpoint": "/intent", "outcome": "not_implemented"})
    return _error(501, "not_implemented", say.VOICE_TODO, lang, trace_id)


@app.get("/health")
async def health():
    return {"ok": True}
