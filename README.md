<p align="center"><img src="app/assets/logo.svg" width="112" alt="Birr logo: a yellow banknote shaped like a speech bubble, with ብር (birr) written on it, on deep green"></p>

# Birr cash assistant

A voice-first assistant that helps blind and low-vision people handle Ethiopian cash. Ask "How much do I have?" or "I paid 500 for something that costs 320". Muse Spark Open reads every note, the backend adds the total in code, and the answer is spoken in Amharic, Afaan Oromo or English. When it is unsure, it asks for a rescan instead of guessing.

Built during the Meta Global AI Developer Hackathon (Oct 26 – Nov 4, 2026). The app–backend contract is `docs/api.md`, and the design is `docs/architecture.md`.

## How it works

1. **Ask (optional).** The user holds the screen and speaks. Gemini hears the question and returns the intent: count the money, or check the change (with the amounts paid and the price).
2. **Photo.** A tap photographs the notes. The app caps the photo at 2048 px and strips EXIF.
3. **Two reads.** Two Muse Spark Open reads run in parallel: one plain, and one with reference sheets of every note. A total is spoken only when both list the same notes and none is unclear. Otherwise the user is guided to rescan.
4. **Count check (optional).** SAM counts note regions as a cross-check (`SAM_PROVIDER`, below).
5. **Answer.** The backend computes the total and the change in code. It writes the answer in English and translates it, and a translation that changes any number is thrown away. The app speaks the answer.

## Backend

A FastAPI service, built to `docs/api.md`.

```bash
cp .env.example .env        # fill in the keys locally; .env is never committed
uv sync
set -a; . ./.env; set +a
uv run uvicorn birr.api:app --port 8000   # one worker: scan jobs live in the process
```

- `POST /scan` takes a multipart `image` (JPEG) with `intent`, `lang`, `paid`, `price` and `attempt`. It returns a `job_id`; poll `GET /scan/{job_id}` for the result. Read B also sends two reference sheets, `clean_sheet.jpg` and `real_sheet.jpg`, loaded from `REFS_DIR`. They are kept out of this repo because the real sheet is made from pre-event photos. Without them read B fails and no scan speaks a total (`/health` shows `refs`).
- `POST /intent` takes the spoken question (m4a, wav or webm, about 10 s at most) and returns the intent and the app's next step. Without `GEMINI_API_KEY` it answers `501`, and the app still counts by tap.
- `GET /speak/{clip_id}` returns the clip behind an answer's `speech_audio` link (WAV). It serves only text the backend wrote.
- `GET /phrases?lang=am` returns the app's own prompts, translated, with clip links.
- `GET /health` reports `refs`, the SAM provider, and whether voice is on.

Each `/scan` and `/intent` call writes one JSON trace to `TRACE_DIR`. Traces hold no images, audio or transcripts.

### SAM providers

| `SAM_PROVIDER` | What counts the regions | Needs |
|---|---|---|
| `roboflow` (default) | Roboflow's hosted SAM 3 | `ROBOFLOW_API_KEY` |
| `modal` | our own SAM 3.1 (or SAM 3) endpoint on Modal, in `modal_sam/` | `SAM_MODAL_URL`, `SAM_MODAL_KEY`, `SAM_MODAL_SECRET`. Deploy steps: `modal_sam/README.md` |
| `off` | nothing. Pair it with `MUSE_ONLY_TOTALS=1` so that two agreeing reads can speak a total | — |

`SAM_OFF=1` also means `off`. The live box currently runs `SAM_OFF=1` with `MUSE_ONLY_TOTALS=1`, and SAM stays switchable while the team tests it. `SAM_ADVISORY=1` logs SAM's count without letting it block a total.

### Voice (Gemini)

Set `GEMINI_API_KEY`. The key stays on the backend, and the app never sees it.
- `gemini-3.8-flash` hears the question (with a JSON schema) and translates answers into Amharic and Oromo. Each phrase is translated once and cached in `VOICE_CACHE_DIR`. To fix a wording, edit `translations.<lang>.json` there.
- `gemini-3.8-flash-tts` speaks Amharic. Gemini's TTS list does not include Oromo, so Oromo answers stay text (the app speaks them with a phone voice, or in English) until a native speaker checks the Oromo voice. Then set `GEMINI_TTS_LANGS=am,om`.
- Fixed phrases are translated and voiced at startup, so prompts and errors need no wait.

### Tests

`uv run pytest` runs everything with Muse, SAM, Modal and Gemini mocked, so it needs no keys or network. App checks: see `app/README.md`.

## App

An Expo (React Native) app in `app/`, Android first. Tap anywhere to count; hold the screen, or tap **Ask**, to ask by voice. See `app/README.md` to run it on a phone with Expo Go. It includes a demo mode that needs no backend.

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

## Disclosures

- **Models and services.** Muse Spark Open (Meta) on Baseten reads the notes. Muse Spark 1.3 through the Cline API is an optional fallback reader and is off by default. Gemini (Google) hears questions, translates answers and speaks them. It never reads notes or computes totals. SAM 3 runs on Roboflow, or SAM 3.1 or SAM 3 runs on Modal, both optional. Each provider processes what we send under its own terms.
- **Data.** The backend stores no photos and no recordings, only traces with labels and timings. The app strips EXIF, including GPS. Voice questions go to Gemini to be understood, and neither the audio nor the transcript is kept. The voice cache holds only text the backend wrote and its audio.
- **Pre-event material.** Photos taken before the event were used only for development and testing. They, and the reference sheets made from them, are not in this repo.
- **Translations.** Gemini makes them, and code checks that no number changed. A native speaker has not reviewed the wording yet.
- **Limits.** Birr notes of 5, 10, 50, 100 and 200 only. It does not detect counterfeits.
- **Secrets.** Keys live in environment variables only (`.env.example` lists them).
- **AI assistance.** Parts of this code were written with AI coding assistants.
- **Third-party licenses.** See `docs/licenses.md`.
