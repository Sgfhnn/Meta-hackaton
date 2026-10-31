# Scan API contract

This is the contract between the Expo app and the backend. Both sides build against it in parallel. Changing it requires a PR.

Scope: birr notes of 5, 10, 50, 100 and 200 (the denominations in the gate labels). Any other note comes back as `unclear`.

**Who does what:** Muse Spark Open reads every note. Meta Omnilingual ASR hears the user's question and Muse turns it into the intent (`POST /intent`; Gemini only as a fallback). No model computes totals. Answers in Amharic and Oromo come from fixed templates and are spoken by Meta MMS-TTS. SAM finds and locates notes. `SAM_PROVIDER` picks Roboflow's hosted SAM 3 (`roboflow`, the default), our SAM 3.1 endpoint on Modal (`modal`, see `modal_sam/README.md`), or no SAM (`off`, which `SAM_OFF=1` also sets). They are not identical, so hint positions proven on one must be re-checked on the other. `GET /health` reports the provider in use.

## Core rules

1. **The backend computes totals and change in code**, from the per-note reads. The model never states a total.
2. **A total is only spoken when we're sure.** That means: two independent Muse reads of the photo list the same notes (the same multiset of denominations, order ignored), SAM's note count equals that note count, no note is `partial` or `unclear`, and every denomination is in scope. Otherwise the outcome is `guide` or `rescan`, and `total` is `null`. There is no exception: the slow-scan retry in §2.1 uses a single read and never speaks a total.
3. **No images or recordings are stored.** The backend keeps only the trace (§4). The app strips EXIF metadata, including GPS location, before uploading. Voice questions are transcribed on our own server (Omnilingual ASR), and neither the audio nor the transcript is kept.

## 1. `POST /intent`: what the user asked

The user holds the screen (or taps Ask) and speaks. **Meta Omnilingual ASR** (`omniASR_CTC_300M_v2`, a local service on the box, §1.2) writes down what was said, and **Muse Spark Open** turns that transcript into the intent and amounts. Without `ASR_URL`, Gemini does both as a fallback; with neither, the endpoint answers 501. Neither the audio nor the transcript is stored.

**Request:** `multipart/form-data`
| Field | Type | Notes |
|---|---|---|
| `audio` | file | m4a (AAC), wav, webm, mp3, ogg or flac, about 10 s at most (`MAX_AUDIO_BYTES`, default 3 MB) |
| `lang` | string | optional: the app's current language (`am`, `om` or `en`), passed to the recogniser and used when the language can't be told |

**Response 200**
```json
{
  "intent": "change",
  "next": "scan",
  "lang": "am",
  "paid": 500,
  "price": 320,
  "speech": {"en": "You paid 500 birr for 320 birr. Your change should be 180 birr. Spread it out, hold the phone over it and tap the screen.", "am": "..."},
  "speech_audio": "/speak/3f1c…",
  "trace_id": "9a0e…"
}
```
- `intent`: `count`, `change`, or `unknown` when the question was not understood.
- `next`: what the app does now. `scan` means the next tap scans with this intent (and `paid`/`price` for a change check). `ask` means speak `speech` and let the user ask again: the question was not understood, an amount is missing, or the price is more than what was paid. `done` means nothing to scan: they paid exactly the price.
- `lang`: the language the user spoke (`am`, `om` or `en`). The app answers in it.
- `paid` and `price`: whole birr, only for `change`; `null` when not said. The model is told never to guess an amount, code checks them, and the answer reads them back to the user before any scan.
- When the recogniser hears nothing, the answer is `intent: "unknown"`, `next: "ask"` with "Sorry, I couldn't hear that".
- `speech`, `speech_audio`, `speech_todo`: see §1.1.

**Errors:** `400 bad_request` (no audio, not audio, or too large), `501 not_implemented` (neither `ASR_URL` nor `GEMINI_API_KEY` set; the app falls back to tap-to-count), `502 upstream_error` (the recogniser, Muse or Gemini failed or timed out). Each carries `speech`, as in §3.

### 1.1 Speech in the user's language

Every answer, error and poll carries `speech`: a dict with `en` and, for `lang` `am` or `om`, that language. The backend writes the English text in code. The Amharic and Oromo text comes from **fixed templates** (`birr/voice/templates.py`), filled in by code (`birr/voice/localize.py`). **No model translates anything**, so nothing can change an amount.

- **Numbers come from code.** On screen, amounts are digits. For the voice, they are words written by `birr/voice/numbers.py` (350 → ሦስት መቶ ሃምሳ), because the voice model reads no digits. A sentence the templates don't recognise, or whose numbers don't add up, stays English.
- **`speech_todo`** is set when `speech[lang]` holds English because no template covers that sentence. The app then speaks the English text with an English voice.
- **`speech_audio`** links a clip of `speech[lang]` that already exists, so the app can play it at once. The clips come from **Meta MMS-TTS** (`facebook/mms-tts-amh`, `facebook/mms-tts-orm`) on the backend's CPU (`TTS_ENGINE=mms`, the `tts` extra; `TTS_LANGS`, default `am`: the MMS Oromo voice tested poorly, so Oromo answers stay text until a native speaker approves it). It's left out when MMS is off, or when a clip can't be made; the app then uses the phone's voice.
- **`GET /speak/{clip_id}`** returns the clip (`audio/wav`, 16 kHz mono, cacheable). It serves only text the backend itself wrote, so it can't be used to speak arbitrary text. An unknown id answers `404`, and an MMS failure answers `502`.
- **`GET /phrases?lang=am`** returns the app's own prompts (keys like `counting`, `noNetwork`) as `{"lang": "am", "phrases": {"counting": {"text": "...", "audio": "/speak/…"}}}`, with `audio` `null` where there is no clip. The app downloads the clips so they play offline. The English texts live in `birr/voice/speech.py` (`APP_PHRASES`) and must match `app/src/voice.ts` (`PROMPTS`).
- The fixed phrases' clips are made at startup. The templates are drafts: a native speaker checks them, and the wording is fixed by editing `birr/voice/templates.py`.

### 1.2 The speech-recognition service (internal)

Meta Omnilingual ASR needs an older PyTorch than MMS, so it runs as its own small service on the box, in its own Python environment (`asr_service/`). It listens on `127.0.0.1` only; the app never calls it. The backend calls it with `ASR_URL`.

- `POST /transcribe?lang=amh_Ethi|orm_Latn|eng_Latn`. The body is the audio exactly as the app uploaded it (m4a/AAC from phones, webm/opus from the web preview, or wav), with that `Content-Type`. The service decodes it to 16 kHz mono and rejects clips over 30 s. It answers `{"text": "<transcript>", "lang": "amh_Ethi", "ms": 612}`, `400` for unreadable audio, `500` for a model error.
- `GET /health` answers `{"ok": true, "model": "omniASR_CTC_300M_v2"}`.
- Measured on the box (4 vCPU, no GPU): 1.5 s to load (cached), about 1.8 GB RAM, about 0.6–0.8 s for a 4-second question.

## 2. `POST /scan`: count the notes

A scan can take from a few seconds to a minute (Baseten latency varies a lot), so `/scan` is a job: `POST /scan` checks the request and returns a `job_id` at once, and the app polls `GET /scan/{job_id}` until the status is `done` or `error`. While it is `pending`, the app plays its tick and may speak `speech` ("Still counting.").

**Request:** `multipart/form-data`
| Field | Type | Notes |
|---|---|---|
| `image` | file | JPEG, EXIF stripped. Longest side is a parameter (`IMAGE_MAX_PX`, default 768) until the p50/p90 latency run settles it |
| `intent` | string | `count` or `change` |
| `lang` | string | `am`, `om` or `en` |
| `paid` | int | `change` only |
| `price` | int | `change` only |
| `attempt` | int | starts at 1, then +1 on each rescan |
| `max_attempts` | int | optional. App default 3. The gate run uses 2 (one rescan), matching gate v2 |
| `wait` | bool | optional, default `false`. `true` runs the scan inside the request and returns the result body below directly (for eval scripts and curl; the app should poll) |

**Response 202** (job started)
```json
{"job_id": "b7e2…", "status": "pending", "poll_url": "/scan/b7e2…", "poll_after_ms": 1500, "trace_id": "b7e2…"}
```
`job_id` is the scan's `trace_id`. Bad requests (missing field, not JPEG, change without a price) still answer `400` at once, with no job.

### `GET /scan/{job_id}`: poll the job

```json
{"job_id": "b7e2…", "status": "pending", "elapsed_ms": 9100, "result": null, "poll_after_ms": 1500, "speech": {"en": "Still counting."}}
{"job_id": "b7e2…", "status": "done", "elapsed_ms": 14200, "result": { …the scan result below… }}
{"job_id": "b7e2…", "status": "error", "elapsed_ms": 3000, "result": null, "error": "upstream_error", "speech": {"en": "Sorry, I couldn't check that. Please try again."}, "trace_id": "b7e2…"}
```
| `status` | Meaning |
|---|---|
| `pending` | Still counting. Poll again after `poll_after_ms`. |
| `done` | `result` holds the scan result (the body below). Its `outcome` may still be `guide` or `rescan`. |
| `error` | Every Muse read failed. Speak `speech` and let the user try again. |

An unknown or expired `job_id` (finished jobs are kept `JOB_TTL_S`, default 10 min) answers `404` with `error: "not_found"` and `speech`. Jobs live in the backend process, so it runs as **one** uvicorn worker.

### 2.1 How a scan runs

1. SAM and two Muse reads (`MUSE_READS=2`, `reasoning_effort` low) start in parallel on the same resized photo.
2. **Two-read path.** If both reads are back within `TWO_READ_TIMEOUT_S` (default 40 s), the decision uses both: a total needs the two reads to list the same notes **and** SAM's count to match.
3. **Single-read retry.** If a read is slow or fails, the scan retries once with a single read: it uses a read that already came back, or else starts one more read (on the fallback reader when `MUSE_FALLBACK=cline`) and takes the first read that finishes. A single read **never** gives a total (single read + SAM spoke wrong totals in Claude's Oct 29 tests). It ends as `guide` when SAM's count differs, else `rescan`.
   **SAM off** (`SAM_OFF=1` or `SAM_PROVIDER=off`): a single read can never speak a total there, so steps 2-3 change. The scan waits for both reads until `SCAN_DEADLINE_S` (default 60 s) instead of dropping the slower one at `TWO_READ_TIMEOUT_S`. A read that errors is replaced once (same slot, same prompt). No third read is started. If a replaced read fails again the outcome is `rescan`; past the deadline it is `rescan`. The trace records this under `wait` (`replaced` slots, and `ended` = `deadline` or `read_failed_twice`).
4. **Hard limit.** The whole scan stops at `SCAN_DEADLINE_S` (default 60 s). If no read is back by then, the job finishes as `done` with `outcome: "rescan"` and a "that took too long" prompt, not an error, so the app's rescan loop carries on. SAM not back by then counts as SAM unavailable.

**Scan result** (`result` of a `done` job, or the direct response with `wait=true`)
```json
{
  "outcome": "total",
  "total": 350,
  "change": null,
  "notes": [
    {"denomination": 200, "confidence": 0.97, "box": [0.12, 0.30, 0.40, 0.22], "status": "read"},
    {"denomination": 100, "confidence": 0.95, "box": [0.55, 0.28, 0.38, 0.21], "status": "read"},
    {"denomination": 50,  "confidence": 0.93, "box": [0.20, 0.62, 0.37, 0.20], "status": "read"}
  ],
  "hint": null,
  "speech": {"am": "...", "en": "You have 350 birr: one 200, one 100 and one 50."},
  "trace_id": "b7e2…",
  "timing_ms": {"muse": 4100, "sam": 1900, "total": 4300}
}
```

| Field | Meaning |
|---|---|
| `outcome` | `total`: confident answer. `guide`: SAM found a covered or cut-off note, and `hint` says which one to move. `rescan`: no usable answer, so try again. |
| `total` | Sum of `notes[].denomination` in birr. `null` unless `outcome` is `total`. |
| `change` | For `change` intent with outcome `total`: `{"expected": paid - price, "counted": total, "difference": total - expected}`. `difference < 0` means the user was short-changed. Otherwise `null`. |
| `notes[].status` | `read` (counted), `partial` (covered or cut off, so it triggers `guide`), or `unclear` (unreadable or out of scope, so it triggers `rescan`). |
| `notes[].box` | `[x, y, w, h]`, normalized 0–1, top-left origin. |
| `notes[].denomination` | One of 5, 10, 50, 100, 200, or `null` when not read. |
| `notes[].confidence`, `notes[].box` | May be `null`: the per-photo Muse read gives neither. SAM fills `box` for the note a hint targets. |
| `hint` | For `guide` only: `{"note_index": 1, "position": "near center", "relation": "under_top", "covered_by": 0, "action": "slide_out"}`. `position` is from the user's point of view (near/far, left/right). `relation` is optional: `under_top` or `next_to`. `covered_by` is the index of the note on top, if any. `action` is one of `slide_out`, `lay_flat`, `move_closer` or `more_light`. A hint targets **one note at a time**, the most covered first; the app rescans after each move. |
| `speech` | The text the app speaks, word for word: English from code, Amharic and Oromo from templates (§1.1). With `speech_audio`, a ready MMS clip of it. |
| `timing_ms` | Latency per stage, for monitoring: `muse` (the whole read stage, retry included), `sam` and `total`. The trace has the full breakdown: each read's ms, the two-read stage, the retry and SAM. |

**When the two reads disagree** (different notes or a different number of notes): the outcome is `rescan`, unless both reads agree on the count and SAM's count differs, which is `guide` as below.

**When SAM's count and Muse's count disagree:** if SAM found more regions than Muse read, the outcome is `guide` (likely a covered note). If SAM found fewer (likely two notes merged into one region), the outcome is `guide` with `action: "lay_flat"` (spread the notes apart); `note_index` may point at the largest region. Fanned notes can over-segment SAM, so the filter (confidence, min-area, overlap dedupe) runs before counting.

**If SAM is unavailable:** the count check can't run, so the outcome is `rescan`. A `MUSE_ONLY_TOTALS` flag may allow a Muse-only total when two reads agree and every note reads as valid (never on a single read), but it defaults to **off**: dev showed 0 wrong totals on only 8 photos, which is too small to drop the cross-check for blind users.

**Spoken totals:** the app may assemble a total from pre-recorded clips ("you have", the number, "birr") using `total`, and use TTS only for other phrases. `speech` is still always filled in.

## 3. Errors

Any non-200 response (and any `error` job) carries spoken text, so the user always hears something:
```json
{"error": "upstream_timeout", "speech": {"am": "...", "en": "Sorry, I couldn't check that. Please try again."}}
```
| Status | `error` |
|---|---|
| 400 | `bad_request`: missing field, unsupported file type, or image too large |
| 404 | `not_found`: unknown or expired `job_id` on `GET /scan/{job_id}` |
| 404 | `not_found` on `GET /speak/{clip_id}`: a clip id this backend never handed out |
| 501 | `not_implemented`: `POST /intent` with neither `ASR_URL` nor `GEMINI_API_KEY` |
| 502 | `upstream_error`: every Muse read failed (as the `error` of a job, or directly with `wait=true`), or the recogniser, Muse or Gemini failed on `/intent`, or MMS failed on `/speak`. SAM failing alone is not an error: the outcome is `rescan` |

A scan that runs past the 60 s limit is not an error: it ends as `outcome: "rescan"` (§2.1).

## 4. Trace

Each `/scan` and `/intent` call writes one JSON trace, keyed by `trace_id`. It records the inputs (minus image and audio; for `/intent`, the audio's size and type, the heard intent, amounts and next step, never the transcript), each Muse read (reader, labels or error, ms), whether the scan used two reads or the single-read retry and why, SAM's raw and kept counts with its timing, the stage timings, per-note reads, filter decisions, the outcome, and the speech text. Traces show judges the agent loop. They contain no images, audio or personal data.

## 5. App behaviour

- **On tap:** play a short audio cue within 1 s, before any network call.
- **While waiting:** poll `GET /scan/{job_id}` every `poll_after_ms` and play a soft tick every 2 s, so silence never means "broken". After about 10 s, speak the pending `speech` ("Still counting.") once.
- **`total`:** speak the `speech` text in the user's language.
- **`guide`:** speak the hint, then capture again with `attempt` + 1.
- **`rescan`:** speak the prompt, then capture again. After `max_attempts`, say that it can't count these notes, and stop.
- **Voice question:** hold the screen (or tap Ask) to record, with a strong vibration at the start and nothing spoken while recording. Send it to `POST /intent`, speak `speech`, and follow `next`. After a `change` intent with `next: "scan"`, the next tap scans with `intent=change`, `paid` and `price`.
- **Speaking:** play `speech_audio` when present. Otherwise speak `speech[lang]` with a phone voice for that language, or `speech.en` (always `speech.en` when `speech_todo` is set).

## 6. `GET /health`

```json
{"ok": true, "refs": true, "sam": "off",
 "voice": {"hears": "omnilingual", "intent": true, "translates": true, "tts": "mms", "speaks": ["am"]}}
```
`refs`: read B's reference sheets are loaded (without them no scan speaks a total). `sam`: the SAM provider (`roboflow`, `modal` or `off`). `voice.hears`: what hears voice questions (`omnilingual`, `gemini` or `off`); `voice.intent`: `POST /intent` works. `voice.translates`: answers come in Amharic and Oromo (templates, always on). `voice.tts`: `mms` or `off`. `voice.speaks`: the languages answered with clips.
