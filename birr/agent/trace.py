"""One JSON trace per call, keyed by trace_id. Never holds image or audio bytes."""

from __future__ import annotations

import json
import uuid
from pathlib import Path


def new_trace_id() -> str:
    return uuid.uuid4().hex


def write_trace(trace_dir: str, trace_id: str, record: dict) -> None:
    path = Path(trace_dir)
    path.mkdir(parents=True, exist_ok=True)
    (path / f"{trace_id}.json").write_text(json.dumps({"trace_id": trace_id, **record}, indent=2))
