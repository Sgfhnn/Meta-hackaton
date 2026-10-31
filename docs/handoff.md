# Handoff: birr cash assistant (Oct 30, 2026)

From Claude to Hark. Read this alongside Slack #meta-hackathon, which may have newer news. Box URLs and keys live in Slack and on the box, never in this repo.

## 1. Open PRs and merge order

| PR | What | Status |
|---|---|---|
| #13 | App: count a saved photo (Hark) | Approve. Merge first. |
| #16 | App: Birr logo, ask by voice, change check, Amharic answers | Built on #13. Merge after it. CI green. |
| #10 | Scan v2 + lab (Hark) | Already contained in #15. Merge it first if you want it under its own PR, or close it once #15 merges. |
| #15 | Backend: SAM provider switch, SAM 3.1 on Modal, voice (Gemini hears, Meta MMS speaks), docs | Built on `hark/reader-2048` (`c9af833`) plus `main`. CI green, 179 tests. |
| #14 | Reader prompt v3.1 (Muse) → `hark/reader-2048` | Review posted: report how many totals it speaks (not only "zero wrong"), and keep the Ge'ez glyphs. After it merges, merge `hark/reader-2048` into `claude/sam-providers` so #15 carries v3.1. |
| #2, #6, #8, #9 | Early harness, eval matrix, knowledge pack, old prompt | Reviews posted: superseded, suggest closing. #8 could stay with a status note. |

The two final PRs, #15 and #16, merge into each other without conflicts in either order.

## 2. What #15 and #16 add

**Backend (#15).** The contract is `docs/api.md`.
- `SAM_PROVIDER` is `roboflow` (default), `modal` or `off`, and `SAM_OFF=1` still means off. `/health` shows which one is in use.
- `modal_sam/` is SAM 3.1 (default) or SAM 3 on Modal, behind a Modal access-token pair. Steps are in `modal_sam/README.md`. **Never deployed.** SAM 3.1 has no official recipe for one still photo, so the photo runs as a one-frame video. Compare it with SAM 3 before choosing.
- `POST /intent` (Gemini) returns `intent` (`count`, `change` or `unknown`), `next` (`scan`, `ask` or `done`), `lang`, `paid` and `price`. No audio or transcript is kept.
- Answers in Amharic and Oromo come from **fixed templates** (`birr/voice/templates.py`, drafts for Anu to correct), filled in by code. **No model translates, and every number is written by code**: digits on screen, words in the voice (350 → ሦስት መቶ ሃምሳ).
- `speech_audio` links to `GET /speak/{id}`: a clip from **Meta MMS-TTS** (`facebook/mms-tts-amh`, `facebook/mms-tts-orm`, CPU, no quota), made before the answer returns, for backend-written text only. `GET /phrases?lang=am` returns the app's prompts with clips.
- Gemini TTS was dropped (10 requests a day on our plan). Gemini now only hears the question; without `GEMINI_API_KEY`, `/intent` answers 501 and everything else still works, including Amharic and Oromo.
- From the PR review: the lab token is compared in constant time, and uploads are read only up to their size limit.

**App (#16).**
- The logo is used everywhere. `app/assets/logo.svg` is the source; `tools/logo/` rebuilds it.
- To ask by voice, hold the screen, speak and let go. Or tap **Ask**, speak and tap again; this path works with TalkBack.
- After "I paid 500, the price is 320", the next tap scans the change.
- Amharic answers play the backend's clips, with a fallback to the phone's voice after 5 s. Prompts come from `/phrases` and are kept offline. The app switches to the language the user spoke.

## 3. Turning it on (live box)

After merging #15:
1. Keep the current live settings (`SAM_OFF=1`, `MUSE_ONLY_TOTALS=1`, the reference sheets in `REFS_DIR`). Run one uvicorn worker.
2. For voice: install MMS with `uv sync --extra tts` (CPU PyTorch, transformers and uroman, about 1 GB), and start the server with `uv run --extra tts uvicorn birr.api:app --port 8000` so later syncs keep it. For voice questions, **Anu adds `GEMINI_API_KEY` to the box's `.env`. It never goes into chat.**
3. `VOICE_CACHE_DIR` (default `voice_cache/`) must be writable and survive restarts; it holds the clips. Wording is fixed in `birr/voice/templates.py`.
4. Restart, then check `GET /health`: it should show `"voice": {"intent": true, "translates": true, "tts": "mms", "speaks": ["am", "om"]}`. At startup each voice loads (about 8 s) and the fixed phrases' clips are made in the background (about a minute of CPU). After that: a short sentence about 1 s, a total plus a change check about 3 s.
5. For the app, after pulling #16, run `cd app && npm install` (new: `expo-audio`, `expo-splash-screen`). Restart Expo with `--clear`, with `EXPO_PUBLIC_API_URL` pointing at the box.

## 4. First live checks, in order

1. **Real Gemini.** Ask "ስንት ብር አለኝ?" and "I paid 500 for 320" in Amharic and in English. Check `intent`, `next` and the amounts, and read the `/intent` traces.
2. **Amharic and Oromo wording and voice.** Anu listens to the MMS clips and corrects `birr/voice/templates.py` and the number words in `birr/voice/numbers.py` (the test list in `tests/test_numbers.py` is the checklist).
3. **Phone.** Try hold-to-talk, Ask with TalkBack on, the change check, and the offline prompt (airplane mode should play the Amharic "cannot reach the server" clip).
4. **Oromo.** A native speaker checks the Oromo templates and voice. If they're not good enough yet, set `TTS_LANGS=am`.
5. **Prompt v3.1 (#14).** Get its coverage numbers on the locked 20 before it goes live.
6. **SAM, if the team still wants to test it** (as Muse proposed): use `SAM_PROVIDER=roboflow` with `SAM_ADVISORY=1`, so SAM's count is logged without blocking a total. Or deploy Modal and compare on the dev set with `tools/experiments/run_sam.py`; it follows `SAM_PROVIDER` and `SAM_MODAL_*`. If the one-frame SAM 3.1 route returns too few boxes, add your Kaggle route as a third `SAM_MODEL` in `modal_sam/app.py`: `build_sam3_image_model` loaded with the `sam3.1_multiplex.pt` checkpoint, with bf16 autocast. On a T4 it boxed 8/8 clean notes at 0.97–0.98.

## 5. Not verified yet

- Real Gemini for `/intent`. All voice tests used a fake Gemini, including the end-to-end run in `tools/e2e/`. (MMS was tested for real on CPU.)
- A Modal GPU deploy.
- A real Android phone with TalkBack.
- A native speaker reading the Amharic and Oromo wording.

## 6. Submission checklist (Nov 4, 9 pm ET; team target 8 pm EAT)

- Merge the final PRs, and close the superseded ones.
- Before the repo goes public:
  - no secrets (gitleaks runs in CI);
  - no pre-event photos, reference sheets or results (they live in `REFS_DIR` on the box and in Anu's Drive folder).
- Check the README "Disclosures" section (in #15) against what actually runs on demo day, such as the SAM setting and the languages.
- `docs/licenses.md` lists every model, service, package and the logo font.
- The demo video states what was pre-existing, shows a trace, and asks a question in Amharic.
- Rotate the API keys that were shared in chat for testing.

## 7. Where things are

- Backend: `birr/` (`scan.py`, `read/`, `segment/`, `voice/gemini.py`, `voice/service.py`, `voice/speech.py`, `voice/templates.py`, `voice/localize.py`, `voice/numbers.py`, `voice/mms.py`, `lab.py`). The SAM service is in `modal_sam/`, the app in `app/`, the contract in `docs/api.md`, and scripts in `tools/` (see `tools/README.md`).
- Outside the repo: the reference sheets (`REFS_DIR` on the box), the dev and locked photos (Anu's Drive, link in Slack), and the lab data (`LAB_DIR`, behind the `/lab` endpoints with `LAB_TOKEN`).

## 8. Decisions on record

- Voice: Gemini only hears the question; Meta MMS-TTS speaks; fixed templates replace machine translation (Oct 31). Suggested next: Meta speech recognition (Omnilingual ASR, Apache 2.0, Amharic and Oromo) for `/intent`, so Gemini can go entirely.

- The backend is hosted on instabox. Modal is only for the optional SAM service.
- Tests run on Muse Spark 1.3 (contributor tier). The real demo runs on Muse Spark Open on Baseten (standard tier).
- SAM is off live (Anu's call) and stays switchable while the team tests it.
- Respect the spend caps. No big batch runs without Anu's OK.
