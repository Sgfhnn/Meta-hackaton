"""One scan, start to finish: two Muse reads + SAM in parallel, a time limit, one retry.

Flow (docs/api.md section 2):
1. SAM and MUSE_READS (default 2) Muse reads start together.
2. If every read is back within TWO_READ_TIMEOUT_S, decide on the two reads.
3. Otherwise (slow or failed reads) retry once with a single read: use a read that already came
   back if there is one, else start one more read (on the fallback reader when MUSE_FALLBACK is
   on) and take the first read that finishes before the hard limit.
4. The whole scan never runs past SCAN_DEADLINE_S. Past it, the answer is a rescan.
"""

from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass

import httpx

from birr.agent.decide import decide
from birr.agent.trace import write_trace
from birr.config import Settings
from birr.read import muse
from birr.segment import sam
from birr.segment.filter import filter_regions
from birr.voice import speech as say


@dataclass(frozen=True)
class ScanRequest:
    intent: str
    lang: str
    paid: int | None
    price: int | None
    attempt: int
    max_attempts: int


def _ms(start: float) -> int:
    return int((time.perf_counter() - start) * 1000)


async def _read(client, jpeg, settings, reader: str, slot: int, with_refs: bool = False) -> dict:
    start = time.perf_counter()
    try:
        labels = await muse.read_notes(client, jpeg, settings, reader=reader, with_refs=with_refs)
    except muse.MuseError as exc:
        return {"slot": slot, "reader": reader, "ok": False, "error": str(exc), "ms": _ms(start)}
    return {"slot": slot, "reader": reader, "ok": True, "labels": labels, "ms": _ms(start)}


async def _sam(client, jpeg, width, height, settings) -> dict:
    start = time.perf_counter()
    if settings.sam_off or settings.sam_provider == "off":
        return {"ok": False, "error": "disabled", "ms": 0}
    try:
        regions = await sam.segment(client, jpeg, width, height, settings)
    except (TimeoutError, sam.SamError) as exc:
        return {"ok": False, "error": str(exc) or type(exc).__name__, "ms": _ms(start)}
    return {"ok": True, "regions": regions, "ms": _ms(start)}


async def _cancel(tasks) -> None:
    for t in tasks:
        t.cancel()
    await asyncio.gather(*tasks, return_exceptions=True)


async def collect_reads(client, jpeg, settings: Settings, deadline: float, trace: dict):
    """Return (reads, mode, timed_out). reads holds the label lists the decision uses."""
    n = max(1, settings.muse_reads)
    started = time.perf_counter()
    tasks = {
        asyncio.create_task(_read(client, jpeg, settings, muse.PRIMARY, i, with_refs=i == 1)): i
        for i in range(n)
    }
    stage1 = max(0.0, min(settings.two_read_timeout_s, deadline - time.perf_counter()))
    done, pending = await asyncio.wait(tasks, timeout=stage1)
    results = [t.result() for t in done]
    log = trace.setdefault("reads", [])
    log.extend(results)
    ok = sorted((r for r in results if r["ok"]), key=lambda r: r["slot"])
    trace["timing_ms"]["reads_stage"] = _ms(started)

    if len(ok) == n:
        return [r["labels"] for r in ok], "two_read" if n > 1 else "single_read", False

    # Retry once with a single read.
    trace["retry"] = {"reason": "slow" if pending else "read_failed"}
    if ok:
        await _cancel(pending)
        log.extend({"slot": tasks[t], "ok": False, "error": "cancelled"} for t in pending)
        trace["retry"]["used"] = "finished_read"
        return [ok[0]["labels"]], "single_read", False

    reader = muse.FALLBACK if settings.fallback_reader == muse.FALLBACK else muse.PRIMARY
    retry = asyncio.create_task(_read(client, jpeg, settings, reader, n))
    trace["retry"]["used"] = f"new_read:{reader}"
    waiting = set(pending) | {retry}
    retry_start = time.perf_counter()
    try:
        while waiting:
            left = deadline - time.perf_counter()
            if left <= 0:
                break
            done, waiting = await asyncio.wait(
                waiting, timeout=left, return_when=asyncio.FIRST_COMPLETED
            )
            for t in done:
                r = t.result()
                log.append(r)
                if r["ok"]:
                    return [r["labels"]], "single_read", False
        timed_out = bool(waiting)
        return [], "single_read", timed_out
    finally:
        trace["timing_ms"]["retry"] = _ms(retry_start)
        if waiting:
            await _cancel(waiting)
            log.extend({"slot": "late", "ok": False, "error": "cancelled"} for _ in waiting)


async def execute(
    client: httpx.AsyncClient,
    jpeg: bytes,
    width: int,
    height: int,
    req: ScanRequest,
    settings: Settings,
    trace_id: str,
    trace: dict,
    sam_image: tuple[bytes, int, int] | None = None,
) -> tuple[int, dict]:
    """Run one scan. Returns (http status, body) and writes the trace."""
    started = time.perf_counter()
    deadline = started + settings.scan_deadline_s
    trace["timing_ms"] = {}
    sam_jpeg, sam_w, sam_h = sam_image or (jpeg, width, height)
    sam_task = asyncio.create_task(_sam(client, sam_jpeg, sam_w, sam_h, settings))
    try:
        reads, mode, timed_out = await collect_reads(client, jpeg, settings, deadline, trace)
        left = max(0.0, deadline - time.perf_counter())
        done, _ = await asyncio.wait({sam_task}, timeout=left)
        sam_result = sam_task.result() if done else {"ok": False, "error": "deadline", "ms": None}
    finally:
        if not sam_task.done():
            await _cancel([sam_task])

    timing = trace["timing_ms"]
    timing["sam"] = sam_result["ms"]
    timing["muse_reads"] = [r.get("ms") for r in trace["reads"]]
    timing["muse"] = timing.get("reads_stage", 0) + timing.get("retry", 0)
    trace["mode"] = mode

    regions = None
    trace["sam_provider"] = settings.sam_provider
    if sam_result["ok"]:
        regions, decisions = filter_regions(
            sam_result["regions"], settings.sam_min_score, settings.sam_min_area
        )
        trace["sam"] = {
            "raw_count": len(sam_result["regions"]),
            "kept": len(regions),
            "filter": decisions,
        }
    else:
        trace["sam_error"] = sam_result["error"]

    def finish(status: int, body: dict, text: str) -> tuple[int, dict]:
        timing["total"] = _ms(started)
        spoken, todo = say.speech(text, req.lang)
        body = {**body, "speech": spoken, "trace_id": trace_id}
        if todo:
            body["speech_todo"] = todo
        if status == 200:
            body["timing_ms"] = {k: timing.get(k) for k in ("muse", "sam", "total")}
        trace.update(speech_en=text, timing_ms=timing)
        write_trace(settings.trace_dir, trace_id, trace)
        return status, body

    if not reads:
        if timed_out:
            # Past the hard limit: a rescan answer, not an error, so the app keeps going.
            text = say.GIVE_UP if req.attempt >= req.max_attempts else say.SLOW_RESCAN
            trace.update(outcome="rescan", detail="scan deadline reached", total=None)
            body = {"outcome": "rescan", "total": None, "change": None, "notes": [], "hint": None}
            return finish(200, body, text)
        trace.update(outcome="upstream_error", detail="every Muse read failed")
        return finish(502, {"error": "upstream_error"}, say.TRY_AGAIN)

    result = decide(
        reads,
        regions,
        intent=req.intent,
        paid=req.paid,
        price=req.price,
        attempt=req.attempt,
        max_attempts=req.max_attempts,
        muse_only_totals=settings.muse_only_totals,
        sam_advisory=settings.sam_advisory,
    )
    text = result.pop("speech_en")
    trace.update(
        sam_available=regions is not None,
        sam_advisory=settings.sam_advisory,
        path=result.pop("path", None),
        muse_only_totals=settings.muse_only_totals,
        muse={"labels": reads[0], "reads_used": reads},
        outcome=result["outcome"],
        total=result["total"],
        change=result["change"],
        hint=result["hint"],
    )
    return finish(200, result, text)
