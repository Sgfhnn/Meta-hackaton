# Scan API contract

This is the contract between the Expo app and the backend. Both sides build against it in parallel. Changing it requires a PR.

Scope: 2020-series birr notes only (10, 50, 100, 200). Any other note comes back as `unclear`.

## Core rules

1. **The backend computes totals and change in code**, from the per-note reads. The model never states a total.
2. **A total is only spoken when we're sure.** That means: SAM's note count equals Muse's note count, no note is `partial` or `unclear`, and every denomination is in scope. Otherwise the outcome is `guide` or `rescan`, and `total` is `null`.
3. **No images are stored.** The backend keeps only the trace (§4). The app strips EXIF metadata, including GPS location, before uploading.

## 1. `POST /intent`: what the user asked

The user taps and speaks. Muse Spark Open reads the audio.

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
- `lang`: `am` or `en`, matching the language the user spoke in.
- `paid` and `price`: whole birr, only for `change`. If either is missing, `speech` asks for it, and the app records again.

## 2. `POST /scan`: count the notes

**Request:** `multipart/form-data`
| Field | Type | Notes |
|---|---|---|
| `image` | file | JPEG, longest side ≤ 896 px, EXIF stripped |
| `intent` | string | `count` or `change` |
| `lang` | string | `am` or `en` |
| `paid` | int | `change` only |
| `price` | int | `change` only |
| `attempt` | int | starts at 1, then +1 on each rescan |

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
| `hint` | For `guide` only: `{"note_index": 1, "position": "bottom center", "action": "slide_out"}`. `action` is one of `slide_out`, `lay_flat`, `move_closer` or `more_light`. |
| `speech` | The text the app speaks (Gemini TTS). The backend writes it, and the app speaks it word for word. |
| `timing_ms` | Latency per stage, for monitoring. |

**If SAM is unavailable:** the backend still answers using Muse only. It never sends a `guide`. If Muse's read is incomplete, it sends `rescan`. It never says a wrong total.

## 3. Errors

Any non-200 response carries spoken text, so the user always hears something:
```json
{"error": "upstream_timeout", "speech": {"am": "...", "en": "Sorry, I couldn't check that. Please try again."}}
```
| Status | `error` |
|---|---|
| 400 | `bad_request`: missing field, unsupported file type, or image too large |
| 502 | `upstream_error`: Muse, SAM or TTS failed |
| 504 | `upstream_timeout`: the scan took longer than 15 s |

## 4. Trace

Each `/scan` and `/intent` call writes one JSON trace, keyed by `trace_id`. It records the inputs (minus image and audio), each model call with its timing, per-note reads, filter decisions, the outcome, and the speech text. Traces show judges the agent loop. They contain no images, audio or personal data.

## 5. App behaviour

- **On tap:** play a short audio cue within 1 s, before any network call.
- **While waiting:** play a soft tick every 2 s, so silence never means "broken".
- **`total`:** speak the `speech` text in the user's language.
- **`guide`:** speak the hint, then capture again with `attempt` + 1.
- **`rescan`:** speak the prompt, then capture again. After `attempt` 3, say that it can't count these notes, and stop.
