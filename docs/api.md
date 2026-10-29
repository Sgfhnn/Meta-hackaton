# Scan API contract

This is the contract between the Expo app and the backend. Both sides build against it in parallel. Changing it requires a PR.

Scope: birr notes of 5, 10, 50, 100 and 200 (the denominations in the gate labels). Any other note comes back as `unclear`.

**Who does what:** Muse Spark Open reads every note. Gemini only transcribes the user's speech and speaks the answers (Amharic, Oromo, English); it never reads notes or computes totals. SAM finds and locates notes: the live app uses Roboflow's hosted SAM 3, while the gate runs SAM 3.1 on Kaggle. They are not identical, so hint positions proven on one must be re-checked on the other.

## Core rules

1. **The backend computes totals and change in code**, from the per-note reads. The model never states a total.
2. **A total is only spoken when we're sure.** That means: two independent Muse reads of the photo list the same notes (the same multiset of denominations, order ignored), SAM's note count equals that note count, no note is `partial` or `unclear`, and every denomination is in scope. Otherwise the outcome is `guide` or `rescan`, and `total` is `null`. There is no exception: the slow-scan retry in §2.1 uses a single read and never speaks a total.
3. **No images are stored.** The backend keeps only the trace (§4). The app strips EXIF metadata, including GPS location, before uploading.

## 1. `POST /intent`: what the user asked

The user taps and speaks. Gemini transcribes the audio and extracts the intent.

**Request:** `multipart/form-data`
| Field | Type | Notes |
|---|---|---|
| `audio` | file | m4a or wav, ≤ 10 s |

**Response 200**
```json
{
  "intent": "count",
  "lang": "am",
  "paid": null,
  "price": null,
  "speech": {"am": "...", "en": "Spread your notes and hold the phone over them."}
}
```
- `intent`: `count` or `change`.
- `lang`: `am`, `om` or `en`, matching the language the user spoke in. `speech` carries the same three keys.
- `paid` and `price`: whole birr, only for `change`. If either is missing, `speech` asks for it, and the app records again.

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
| `speech` | The text the app speaks (Gemini TTS). The backend writes it, and the app speaks it word for word. |
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
| 502 | `upstream_error`: every Muse read failed (as the `error` of a job, or directly with `wait=true`). SAM failing alone is not an error: the outcome is `rescan` |

A scan that runs past the 60 s limit is not an error: it ends as `outcome: "rescan"` (§2.1).

## 4. Trace

Each `/scan` and `/intent` call writes one JSON trace, keyed by `trace_id`. It records the inputs (minus image and audio), each Muse read (reader, labels or error, ms), whether the scan used two reads or the single-read retry and why, SAM's raw and kept counts with its timing, the stage timings, per-note reads, filter decisions, the outcome, and the speech text. Traces show judges the agent loop. They contain no images, audio or personal data.

## 5. App behaviour

- **On tap:** play a short audio cue within 1 s, before any network call.
- **While waiting:** poll `GET /scan/{job_id}` every `poll_after_ms` and play a soft tick every 2 s, so silence never means "broken". After about 10 s, speak the pending `speech` ("Still counting.") once.
- **`total`:** speak the `speech` text in the user's language.
- **`guide`:** speak the hint, then capture again with `attempt` + 1.
- **`rescan`:** speak the prompt, then capture again. After `max_attempts`, say that it can't count these notes, and stop.
