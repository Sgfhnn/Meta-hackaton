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

- `POST /scan`: multipart `image` (JPEG), `intent`, `lang`, `paid`, `price`, `attempt`. Muse and SAM run in parallel; the total and change are computed in code.
- `POST /intent`: returns 501 for now. Voice goes through Gemini on the app side.
- `GET /health`: liveness check.

Each call writes one JSON trace to `TRACE_DIR` (no image bytes). Tests mock Muse and SAM, so they need no keys or network: `uv run pytest`.

## App

Expo (React Native) app in `app/`, Android first: tap anywhere, the phone photographs the notes, and the answer from `/scan` is spoken. See `app/README.md` to run it on a phone with Expo Go, including a demo mode that needs no backend.

## What we tried

Our design rule is zero wrong spoken totals. A blind user cannot check a wrong number, so when the reader is not sure, the app asks for a rescan rather than guess. Every experiment below was judged against that rule first and exact reads second.

### Our own note detector (Oct 30)

We trained a YOLOv8s and a DETR note detector, plus a DINOv2 note reader, on free Kaggle GPUs, as a second opinion beside Muse. On real piles of notes YOLO got 3 of 29 totals exact, and as a cross-check it would have vetoed 21 of the 24 piles that Muse read correctly. It was not integrated.

### Fine-tuning Muse Glimmer 30B

We fine-tuned Meta's Muse Glimmer 30B with LoRA (rank 16, 4-bit) on a free Kaggle 2x T4.

- **v1.** 914 rows, 229 steps, final loss 0.063. On 8 held-out piles it got 5 exact and 3 wrong totals (a 100 read as a 5 twice, and a 200 missed). The cause was the labels. Every training note was labelled as read, so the model learned to guess on notes that can only be told apart by colour.
- **v2.** Continued training on 400 hard piles, with colour-only notes relabelled `unclear`. On 24 held-out piles it got 8 exact, asked for a rescan on 15, and gave 1 wrong total (a dropped 200).

One wrong total fails the zero-wrong rule, so Muse Spark Open (`muse-spark-open-1026`) stays the only reader in the app.

**Future work.** Add a per-pile note count to the training target, so a dropped note shows up as a count mismatch and becomes a rescan instead of a wrong total.
