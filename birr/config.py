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


def get_settings() -> Settings:
    return Settings()
