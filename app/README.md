# Birr app (Expo, Android first)

One screen for blind and low-vision users. Tap anywhere: the phone photographs the notes, the backend counts them, and the answer is spoken aloud. Hold the screen to ask by voice, like "How much do I have?" or "I paid 500 for something that costs 320". The app never adds up notes and holds no model keys. It only calls our backend (contract: `../docs/api.md`).

## Run it on an Android phone

1. Install **Expo Go** from the Play Store.
2. On a computer with Node 20 or later:
   ```bash
   cd app
   npm install
   cp .env.example .env      # set EXPO_PUBLIC_API_URL to the backend, or leave it empty for demo mode
   npx expo start --tunnel
   ```
3. Scan the QR code with Expo Go. The phone and computer don't need to be on the same network with `--tunnel`.

With `EXPO_PUBLIC_API_URL` empty (or `mock`), the app runs in **demo mode**. It shows "Demo mode (no server)" and cycles through three canned answers (a total, a guide hint, a rescan), so the flow can be tried before the backend is deployed. After changing `.env`, reload the app fully.

## What it does

- **Tap anywhere** (the whole screen is one button, labelled for TalkBack): a vibration and "Counting." play before any network call. **Hold** to ask by voice (below).
- **Photo:** the camera is asked for at least 2048 px on the long side (the iOS "Photo" preset, or the smallest Android size that reaches 2048, preferring 4:3). The photo is capped at 2048 px, never upscaled, and re-encoded as JPEG at quality 85 (about 0.5–1 MB), which drops EXIF data including GPS. The backend reads notes at 2048 px.
- **Scan:** `POST /scan` starts a job (202 with a `job_id`), and the app polls `GET /scan/{job_id}` every `poll_after_ms` until it is done. A backend that answers the POST with the result directly (200) works too.
- **While waiting:** a soft vibration tick every 2 s, and "Still counting." once after about 10 s.
- **Answer:** the app speaks the backend's `speech` text word for word, in the chosen language if this phone has a voice for it, otherwise in English. Totals vibrate as success, and guide or rescan answers as a warning.
- **Slow scans:** the backend ends a scan at 60 s with a rescan answer. The app gives up on its own only after 90 s, which covers a lost connection.
- **Rescans:** after a `guide` or `rescan` answer, the next tap sends `attempt + 1`, up to 3 attempts.
- **Language button** (top right): cycles English, Amharic and Afaan Oromoo. Amharic and Oromo are offered when the backend translates (its `/health` says `voice.gemini: true`) or when the phone has those voices.
- **Ask by voice:** hold the screen, speak, and let go. Or tap **Ask**, speak, and tap again, which also works with TalkBack (the screen button has an "Ask a question" action too). A strong vibration marks the start, and nothing is spoken while recording. Recording stops by itself after 8 s. The question (AAC in `.m4a`, or WebM on the web) goes to `POST /intent`, and the app speaks the answer.
- **Change check:** after "I paid 500, the price is 320", the app says what change to expect, and the next tap scans the change (`intent=change` with `paid` and `price`). The box at the bottom shows "Checking change: paid 500, price 320" until the answer comes back (or for 5 minutes).
- **Amharic and Oromo speech:** answers carry the user's language, and a `speech_audio` link to a clip the backend made with Gemini. The app plays the clip, and if it can't start within 5 s, it speaks the text instead. The app's own prompts ("Counting.") come translated from `GET /phrases`, and their clips are kept on the phone so they still play offline. If the user speaks Amharic, the app switches to Amharic. Oromo clips arrive once the backend turns them on; until then, Oromo answers use the phone's voice or English.
- **Look:** the logo's yellow and deep green (8.7:1 contrast). Splash, icon and Android themed icon are in `assets/`; `assets/logo.svg` is the source.

## Checks

```bash
npx tsc --noEmit
npx expo lint
npx expo export --platform web   # the web preview for judges
```

## Not done yet

- A check by a native speaker of the Amharic and Oromo wording and voice.
- Testing hold-to-talk with TalkBack on real phones. The Ask button is the path TalkBack users are sure to have.
