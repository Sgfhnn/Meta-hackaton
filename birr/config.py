"""Runtime settings, read from the environment. No secrets live in code."""

from __future__ import annotations

import os
from dataclasses import dataclass, field

VALID_DENOMINATIONS = (5, 10, 50, 100, 200)


def _flag(name: str, default: bool) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


@dataclass(frozen=True)
class Settings:
    muse_url: str = field(
        default_factory=lambda: (
            os.getenv("MODEL_BASE_URL", "https://inference.baseten.co/v1").rstrip("/")
            + "/chat/completions"
        )
    )
    muse_model: str = field(
        default_factory=lambda: os.getenv("MODEL_NAME", "meta-models/muse-spark-open-1026")
    )
    # BASETEN_API_KEY is the name the backend uses; MODEL_API_KEY is accepted for older .env files.
    muse_key: str = field(
        default_factory=lambda: os.getenv("BASETEN_API_KEY") or os.getenv("MODEL_API_KEY", "")
    )
    sam_url: str = field(
        default_factory=lambda: os.getenv(
            "SAM_URL", "https://serverless.roboflow.com/sam3/concept_segment"
        )
    )
    sam_key: str = field(default_factory=lambda: os.getenv("ROBOFLOW_API_KEY", ""))
    image_max_px: int = field(default_factory=lambda: int(os.getenv("IMAGE_MAX_PX", "768")))
    # Size of the photo sent to Muse. SAM always gets IMAGE_MAX_PX. 2048 = Muse's narrowed design
    # (lab runs 7-9: the plain read went 9/20 -> 17/20 on the locked set at full size).
    muse_max_px: int = field(
        default_factory=lambda: int(os.getenv("MUSE_MAX_PX") or os.getenv("IMAGE_MAX_PX", "768"))
    )
    # SAM filter. Live 0.6 / 0.015; Muse's design 0.5 / 0.005 (keeps fan strips).
    sam_min_score: float = field(default_factory=lambda: float(os.getenv("SAM_MIN_SCORE", "0.6")))
    sam_min_area: float = field(default_factory=lambda: float(os.getenv("SAM_MIN_AREA", "0.015")))
    # SAM_ADVISORY=1: when both reads agree (same notes, none unclear) the total is spoken and
    # SAM's count is only logged. Off = the live rule, where SAM's count must match.
    sam_advisory: bool = field(default_factory=lambda: _flag("SAM_ADVISORY", False))
    # SAM_OFF=1: never call SAM. Pair with MUSE_ONLY_TOTALS=1 so two agreeing reads speak;
    # disagreement then always ends as rescan (no "move this note" hint).
    sam_off: bool = field(default_factory=lambda: _flag("SAM_OFF", False))
    # Which SAM serves the count: "roboflow" (hosted SAM 3, the default), "modal" (our own SAM 3.1
    # endpoint, see modal_sam/) or "off". SAM_OFF=1 still means off.
    sam_provider: str = field(
        default_factory=lambda: (
            "off"
            if _flag("SAM_OFF", False)
            else os.getenv("SAM_PROVIDER", "roboflow").strip().lower()
        )
    )
    sam_prompt: str = field(default_factory=lambda: os.getenv("SAM_PROMPT", "banknote").strip())
    # Modal SAM 3.1 endpoint: the URL `modal deploy` prints, plus a proxy-auth token pair.
    sam_modal_url: str = field(default_factory=lambda: os.getenv("SAM_MODAL_URL", "").strip())
    sam_modal_key: str = field(default_factory=lambda: os.getenv("SAM_MODAL_KEY", ""))
    sam_modal_secret: str = field(default_factory=lambda: os.getenv("SAM_MODAL_SECRET", ""))
    # A GPU container that has scaled to zero needs time to start and load the model.
    sam_modal_timeout_s: float = field(
        default_factory=lambda: float(os.getenv("SAM_MODAL_TIMEOUT_S", "25"))
    )
    max_upload_bytes: int = field(
        default_factory=lambda: int(os.getenv("MAX_UPLOAD_BYTES", str(10 * 1024 * 1024)))
    )
    # Reader settings. Two Muse reads run in parallel; a total needs both to list the same notes.
    muse_reads: int = field(default_factory=lambda: int(os.getenv("MUSE_READS", "2")))
    # OpenAI-style reasoning_effort sent to Muse. Empty string leaves it out of the request.
    muse_reasoning_effort: str = field(
        default_factory=lambda: os.getenv("MUSE_REASONING_EFFORT", "low").strip()
    )
    # Optional fallback reader (Muse Spark 1.3 contributor via the Cline API). Off by default.
    # When on, the single-read retry after a slow two-read stage goes to this reader.
    fallback_reader: str = field(
        default_factory=lambda: os.getenv("MUSE_FALLBACK", "none").strip().lower()
    )
    cline_url: str = field(
        default_factory=lambda: (
            os.getenv("CLINE_BASE_URL", "https://api.cline.bot/api/v1").rstrip("/")
            + "/chat/completions"
        )
    )
    cline_model: str = field(
        default_factory=lambda: os.getenv("CLINE_MODEL", "meta/muse-spark-1.3")
    )
    cline_key: str = field(default_factory=lambda: os.getenv("CLINE_API_KEY", ""))
    # Hard limit for one scan job, everything included.
    scan_deadline_s: float = field(
        default_factory=lambda: float(os.getenv("SCAN_DEADLINE_S", "60"))
    )
    # How long the two-read stage may take before the scan falls back to a single read.
    two_read_timeout_s: float = field(
        default_factory=lambda: float(os.getenv("TWO_READ_TIMEOUT_S", "40"))
    )
    job_ttl_s: float = field(default_factory=lambda: float(os.getenv("JOB_TTL_S", "600")))
    sam_timeout_s: float = field(default_factory=lambda: float(os.getenv("SAM_TIMEOUT_S", "8")))
    # Pending team decision: when SAM is down, may a Muse-only read produce a total?
    muse_only_totals: bool = field(default_factory=lambda: _flag("MUSE_ONLY_TOTALS", False))
    # Folder with clean_sheet.jpg and real_sheet.jpg for read B. Kept outside the repo: the real
    # sheet is made from pre-event photos. Missing sheets make read B fail, so no total is spoken.
    refs_dir: str = field(default_factory=lambda: os.getenv("REFS_DIR", "").strip())
    trace_dir: str = field(default_factory=lambda: os.getenv("TRACE_DIR", "traces"))
    # Voice (docs/api.md section 1). The spoken question: Meta Omnilingual ASR (a local service at
    # ASR_URL) hears it and Muse turns the transcript into the intent; Gemini is only the fallback
    # when ASR_URL is not set. With neither, POST /intent answers 501. Answers in Amharic and Oromo
    # come from fixed templates (birr/voice/templates.py) and are spoken by Meta MMS-TTS on the CPU.
    asr_url: str = field(default_factory=lambda: os.getenv("ASR_URL", "").strip().rstrip("/"))
    asr_timeout_s: float = field(default_factory=lambda: float(os.getenv("ASR_TIMEOUT_S", "10")))
    intent_timeout_s: float = field(
        default_factory=lambda: float(os.getenv("INTENT_TIMEOUT_S", "15"))
    )
    # The assistant's Muse turn (POST /assist).
    assist_timeout_s: float = field(
        default_factory=lambda: float(os.getenv("ASSIST_TIMEOUT_S", "15"))
    )
    gemini_key: str = field(default_factory=lambda: os.getenv("GEMINI_API_KEY", ""))
    gemini_base_url: str = field(
        default_factory=lambda: os.getenv(
            "GEMINI_BASE_URL", "https://generativelanguage.googleapis.com/v1beta"
        ).rstrip("/")
    )
    gemini_model: str = field(default_factory=lambda: os.getenv("GEMINI_MODEL", "gemini-3.8-flash"))
    # Optional thinkingConfig.thinkingLevel for the model above. Empty leaves it out.
    gemini_thinking_level: str = field(
        default_factory=lambda: os.getenv("GEMINI_THINKING_LEVEL", "").strip()
    )
    gemini_timeout_s: float = field(
        default_factory=lambda: float(os.getenv("GEMINI_TIMEOUT_S", "15"))
    )
    max_audio_bytes: int = field(
        default_factory=lambda: int(os.getenv("MAX_AUDIO_BYTES", str(3 * 1024 * 1024)))
    )
    # "mms" (Meta MMS-TTS, needs `uv sync --extra tts`) or "off" (text only; the app's phone voice).
    tts_engine: str = field(default_factory=lambda: os.getenv("TTS_ENGINE", "mms").strip().lower())
    # Languages spoken as clips. Amharic only by default: the MMS Oromo voice tested poorly (Hark's
    # ASR check, Oct 31); TTS_LANGS=am,om once a native speaker approves it.
    tts_langs: frozenset[str] = field(
        default_factory=lambda: frozenset(
            x.strip() for x in os.getenv("TTS_LANGS", "am").split(",") if x.strip()
        )
    )
    mms_model_am: str = field(
        default_factory=lambda: os.getenv("MMS_TTS_AM", "facebook/mms-tts-amh")
    )
    mms_model_om: str = field(
        default_factory=lambda: os.getenv("MMS_TTS_OM", "facebook/mms-tts-orm")
    )
    # Speech clips (WAV). Holds backend sentences only, never user audio.
    voice_cache_dir: str = field(
        default_factory=lambda: os.getenv("VOICE_CACHE_DIR", "voice_cache")
    )


def get_settings() -> Settings:
    return Settings()
