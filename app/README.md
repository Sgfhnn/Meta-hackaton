# Birr app (Expo, Android first)

One screen for blind and low-vision users. Tap anywhere: the phone photographs the notes, the backend counts them, and the answer is spoken aloud. The app never adds up notes and holds no model keys. It only calls the backend's `POST /scan` (contract: `../docs/api.md`).

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

- **Tap anywhere** (the whole screen is one button, labelled for TalkBack): a vibration and "Counting." play before any network call.
- **While waiting:** a soft vibration tick every 2 s, and "Still counting." every 8 s.
- **Photo:** resized to 1280 px on the longest side and re-encoded as JPEG, which drops EXIF data including GPS.
- **Answer:** the app speaks the backend's `speech` text word for word, in the chosen language if this phone has a voice for it, otherwise in English. Totals vibrate as success, and guide or rescan answers as a warning.
- **Slow scans:** after 60 s the app cancels and retries once with `fast=1` (the backend then runs a single read). If that also fails, it asks the user to try again.
- **Rescans:** after a `guide` or `rescan` answer, the next tap sends `attempt + 1`, up to 3 attempts.
- **Language button** (top right): cycles English, then Amharic and Afaan Oromoo if the phone has those voices.

## Checks

```bash
npx tsc --noEmit
npx expo lint
npx expo export --platform web   # the web preview for judges
```

## Not done yet

- Amharic and Oromo speech through Gemini. The app's own short prompts ("Counting.", "Still counting.") are English only for now.
- "Is my change right?" by voice (`POST /intent`).
- Pre-recorded audio clips for totals (allowed by the contract).
