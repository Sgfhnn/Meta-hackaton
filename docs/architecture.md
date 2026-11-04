> **Superseded.** This was the fallback design ("Auditor") from day 1, kept for the record. Birr, the project we built, is described in the main README.

# Birr cash assistant: architecture

Status: **gated spike.** If the Wed Oct 28, 12:00 EAT gate fails, we switch to the AI Application Auditor (see §7).

## 1. What it does

It's a voice-first assistant that helps blind and low-vision people handle Ethiopian cash (2020 series: 10, 50, 100 and 200 birr).

- **"How much do I have?"** The user spreads or fans their notes in front of the camera. The assistant counts each note and speaks the total in Amharic and English.
- **"Is my change right?"** The user says what they paid and the price. The assistant counts the change it sees and says whether the change is right, or how much is missing.

When it isn't sure, it says so and asks the user to rescan. It never guesses an amount. It makes no claims about detecting counterfeit notes.

## 2. Why it isn't a "simple image analyzer"

The photo is one tool call inside an agent loop, not the product:

```
voice question (Amharic/English)
   → intent: count | change-check
   → capture photo / short video
   → SAM 3.1: segment every "banknote"
   → filter: confidence + min-area, overlap dedupe
   → Muse Spark Open: read the denomination of each note crop
   → code: add up the per-note values (the model never states the total)
   → confidence check: any unclear note → ask for a rescan or a confirmation
   → change-check: compare the counted change with the expected change (paid − price)
   → spoken answer + a logged trace of every step
```

The judge-visible proof is a side-by-side run on the same messy pile: Muse alone, which guesses, against our loop, which counts each note exactly or asks for a rescan.

## 3. Components

| Component | Path | Notes |
|---|---|---|
| Segmenter client | `birr/segment/` | `SAM_PROVIDER`: Roboflow's hosted SAM 3 (default), our SAM 3.1 (or SAM 3) endpoint on Modal (`modal_sam/`), or off. The live box runs it off, with two agreeing Muse reads (`MUSE_ONLY_TOTALS`). |
| Note filter | `birr/segment/filter.py` | Confidence threshold, min-area, IoU dedupe. Fragments become "unclear", never notes. |
| Denomination reader | `birr/read/` | Muse Spark Open on Baseten (`meta-models/muse-spark-open-1026`, OpenAI-compatible). Takes one crop and returns `{denomination, confidence}`. |
| Agent loop | `birr/agent/` | Intent → plan → tools → confidence → answer. Every step goes to a JSON trace. |
| Arithmetic | `birr/agent/money.py` | Totals and change are computed in code only. Unit-tested. |
| Voice I/O | `birr/voice/` | Gemini hears the question (`POST /intent`). Answers are written in English in code, put into Amharic and Oromo by fixed templates (numbers written by code), and spoken by Meta MMS-TTS on the CPU (`GET /speak`). |
| Eval harness | `evals/` | A/B test: Muse alone vs SAM 3.1 + Muse. Per-note accuracy, exact totals, gate summary. |

## 4. Gate (Wed Oct 28, 12:00 EAT)

These must all pass on the 20 locked photos, which nobody tunes on:
- At least 18 out of 20 exact totals
- At least 95% per-note denomination accuracy
- SAM 3.1 + Muse gets at least 2 more exact totals than Muse alone
- The fanned-note video counts every note exactly once

Dev photos are kept separate from the locked set. Each arm runs on the locked set once.

## 5. Rules check

- **Public repo, event work only.** This is a fresh repo. No pre-event code or data. The video opens by stating what was pre-existing.
- **No secrets.** Config lives in env vars and `.env.example`. gitleaks runs in CI and pre-commit.
- **Data.** Banknote photos only, with no faces and no personal data. @anu's pre-event photos are dev-only, disclosed, and never committed.
- **Hosting.** Discord says no deployed backend is required and there is no partner-only rule. Muse Spark runs on Baseten, a partner, which keeps the open-weights bonus possible.
- **Unresolved:** whether SAM 3.1 counts toward the open-weights bonus. That question is pending at office hours.

## 6. Owners

| Area | Owner |
|---|---|
| SAM 3.1 runs on Kaggle, Baseten wiring | @hark |
| A/B harness, filter and dedupe | @muse |
| Voice flow and rescan/confirm prompts | @cue |
| Eval matrix, go/no-go report | @hermes |
| Architecture, rules, foundation PR, technical call | @claude |
| Photos, keys, approvals, merges | @anu |

## 7. Fallback: AI Application Auditor

If the gate fails, we build one synthetic incident end to end on Muse Spark Open. The agent reproduces it, correlates logs, code and deploy state, writes a patch, runs the tests, and opens a verified fix PR. No real KennaJobs code or logs.
