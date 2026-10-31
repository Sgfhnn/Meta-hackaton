"""FastAPI backend for the birr cash assistant. Contract: docs/api.md.

Run: uv run uvicorn birr.api:app --reload
"""

from __future__ import annotations

import asyncio
import logging
import os
import re
import time
from contextlib import asynccontextmanager
from typing import Annotated

import httpx
from fastapi import FastAPI, File, Form, Request, UploadFile
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, Response

from birr import scan as scan_flow
from birr.agent.trace import new_trace_id, write_trace
from birr.config import get_settings
from birr.image import BadImage, prepare_jpeg
from birr.jobs import JobStore
from birr.ratelimit import RateLimiter, client_key
from birr.read import muse
from birr.scan import ScanRequest
from birr.voice import asr, gemini, mms, understand
from birr.voice import speech as say
from birr.voice.service import LANGS, TRANSLATED, Voice

POLL_AFTER_MS = 1500
_CLIP_ID = re.compile(r"[0-9a-f]{32}")
log = logging.getLogger(__name__)


async def _warm(voice: Voice) -> None:
    """Load the MMS voices and make the fixed phrases' clips, so prompts and errors need no wait."""
    try:
        await voice.warm(say.FIXED + list(say.APP_PHRASES.values()))
    except Exception:  # noqa: BLE001 - a failed warm-up only costs speed: clips are made on demand
        log.exception("voice warm-up failed")


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = get_settings()
    app.state.http = httpx.AsyncClient(timeout=settings.scan_deadline_s)
    app.state.jobs = JobStore()
    app.state.limiter = RateLimiter()
    app.state.voice = Voice(settings)
    warm = asyncio.create_task(_warm(app.state.voice))
    yield
    warm.cancel()
    await asyncio.gather(warm, return_exceptions=True)
    await app.state.jobs.close()
    await app.state.http.aclose()


app = FastAPI(title="Birr backend", lifespan=lifespan)

if os.environ.get("LAB_TOKEN"):
    from birr.lab import router as lab_router

    app.include_router(lab_router)

_origins = [o.strip() for o in os.environ.get("CORS_ORIGINS", "").split(",") if o.strip()]
if _origins:
    app.add_middleware(
        CORSMiddleware,
        allow_origins=_origins,
        allow_methods=["GET", "POST"],
        allow_headers=["*"],
        allow_credentials=False,
    )


def _speech(text: str, lang: str) -> dict:
    """speech (+ speech_audio / speech_todo) from cached translations. No network call."""
    voice = getattr(app.state, "voice", None)
    if voice is not None:
        return voice.speech(text, lang)
    spoken, todo = say.speech(text, lang)
    return {"speech": spoken, **({"speech_todo": todo} if todo else {})}


def _error(status: int, error: str, text: str, lang: str = "en", trace_id: str | None = None):
    body = {"error": error, **_speech(text, lang), "trace_id": trace_id}
    return JSONResponse(status_code=status, content=body)


def hears(settings) -> str:
    """Which engine hears voice questions: omnilingual (ASR_URL set), gemini (key set) or off."""
    if settings.asr_url:
        return "omnilingual"
    return "gemini" if settings.gemini_key else "off"


async def _in_language(work, lang: str) -> tuple[int, dict]:
    """Finish a scan job, then put its answer into the user's language. A translation problem
    never costs the answer: it then stays in English."""
    status, body = await work
    try:
        return status, await app.state.voice.localize_body(body, lang)
    except Exception:  # noqa: BLE001
        log.exception("could not localize a scan answer")
        return status, body


@app.exception_handler(RequestValidationError)
async def _validation_error(request: Request, exc: RequestValidationError):
    return _error(400, "bad_request", say.BAD_REQUEST)


def _limited(request: Request, settings, lang: str):
    """A 429 answer once this caller made RATE_LIMIT_PER_HOUR requests in the last hour."""
    if app.state.limiter.allow(client_key(request), settings.rate_limit_per_hour):
        return None
    return _error(429, "rate_limited", say.RATE_LIMITED, lang if lang in LANGS else "en")


@app.post("/scan")
async def scan(
    request: Request,
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
    if limited := _limited(request, settings, lang):
        return limited
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
    raw = await image.read(settings.max_upload_bytes + 1)  # never hold more than the limit
    if len(raw) > settings.max_upload_bytes:
        return fail(400, "bad_request", say.BAD_REQUEST, "image too large")
    try:
        jpeg, width, height = prepare_jpeg(raw, max(settings.image_max_px, settings.muse_max_px))
        sam_jpeg, sam_w, sam_h = jpeg, width, height
        if settings.muse_max_px > settings.image_max_px:
            sam_jpeg, sam_w, sam_h = prepare_jpeg(jpeg, settings.image_max_px)
    except BadImage as exc:
        return fail(400, "bad_request", say.BAD_REQUEST, str(exc))
    trace["image"] = {"width": width, "height": height, "sam": [sam_w, sam_h]}

    req = ScanRequest(intent, lang, paid, price, attempt, max_attempts)
    work = scan_flow.execute(
        app.state.http, jpeg, width, height, req, settings, trace_id, trace,
        sam_image=(sam_jpeg, sam_w, sam_h),
    )  # fmt: skip
    work = _in_language(work, lang)
    crash_body = {"error": "upstream_error", **_speech(say.TRY_AGAIN, lang), "trace_id": trace_id}
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
        spoken = _speech(say.STILL_COUNTING, job.lang)
        content.update(result=None, poll_after_ms=POLL_AFTER_MS, **spoken)
    elif job.status == "done":
        content["result"] = job.body
    else:
        content.update(result=None, **job.body)
    return content


@app.post("/intent")
async def intent(
    request: Request,
    audio: Annotated[UploadFile, File()],
    lang: Annotated[str, Form()] = "en",
):
    """A spoken question -> what to do next (docs/api.md section 1). Meta Omnilingual ASR hears
    it and Muse turns the transcript into the intent (Gemini only when ASR_URL is not set).
    Neither the audio nor the transcript is kept."""
    settings = get_settings()
    if limited := _limited(request, settings, lang):
        return limited
    voice: Voice = app.state.voice
    trace_id = new_trace_id()
    hint = lang if lang in LANGS else "en"
    trace: dict = {"endpoint": "/intent", "inputs": {"lang": hint}}
    started = time.perf_counter()

    def fail(status: int, error: str, text: str, detail: str):
        trace.update(outcome=error, detail=detail, speech_en=text)
        trace["timing_ms"] = {"total": int((time.perf_counter() - started) * 1000)}
        write_trace(settings.trace_dir, trace_id, trace)
        return _error(status, error, text, hint, trace_id)

    engine = hears(settings)
    trace["engine"] = engine
    if engine == "off":
        return fail(501, "not_implemented", say.VOICE_TODO, "neither ASR_URL nor GEMINI_API_KEY")
    raw = await audio.read(settings.max_audio_bytes + 1)
    mime = gemini.audio_mime(audio.filename, audio.content_type)
    trace["inputs"].update(audio_bytes=len(raw), mime=mime)
    if not raw or len(raw) > settings.max_audio_bytes or mime is None:
        return fail(400, "bad_request", say.BAD_AUDIO, "audio missing, too large or not audio")
    timing: dict = {}
    try:
        if engine == "omnilingual":
            t = time.perf_counter()
            transcript = await asr.transcribe(app.state.http, raw, mime, hint, settings)
            timing["asr"] = int((time.perf_counter() - t) * 1000)
            trace["heard_chars"] = len(transcript)  # never the words themselves
            t = time.perf_counter()
            if transcript:
                heard = await understand.from_text(app.state.http, transcript, settings)
            else:
                heard = {"lang": None, "intent": "silent", "paid": None, "price": None}
            timing["intent"] = int((time.perf_counter() - t) * 1000)
        else:
            heard = await gemini.understand(app.state.http, raw, mime, settings)
    except (asr.AsrError, understand.UnderstandError, gemini.GeminiError) as exc:
        return fail(502, "upstream_error", say.NOT_HEARD, str(exc))

    spoken_lang = heard["lang"] or hint
    kind, paid, price = heard["intent"], heard["paid"], heard["price"]
    # next: "scan" = start a scan with this intent; "ask" = speak, then record again;
    # "done" = nothing to scan (paid exactly the price).
    if kind == "count":
        text, step = say.COUNT_PROMPT, "scan"
    elif kind == "change" and (paid is None or price is None):
        text, step = say.NEED_PRICE, "ask"
    elif kind == "change" and paid < price:
        text, step = say.PRICE_OVER_PAID, "ask"
    elif kind == "change":
        text, step = say.change_prompt(paid, price), "scan" if paid > price else "done"
    elif kind == "silent":  # the recogniser heard nothing
        kind, text, step = "unknown", say.NOT_HEARD, "ask"
    else:
        text, step = say.INTENT_UNKNOWN, "ask"
    try:
        speech = await voice.localize(text, spoken_lang)
    except Exception:  # noqa: BLE001 - the intent still stands; speak it in English
        log.exception("could not localize an intent answer")
        speech = {"speech": {"en": text}}
    timing["total"] = int((time.perf_counter() - started) * 1000)
    trace.update(
        outcome=kind, next=step, lang=spoken_lang, paid=paid, price=price, speech_en=text,
        timing_ms=timing,
    )  # fmt: skip
    write_trace(settings.trace_dir, trace_id, trace)
    return {
        "intent": kind,
        "next": step,
        "lang": spoken_lang,
        "paid": paid,
        "price": price,
        **speech,
        "trace_id": trace_id,
    }


@app.get("/speak/{clip_id}")
async def speak(clip_id: str):
    """WAV for a `speech_audio` link this backend handed out. Unknown ids get 404."""
    if not _CLIP_ID.fullmatch(clip_id):
        return _error(404, "not_found", say.TRY_AGAIN)
    try:
        wav = await app.state.voice.audio(clip_id)
    except mms.MmsError:
        return _error(502, "upstream_error", say.TRY_AGAIN)
    if wav is None:
        return _error(404, "not_found", say.TRY_AGAIN)
    cache = {"Cache-Control": "public, max-age=604800, immutable"}
    return Response(content=wav, media_type="audio/wav", headers=cache)


@app.get("/phrases")
async def phrases(lang: str = "en"):
    """The app's own prompts in `lang`, with audio links where Gemini speaks that language."""
    lang = lang if lang in LANGS else "en"
    voice: Voice = app.state.voice
    out = {}
    for key, en in say.APP_PHRASES.items():
        fields = voice.speech(en, lang)
        out[key] = {"text": fields["speech"].get(lang, en), "audio": fields.get("speech_audio")}
    return {"lang": lang, "phrases": out}


@app.get("/health")
async def health():
    # refs: read B's reference sheets are loaded; without them no scan can speak a total.
    # sam: which SAM provider counts the notes (roboflow, modal or off).
    # voice.hears: which engine hears questions (omnilingual, gemini or off); voice.intent: POST
    # /intent works. voice.translates: answers come in Amharic and Oromo (fixed templates, always
    # on). voice.tts / speaks: Meta MMS clips, and in which languages.
    settings = get_settings()
    voice: Voice = app.state.voice
    return {
        "ok": True,
        "refs": muse.load_refs(settings.refs_dir) is not None,
        "sam": settings.sam_provider,
        "voice": {
            "hears": hears(settings),
            "intent": hears(settings) != "off",
            "translates": True,
            "tts": voice.tts,
            "speaks": [lang for lang in TRANSLATED if voice.speaks(lang)],
        },
    }
