# Handoff: birr cash assistant (Oct 30, 2026)

From Claude to Hark. Read this alongside Slack #meta-hackathon, which may have newer news. Box URLs and keys live in Slack and on the box, never in this repo.

## 1. Open PRs and merge order

| PR | What | Status |
|---|---|---|
| #13 | App: count a saved photo (Hark) | Approve. Merge first. |
| #16 | App: Birr logo, ask by voice, change check, Amharic answers | Built on #13. Merge after it. CI green. |
| #10 | Scan v2 + lab (Hark) | Already contained in #15. Merge it first if you want it under its own PR, or close it once #15 merges. |
| #15 | Backend: SAM provider switch, SAM 3.1 on Modal, Gemini voice, docs | Built on `hark/reader-2048` (`c9af833`) plus `main`. CI green, 144 tests. |
| #14 | Reader prompt v3.1 (Muse) → `hark/reader-2048` | Review posted: report how many totals it speaks (not only "zero wrong"), and keep the Ge'ez glyphs. After it merges, merge `hark/reader-2048` into `claude/sam-providers` so #15 carries v3.1. |
| #2, #6, #8, #9 | Early harness, eval matrix, knowledge pack, old prompt | Reviews posted: superseded, suggest closing. #8 could stay with a status note. |

The two final PRs, #15 and #16, merge into each other without conflicts in either order.

## 2. What #15 and #16 add

**Backend (#15).** The contract is `docs/api.md`.
- `SAM_PROVIDER` is `roboflow` (default), `modal` or `off`, and `SAM_OFF=1` still means off. `/health` shows which one is in use.
- `modal_sam/` is SAM 3.1 (default) or SAM 3 on Modal, behind a Modal access-token pair. Steps are in `modal_sam/README.md`. **Never deployed.** SAM 3.1 has no official recipe for one still photo, so the photo runs as a one-frame video. Compare it with SAM 3 before choosing.
- `POST /intent` (Gemini) returns `intent` (`count`, `change` or `unknown`), `next` (`scan`, `ask` or `done`), `lang`, `paid` and `price`. No audio or transcript is kept.
- Answers are translated into Amharic and Oromo once per phrase and cached. **A translation that drops or changes a number is thrown away**, and the user hears English.
- `speech_audio` links to `GET /speak/{id}`: an Amharic clip made before the answer returns, for backend-written text only. `GET /phrases?lang=am` returns the app's prompts, translated, with clips.
- Oromo voice is off by default, because Gemini's TTS list has no Oromo: `GEMINI_TTS_LANGS=am,om` turns it on. Without `GEMINI_API_KEY`, everything stays English and `/intent` answers 501.
- From the PR review: the lab token is compared in constant time, and uploads are read only up to their size limit.

**App (#16).**
- The logo is used everywhere. `app/assets/logo.svg` is the source; `tools/logo/` rebuilds it.
- To ask by voice, hold the screen, speak and let go. Or tap **Ask**, speak and tap again; this path works with TalkBack.
- After "I paid 500, the price is 320", the next tap scans the change.
- Amharic answers play the backend's clips, with a fallback to the phone's voice after 5 s. Prompts come from `/phrases` and are kept offline. The app switches to the language the user spoke.

## 3. Turning it on (live box)

After merging #15:
1. Keep the current live settings (`SAM_OFF=1`, `MUSE_ONLY_TOTALS=1`, the reference sheets in `REFS_DIR`). Run one uvicorn worker.
2. For voice, **Anu adds `GEMINI_API_KEY` to the box's `.env`. It never goes into chat.** The defaults are fine: `GEMINI_MODEL=gemini-3.8-flash`, `GEMINI_TTS_MODEL=gemini-3.8-flash-tts`, `GEMINI_TTS_LANGS=am`.
3. `VOICE_CACHE_DIR` (default `voice_cache/`) must be writable and survive restarts. It holds the translations, and wording can be fixed by editing `translations.am.json` there, plus the clips.
4. Restart, then check `GET /health`: it should show `"voice": {"gemini": true, "speaks": ["am"]}`. The first start translates 24 fixed phrases (2 calls) and makes about 24 Amharic clips, in the background. That takes a minute or two and costs a few cents.
5. For the app, after pulling #16, run `cd app && npm install` (new: `expo-audio`, `expo-splash-screen`). Restart Expo with `--clear`, with `EXPO_PUBLIC_API_URL` pointing at the box.

## 4. First live checks, in order

1. **Real Gemini.** Ask "ስንት ብር አለኝ?" and "I paid 500 for 320" in Amharic and in English. Check `intent`, `next` and the amounts, and read the `/intent` traces.
2. **Amharic wording and voice.** Anu listens to the clips. Fix the wording in `translations.am.json`, or hand the fixes to us.
3. **Phone.** Try hold-to-talk, Ask with TalkBack on, the change check, and the offline prompt (airplane mode should play the Amharic "cannot reach the server" clip).
4. **Oromo.** A native speaker decides whether Gemini's Oromo voice is acceptable. If it is, set `GEMINI_TTS_LANGS=am,om`.
5. **Prompt v3.1 (#14).** Get its coverage numbers on the locked 20 before it goes live.
6. **SAM, if the team still wants to test it** (as Muse proposed): use `SAM_PROVIDER=roboflow` with `SAM_ADVISORY=1`, so SAM's count is logged without blocking a total. Or deploy Modal and compare on the dev set with `tools/experiments/run_sam.py`; it follows `SAM_PROVIDER` and `SAM_MODAL_*`.

## 5. Not verified yet

- Real Gemini. All voice tests used a fake Gemini, including the end-to-end run in `tools/e2e/`.
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

- Backend: `birr/` (`scan.py`, `read/`, `segment/`, `voice/gemini.py`, `voice/service.py`, `voice/speech.py`, `lab.py`). The SAM service is in `modal_sam/`, the app in `app/`, the contract in `docs/api.md`, and scripts in `tools/` (see `tools/README.md`).
- Outside the repo: the reference sheets (`REFS_DIR` on the box), the dev and locked photos (Anu's Drive, link in Slack), and the lab data (`LAB_DIR`, behind the `/lab` endpoints with `LAB_TOKEN`).

## 8. Decisions on record

- The backend is hosted on instabox. Modal is only for the optional SAM service.
- Tests run on Muse Spark 1.3 (contributor tier). The real demo runs on Muse Spark Open on Baseten (standard tier).
- SAM is off live (Anu's call) and stays switchable while the team tests it.
- Respect the spend caps. No big batch runs without Anu's OK.
