"""FastAPI backend for the birr cash assistant. Contract: docs/api.md.

Run: uv run uvicorn birr.api:app --reload
"""

from __future__ import annotations

from contextlib import asynccontextmanager
from typing import Annotated

import httpx
from fastapi import FastAPI, File, Form, Request, UploadFile
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from birr import scan as scan_flow
from birr.agent.trace import new_trace_id, write_trace
from birr.config import get_settings
from birr.image import BadImage, prepare_jpeg
from birr.jobs import JobStore
from birr.scan import ScanRequest
from birr.voice import speech as say

POLL_AFTER_MS = 1500


@asynccontextmanager
async def lifespan(app: FastAPI):
    app.state.http = httpx.AsyncClient(timeout=get_settings().scan_deadline_s)
    app.state.jobs = JobStore()
    yield
    await app.state.jobs.close()
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


@app.post("/scan")
async def scan(
    image: Annotated[UploadFile, File()],
    intent: Annotated[str, Form()],
    lang: Annotated[str, Form()] = "en",
    paid: Annotated[int | None, Form()] = None,
    price: Annotated[int | None, Form()] = None,
    attempt: Annotated[int, Form()] = 1,
    max_attempts: Annotated[int, Form()] = 3,
    wait: Annotated[bool, Form()] = False,
):
    """Validate, then start a scan job. Returns 202 + job_id (or the result when wait=true)."""
    settings = get_settings()
    trace_id = new_trace_id()
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

    req = ScanRequest(intent, lang, paid, price, attempt, max_attempts)
    work = scan_flow.execute(app.state.http, jpeg, width, height, req, settings, trace_id, trace)
    crash, _ = say.speech(say.TRY_AGAIN, lang)
    crash_body = {"error": "upstream_error", "speech": crash, "trace_id": trace_id}
    job = app.state.jobs.start(trace_id, lang, work, crash_body, settings.job_ttl_s)
    if wait:
        await job.task
        return JSONResponse(status_code=job.http_status, content=job.body)
    return JSONResponse(
        status_code=202,
        content={
            "job_id": job.job_id,
            "status": "pending",
            "poll_url": f"/scan/{job.job_id}",
            "poll_after_ms": POLL_AFTER_MS,
            "trace_id": trace_id,
        },
    )


@app.get("/scan/{job_id}")
async def scan_status(job_id: str):
    job = app.state.jobs.get(job_id)
    if job is None:
        return _error(404, "not_found", say.TRY_AGAIN)
    content = {"job_id": job.job_id, "status": job.status, "elapsed_ms": job.elapsed_ms}
    if job.status == "pending":
        spoken, _ = say.speech(say.STILL_COUNTING, job.lang)
        content.update(result=None, poll_after_ms=POLL_AFTER_MS, speech=spoken)
    elif job.status == "done":
        content["result"] = job.body
    else:
        content.update(result=None, **job.body)
    return content


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
