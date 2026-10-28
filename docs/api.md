# Scan API contract

This is the contract between the Expo app and the backend. Both sides build against it in parallel. Changing it requires a PR.

Scope: birr notes of 5, 10, 50, 100 and 200 (the denominations in the gate labels). Any other note comes back as `unclear`.

**Who does what:** Muse Spark Open reads every note. Gemini only transcribes the user's speech and speaks the answers (Amharic, Oromo, English); it never reads notes or computes totals. SAM finds and locates notes: the live app uses Roboflow's hosted SAM 3, while the gate runs SAM 3.1 on Kaggle. They are not identical, so hint positions proven on one must be re-checked on the other.

## Core rules

1. **The backend computes totals and change in code**, from the per-note reads. The model never states a total.
2. **A total is only spoken when we're sure.** That means: SAM's note count equals Muse's note count, no note is `partial` or `unclear`, and every denomination is in scope. Otherwise the outcome is `guide` or `rescan`, and `total` is `null`.
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

**Response 200**
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
| `hint` | For `guide` only: `{"note_index": 1, "position": "near center", "relation": "under_top", "covered_by": 0, "action": "slide_out"}`. `position` is from the user's point of view (near/far, left/right). `relation` is optional: `under_top` or `next_to`. `covered_by` is the index of the note on top, if any. `action` is one of `slide_out`, `lay_flat`, `move_closer` or `more_light`. A hint targets **one note at a time**, the most covered first; the app rescans after each move. |
| `speech` | The text the app speaks (Gemini TTS). The backend writes it, and the app speaks it word for word. |
| `timing_ms` | Latency per stage, for monitoring. |

**When SAM's count and Muse's count disagree:** if SAM found more regions than Muse read, the outcome is `guide` (likely a covered note). If SAM found fewer, the outcome is `rescan`. Fanned notes can over-segment SAM, so the filter (confidence, min-area, overlap dedupe) runs before counting.

**If SAM is unavailable:** the count check can't run, so the outcome is always `rescan`. No total is spoken without the count check.

**Spoken totals:** the app may assemble a total from pre-recorded clips ("you have", the number, "birr") using `total`, and use TTS only for other phrases. `speech` is still always filled in.

## 3. Errors

Any non-200 response carries spoken text, so the user always hears something:
```json
{"error": "upstream_timeout", "speech": {"am": "...", "en": "Sorry, I couldn't check that. Please try again."}}
```
| Status | `error` |
|---|---|
| 400 | `bad_request`: missing field, unsupported file type, or image too large |
| 502 | `upstream_error`: Muse, SAM or TTS failed |
| 504 | `upstream_timeout`: the scan took longer than 20 s |

## 4. Trace

Each `/scan` and `/intent` call writes one JSON trace, keyed by `trace_id`. It records the inputs (minus image and audio), each model call with its timing, per-note reads, filter decisions, the outcome, and the speech text. Traces show judges the agent loop. They contain no images, audio or personal data.

## 5. App behaviour

- **On tap:** play a short audio cue within 1 s, before any network call.
- **While waiting:** play a soft tick every 2 s, so silence never means "broken".
- **`total`:** speak the `speech` text in the user's language.
- **`guide`:** speak the hint, then capture again with `attempt` + 1.
- **`rescan`:** speak the prompt, then capture again. After `max_attempts`, say that it can't count these notes, and stop.
