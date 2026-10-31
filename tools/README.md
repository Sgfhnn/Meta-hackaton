# Tools

Scripts used during the build, kept so the runs can be repeated. They are not part of the backend or the app, and `ruff` skips this folder. Photos, reference sheets and results stay out of the repo, because the photos are pre-event material. Every script takes their paths as arguments. Keys come from environment variables or a key file passed as an argument, and no script prints or stores a key.

## `e2e/`: end-to-end checks (no real keys)

**`fake_upstream_voice.py` + `integration_voice.js`** test the app's web build, a local backend, and a fake Muse and Gemini. Chromium fakes the camera and microphone. The flow: tap Ask, speak, tap again. The fake Gemini hears "paid 500, price 320" in Amharic. A tap then runs the change scan, and the answer ("30 birr short") must come back translated, with clips played.

```bash
python3 tools/e2e/fake_upstream_voice.py &          # fake Baseten + Gemini on :8300
(cd app && EXPO_PUBLIC_API_URL=http://localhost:8000 npx expo export --platform web --output-dir /tmp/birr-web)
(cd /tmp/birr-web && python3 -m http.server 8099) &
MODEL_BASE_URL=http://127.0.0.1:8300/v1 BASETEN_API_KEY=fake SAM_OFF=1 MUSE_ONLY_TOTALS=1 \
  REFS_DIR=/data/refs GEMINI_API_KEY=fake GEMINI_BASE_URL=http://127.0.0.1:8300/v1beta \
  CORS_ORIGINS=http://localhost:8099 uv run uvicorn birr.api:app --port 8000 &
node tools/e2e/integration_voice.js /tmp           # prints requests, clips, text; saves screenshots
```
`REFS_DIR` needs the two reference sheets, or no total is spoken. The scripts need Playwright with Chromium.

**`fake_upstream.py` + `integration_app.js` + `smoke_app.js`** are the older scan-only versions (tap → total), used for PRs #11 and #12. **`test_picture_size.mts`** checks `choosePictureSize` (`node --experimental-strip-types`).

## `experiments/`: the Muse and SAM runs reported in Slack

| Script | What it ran |
|---|---|
| `run_bt.py` | Muse Spark Open on Baseten: prompt arms, with and without reference sheets (`REFS_DIR/clean_sheet.jpg`, `real_sheet.jpg`, `examples.json`). Has a spend cap. |
| `run13.py`, `run_cline2.py` | Muse Spark 1.3 (contributor) through the Cline API, one call at a time. Has a spend cap, and the key comes from a file. |
| `run_sam.py` | Roboflow SAM 3 exactly as the backend calls it (768 px, prompt "banknote"); saves the raw regions. |
| `score13.py`, `score_agree.py`, `score_hard.py`, `score_singles.py`, `score_dev_piles.py` | Scoring: exact totals, wrong totals, rescans, the two-read agreement rule, per-note accuracy, latency and cost. |
| `probe*.py` | Small API probes (model list, latency, `reasoning_effort`). |

These imported the backend as it was on Oct 29–30 (`birr.config`, `birr.segment`, `birr.read`). Later backend changes may need small edits here.

## `logo/`: the Birr logo

`make_logo.py` builds the SVGs: the mark, the icon, the Android adaptive and themed layers, and the splash. `render.js` turns them into PNGs with Chromium. The ብር glyphs come from Noto Sans Ethiopic Black (SIL OFL 1.1), downloaded from Google Fonts, and are written into the SVGs as outlines.

```bash
pip install fonttools
python tools/logo/make_logo.py NotoSansEthiopic-Black.ttf /tmp/logo bubble
node tools/logo/render.js /tmp/logo/icon.svg app/assets/icon.png 1024   # then strip alpha for icon.png
```
