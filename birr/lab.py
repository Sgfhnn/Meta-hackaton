"""Reader lab: a token-protected test bench for prompt and reader experiments.

Off unless LAB_TOKEN is set. Photos and truths live in LAB_DIR (outside the repo):
  LAB_DIR/<set>/<name>.jpg and LAB_DIR/<set>/truths.json ({"D01": 60, ...}).
Every call needs the header X-Lab-Token (or ?token=). The provider keys never leave the server.
Muse calls are capped per UTC day by LAB_DAILY_LIMIT (they cost Baseten credit).
"""

from __future__ import annotations

import asyncio
import base64
import io
import json
import os
import statistics
import time
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path
from typing import Literal

import httpx
from fastapi import APIRouter, Depends, Header, HTTPException, Query, Request
from fastapi.responses import Response
from PIL import Image
from pydantic import BaseModel, Field

from birr.config import VALID_DENOMINATIONS, get_settings
from birr.read import muse
from birr.read.prompt import PROMPT
from birr.segment import filter as sam_filter
from birr.segment import sam

_KNOWLEDGE = PROMPT[
    PROMPT.index("Ethiopian birr notes in circulation:") : PROMPT.index("Reply with ONLY JSON")
]
CROP_PROMPT = (
    "This image is a crop around ONE Ethiopian birr banknote taken from a photo of a pile of cash. "
    "Parts of neighbouring notes may show at the edges: ignore them and identify only the note "
    "that fills the middle of the crop.\n\n" + _KNOWLEDGE + "Reply with ONLY JSON, no other text:\n"
    '{"notes": [{"value": 5|10|50|100|200|null, "evidence": ["latin numeral"|"geez numeral"|'
    '"amount text"|"picture"|"colour"], "status": "read"|"unclear"}]}\n'
    'Exactly one entry, for the middle note. Use value null with status "unclear" if you cannot '
    "identify it."
)

_calls = {"day": "", "n": 0}
_sem = asyncio.Semaphore(int(os.getenv("LAB_CONCURRENCY", "8")))


def _lab_dir() -> Path:
    return Path(os.getenv("LAB_DIR", "/data/home/lab"))


def _check(
    request: Request, x_lab_token: str | None = Header(None), token: str | None = Query(None)
):
    want = os.getenv("LAB_TOKEN", "")
    if not want or (x_lab_token or token) != want:
        raise HTTPException(status_code=401, detail="bad or missing lab token")


router = APIRouter(prefix="/lab", dependencies=[Depends(_check)])


def _spend(n: int) -> None:
    day = datetime.now(UTC).strftime("%Y-%m-%d")
    if _calls["day"] != day:
        _calls.update(day=day, n=0)
    limit = int(os.getenv("LAB_DAILY_LIMIT", "3000"))
    if _calls["n"] + n > limit:
        raise HTTPException(status_code=429, detail=f"daily Muse call limit {limit} reached")
    _calls["n"] += n


class ReadConfig(BaseModel):
    prompt: str | None = Field(None, description="Full prompt text. Default: the live prompt.")
    refs: bool = Field(
        False, description="Send the two reference sheets before the photo (live read B)."
    )
    reader: Literal["baseten", "cline"] = Field(
        "baseten", description="baseten = muse-spark-open-1026, cline = muse-spark-1.3"
    )
    model: str | None = Field(None, description="Override the model name for the chosen reader.")
    effort: str | None = Field(
        "low", description="reasoning_effort: low|medium|high, or '' to leave it out."
    )
    temperature: float = 0.0
    max_px: int = Field(768, ge=256, le=2048, description="Longest side of the photo sent to Muse.")
    mode: Literal["pile", "crops"] = Field(
        "pile", description="pile = one read of the whole photo; crops = one read per SAM box."
    )
    crop_prompt: str | None = Field(
        None,
        description="Prompt for each crop (crops mode). Default: a one-note version of the live prompt.",
    )
    crop_pad: float = Field(
        0.08,
        ge=0,
        le=0.5,
        description="Padding around each SAM box, as a fraction of the box size.",
    )
    crop_px: int = Field(512, ge=128, le=1536)


class SamConfig(BaseModel):
    min_score: float = sam_filter.MIN_SCORE
    min_area: float = sam_filter.MIN_AREA
    nms_iou: float = sam_filter.NMS_IOU
    prompt: str = "banknote"


class ReadRequest(BaseModel):
    photo: str | None = Field(None, description="'<set>/<name>', e.g. 'dev/D01'.")
    image_b64: str | None = Field(None, description="Or your own JPEG, base64.")
    read: ReadConfig = ReadConfig()
    sam: SamConfig = SamConfig()


class EvalRequest(BaseModel):
    set: str = "dev"
    photos: list[str] | None = Field(None, description="Names in the set; default all.")
    reads: list[ReadConfig] = Field(
        default_factory=lambda: [ReadConfig(), ReadConfig(refs=True)],
        description="Reads run in parallel per photo. Default = the live pair (A plain, B with sheets).",
    )
    sam_check: bool = Field(
        True, description="A total is spoken only if the note count equals SAM's kept count."
    )
    sam: SamConfig = SamConfig()


def _load_photo(ref: str) -> tuple[bytes, int | None]:
    set_name, _, name = ref.partition("/")
    folder = _lab_dir() / set_name
    path = folder / f"{name}.jpg"
    if not set_name or not name or ".." in ref or not path.is_file():
        raise HTTPException(status_code=404, detail=f"no photo {ref}")
    truths = _truths(set_name)
    return path.read_bytes(), truths.get(name)


def _truths(set_name: str) -> dict:
    try:
        return json.loads((_lab_dir() / set_name / "truths.json").read_text())
    except (OSError, ValueError):
        return {}


def _resize(img: Image.Image, max_px: int) -> bytes:
    img = img.copy()
    img.thumbnail((max_px, max_px))
    out = io.BytesIO()
    img.save(out, format="JPEG", quality=90)
    return out.getvalue()


def _open(raw: bytes) -> Image.Image:
    img = Image.open(io.BytesIO(raw)).convert("RGB")
    img.thumbnail((2048, 2048))
    return img


async def _muse(
    client: httpx.AsyncClient, jpeg: bytes, cfg: ReadConfig, prompt: str, refs: list | None
) -> dict:
    s = get_settings()
    reader = muse.FALLBACK if cfg.reader == "cline" else muse.PRIMARY
    url, model, key = muse._endpoint(s, reader)
    content: list[dict] = [{"type": "text", "text": prompt}]
    if refs:
        content.append({"type": "text", "text": muse.REFS_INTRO})
        for (_, caption), sheet in zip(muse.REF_SHEETS, refs, strict=True):
            content += [{"type": "text", "text": caption}, muse._image(sheet)]
    content += [{"type": "text", "text": muse.PHOTO_LABEL}, muse._image(jpeg)]
    body = {"model": cfg.model or model, "temperature": cfg.temperature,
            "messages": [{"role": "user", "content": content}]}  # fmt: skip
    if cfg.effort:
        body["reasoning_effort"] = cfg.effort
    start = time.perf_counter()
    async with _sem:
        try:
            resp = await client.post(
                url, json=body, headers={"Authorization": f"Bearer {key}"}, timeout=120
            )
            data = resp.json()
            if (
                isinstance(data, dict)
                and "choices" not in data
                and isinstance(data.get("data"), dict)
            ):
                data = data["data"]
            if resp.status_code >= 400:
                return {"ok": False, "error": f"HTTP {resp.status_code}: {str(data)[:300]}",
                        "ms": int((time.perf_counter() - start) * 1000)}  # fmt: skip
            text = data["choices"][0]["message"]["content"]
            usage = data.get("usage")
        except Exception as exc:  # noqa: BLE001 - lab reports every failure
            return {"ok": False, "error": f"{type(exc).__name__}: {exc}"[:300],
                    "ms": int((time.perf_counter() - start) * 1000)}  # fmt: skip
    ms = int((time.perf_counter() - start) * 1000)
    try:
        labels = muse.parse_labels(text)
    except muse.MuseError:
        return {
            "ok": False,
            "error": "no JSON notes in reply",
            "raw": text,
            "ms": ms,
            "usage": usage,
        }
    return {"ok": True, "labels": labels, "raw": text, "ms": ms, "usage": usage}


async def _sam(client: httpx.AsyncClient, img: Image.Image, cfg: SamConfig) -> dict:
    s = get_settings()
    jpeg = _resize(img, s.image_max_px)
    small = Image.open(io.BytesIO(jpeg))
    start = time.perf_counter()
    body = {"image": {"type": "base64", "value": base64.b64encode(jpeg).decode()},
            "prompts": [{"type": "text", "text": cfg.prompt}],
            "output_prob_thresh": 0.5, "format": "polygon"}  # fmt: skip
    try:
        resp = await client.post(s.sam_url, json=body, headers={"Authorization": f"Bearer {s.sam_key}"},
                                 timeout=s.sam_timeout_s * 2)  # fmt: skip
        resp.raise_for_status()
        regions = sam.regions_from_response(resp.json(), small.width, small.height)
    except Exception as exc:  # noqa: BLE001
        return {
            "ok": False,
            "error": f"{type(exc).__name__}",
            "ms": int((time.perf_counter() - start) * 1000),
        }
    kept, log = [], []
    for r in sorted(regions, key=lambda r: r.score, reverse=True):
        e = {"box": [round(v, 4) for v in r.box], "score": round(r.score, 3)}
        if r.score < cfg.min_score:
            log.append({**e, "kept": False, "reason": "low_score"})
        elif r.area < cfg.min_area:
            log.append({**e, "kept": False, "reason": "small_area"})
        elif any(sam_filter.iou(r, k) >= cfg.nms_iou for k in kept):
            log.append({**e, "kept": False, "reason": "duplicate"})
        else:
            kept.append(r)
            log.append({**e, "kept": True, "reason": None})
    return {"ok": True, "kept": len(kept), "boxes": [k.box for k in kept], "regions": log,
            "ms": int((time.perf_counter() - start) * 1000)}  # fmt: skip


def _crop(img: Image.Image, box, pad: float, px: int) -> bytes:
    x, y, w, h = box
    x0, y0 = max(0.0, x - w * pad), max(0.0, y - h * pad)
    x1, y1 = min(1.0, x + w * (1 + pad)), min(1.0, y + h * (1 + pad))
    c = img.crop(
        (int(x0 * img.width), int(y0 * img.height), int(x1 * img.width), int(y1 * img.height))
    )
    return _resize(c, px)


def _total(labels: list[str]) -> int | None:
    if not labels or any(lab not in {str(v) for v in VALID_DENOMINATIONS} for lab in labels):
        return None
    return sum(int(lab) for lab in labels)


async def _run_read(client, img: Image.Image, cfg: ReadConfig, sam_res: dict | None) -> dict:
    s = get_settings()
    refs = None
    if cfg.refs:
        refs = muse.load_refs(s.refs_dir)
        if refs is None:
            return {"ok": False, "error": "reference sheets missing on server"}
    if cfg.mode == "pile":
        _spend(1)
        r = await _muse(client, _resize(img, cfg.max_px), cfg, cfg.prompt or PROMPT, refs)
    else:
        if not sam_res or not sam_res.get("ok"):
            return {"ok": False, "error": "crops mode needs SAM boxes; SAM failed"}
        boxes = sam_res["boxes"]
        if not boxes:
            return {"ok": True, "labels": [], "crops": [], "ms": 0}
        _spend(len(boxes))
        start = time.perf_counter()
        parts = await asyncio.gather(*[
            _muse(client, _crop(img, b, cfg.crop_pad, cfg.crop_px), cfg, cfg.crop_prompt or CROP_PROMPT, refs)
            for b in boxes
        ])  # fmt: skip
        labels = [(p["labels"][0] if p["ok"] and p["labels"] else "unclear") for p in parts]
        r = {"ok": all(p["ok"] for p in parts), "labels": labels,
             "crops": [{"box": [round(v, 4) for v in b], **p} for b, p in zip(boxes, parts, strict=True)],
             "ms": int((time.perf_counter() - start) * 1000)}  # fmt: skip
    if r.get("ok") or r.get("labels"):
        r["total"] = _total(r.get("labels") or [])
    return r


def _decide(reads: list[dict], sam_res: dict | None, sam_check: bool) -> dict:
    if not all(r.get("ok") for r in reads):
        return {"total": None, "why": "a read failed"}
    sets = [Counter(r["labels"]) for r in reads]
    if any(c != sets[0] for c in sets[1:]):
        return {"total": None, "why": "reads disagree"}
    total = _total(reads[0]["labels"])
    if total is None:
        return {"total": None, "why": "unclear note"}
    if sam_check:
        if not sam_res or not sam_res.get("ok"):
            return {"total": None, "why": "SAM down"}
        if sam_res["kept"] != len(reads[0]["labels"]):
            return {
                "total": None,
                "why": f"count {len(reads[0]['labels'])} vs SAM {sam_res['kept']}",
            }
    return {"total": total, "why": "agree"}


@router.get("")
async def lab_help():
    return {
        "about": "Birr reader lab. Send X-Lab-Token on every call. Keys stay on the server.",
        "endpoints": {
            "GET /lab/photos": "sets, photo names, truths",
            "GET /lab/photos/{set}/{name}": "the JPEG itself",
            "GET /lab/defaults": "live prompt, crop prompt, reference captions, models, SAM filter",
            "POST /lab/read": "one photo, one read config -> labels, raw reply, total, ms, SAM boxes",
            "POST /lab/eval": "a whole set with N parallel reads + the agreement/SAM rule -> scoreboard",
            "GET /lab/usage": "Muse calls used today vs limit",
        },
        "rules": "Tune on 'dev' only. 'locked' is for error analysis, never for tuning.",
    }


@router.get("/usage")
async def lab_usage():
    return {
        "day": _calls["day"],
        "muse_calls": _calls["n"],
        "limit": int(os.getenv("LAB_DAILY_LIMIT", "3000")),
    }


@router.get("/defaults")
async def lab_defaults():
    s = get_settings()
    return {"prompt": PROMPT, "crop_prompt": CROP_PROMPT, "refs_intro": muse.REFS_INTRO,
            "ref_captions": [c for _, c in muse.REF_SHEETS], "photo_label": muse.PHOTO_LABEL,
            "baseten_model": s.muse_model, "cline_model": s.cline_model, "live_effort": s.muse_reasoning_effort,
            "sam": SamConfig().model_dump(), "max_px": s.image_max_px}  # fmt: skip


@router.get("/photos")
async def lab_photos():
    out = {}
    for d in sorted(p for p in _lab_dir().iterdir() if p.is_dir()):
        out[d.name] = {"truths": _truths(d.name), "photos": sorted(p.stem for p in d.glob("*.jpg"))}
    return out


@router.get("/photos/{set_name}/{name}")
async def lab_photo(set_name: str, name: str):
    raw, _ = _load_photo(f"{set_name}/{name.removesuffix('.jpg')}")
    return Response(raw, media_type="image/jpeg")


@router.post("/read")
async def lab_read(req: ReadRequest, request: Request):
    truth = None
    if req.photo:
        raw, truth = _load_photo(req.photo)
    elif req.image_b64:
        raw = base64.b64decode(req.image_b64)
    else:
        raise HTTPException(status_code=400, detail="give photo or image_b64")
    img = _open(raw)
    client = request.app.state.http
    sam_res = await _sam(client, img, req.sam)
    r = await _run_read(client, img, req.read, sam_res)
    return {"photo": req.photo, "truth": truth, "read": r, "sam": sam_res}


@router.post("/eval")
async def lab_eval(req: EvalRequest, request: Request):
    truths = _truths(req.set)
    names = req.photos or sorted(p.stem for p in (_lab_dir() / req.set).glob("*.jpg"))
    client = request.app.state.http

    async def one(name: str) -> dict:
        raw, truth = _load_photo(f"{req.set}/{name}")
        img = _open(raw)
        start = time.perf_counter()
        sam_res = await _sam(client, img, req.sam)
        reads = await asyncio.gather(*[_run_read(client, img, c, sam_res) for c in req.reads])
        d = _decide(list(reads), sam_res, req.sam_check)
        verdict = (
            "no_total" if d["total"] is None else ("exact" if d["total"] == truth else "WRONG")
        )
        return {"photo": name, "truth": truth, "spoken": d["total"], "verdict": verdict, "why": d["why"],
                "ms": int((time.perf_counter() - start) * 1000), "sam_kept": sam_res.get("kept"),
                "reads": [{"labels": r.get("labels"), "total": r.get("total"), "ms": r.get("ms"),
                           "error": r.get("error"), "raw": r.get("raw"), "crops": r.get("crops")} for r in reads]}  # fmt: skip

    rows = await asyncio.gather(*[one(n) for n in names])
    ms = sorted(r["ms"] for r in rows)
    per_read_exact = [
        sum(r["reads"][i]["total"] == r["truth"] for r in rows) for i in range(len(req.reads))
    ]
    return {
        "summary": {
            "photos": len(rows),
            "exact": sum(r["verdict"] == "exact" for r in rows),
            "wrong_spoken": sum(r["verdict"] == "WRONG" for r in rows),
            "no_total": sum(r["verdict"] == "no_total" for r in rows),
            "per_read_exact_if_alone": per_read_exact,
            "p50_ms": int(statistics.median(ms)) if ms else None,
            "p90_ms": ms[min(len(ms) - 1, int(len(ms) * 0.9))] if ms else None,
            "truths_known": truths != {},
        },
        "rows": rows,
    }
