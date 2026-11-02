"""Local ASR service for Birr: Omnilingual ASR 300M on CPU. Bind to 127.0.0.1 only."""

import io
import os
import tempfile
import time

import av
import numpy as np
import soundfile as sf
import torch
from fastapi import FastAPI, HTTPException, Request

MODEL = os.environ.get("ASR_MODEL", "omniASR_CTC_300M_v2")
LANGS = {"amh_Ethi", "orm_Latn", "eng_Latn"}
MAX_S = 30.0
torch.set_num_threads(int(os.environ.get("ASR_THREADS", "4")))
from omnilingual_asr.models.inference.pipeline import ASRInferencePipeline  # noqa: E402

pipe = ASRInferencePipeline(model_card=MODEL, device="cpu", dtype=torch.float32)
app = FastAPI()


def decode16k(raw: bytes) -> np.ndarray:
    """Decode any container (m4a/aac, webm/opus, wav) to 16 kHz mono float32."""
    try:
        with av.open(io.BytesIO(raw)) as c:
            st = next(s for s in c.streams if s.type == "audio")
            rs = av.AudioResampler(format="s16", layout="mono", rate=16000)
            chunks = []
            for fr in c.decode(st):
                for o in rs.resample(fr):
                    chunks.append(o.to_ndarray().reshape(-1))
            for o in rs.resample(None):
                chunks.append(o.to_ndarray().reshape(-1))
    except Exception as e:
        raise HTTPException(400, f"unreadable audio: {type(e).__name__}") from None
    if not chunks:
        raise HTTPException(400, "no audio")
    return np.concatenate(chunks).astype(np.float32) / 32768.0


@app.get("/health")
def health():
    return {"ok": True, "model": MODEL}


@app.post("/transcribe")
async def transcribe(request: Request, lang: str = "eng_Latn"):
    if lang not in LANGS:
        raise HTTPException(400, "bad lang")
    raw = await request.body()
    if not raw:
        raise HTTPException(400, "empty body")
    t0 = time.time()
    wav = decode16k(raw)
    if len(wav) / 16000 > MAX_S:
        raise HTTPException(400, "clip over 30 s")
    try:
        with tempfile.NamedTemporaryFile(suffix=".wav") as f:
            sf.write(f.name, wav, 16000)
            out = pipe.transcribe([f.name], lang=[lang], batch_size=1)
        text = out[0]
    except Exception as e:
        raise HTTPException(500, f"model error: {type(e).__name__}") from None
    return {"text": text, "lang": lang, "ms": int((time.time() - t0) * 1000)}
