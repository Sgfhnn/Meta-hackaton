# Birr cash assistant

A voice-first assistant that helps blind and low-vision people handle Ethiopian cash. Ask "how much do I have?" or "is my change right?". It segments every note with SAM 3.1, reads each denomination with Muse Spark Open, adds the total in code, and answers in Amharic and English. When it is unsure, it asks for a rescan instead of guessing.

Built during the Meta Global AI Developer Hackathon (Oct 26 – Nov 4, 2026). See `docs/architecture.md`.

## Backend

FastAPI service for the app, built to the contract in `docs/api.md`.

```bash
cp .env.example .env        # fill in BASETEN_API_KEY and ROBOFLOW_API_KEY locally
uv sync
set -a; . ./.env; set +a
uv run uvicorn birr.api:app --reload --port 8000
```

- `POST /scan`: multipart `image` (JPEG), `intent`, `lang`, `paid`, `price`, `attempt`. Returns a `job_id`; poll `GET /scan/{job_id}` for the result. Two Muse reads and SAM run in parallel; a total is spoken only when both reads list the same notes and SAM's count matches, and the total and change are computed in code. Run one uvicorn worker (jobs live in the process).
- `POST /intent`: returns 501 for now. Voice goes through Gemini on the app side.
- `GET /health`: liveness check.

Each call writes one JSON trace to `TRACE_DIR` (no image bytes). Tests mock Muse and SAM, so they need no keys or network: `uv run pytest`.
