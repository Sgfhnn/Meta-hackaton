# Third-party licenses

Every open-source dependency, model or service we build on is listed here, as the hackathon rules require.

## Models and hosted services

| Component | License or terms | Used for |
|---|---|---|
| Muse Spark Open (`meta-models/muse-spark-open-1026`) on Baseten | Meta's license for the model, and Baseten's terms of service. Used through the API; we distribute no weights | reading every note |
| Muse Spark 1.3 through the Cline API (optional, off by default) | Cline's terms of service | fallback reader for slow scans |
| SAM 3 and SAM 3.1 (`facebookresearch/sam3` code, `facebook/sam3` and `facebook/sam3.1` weights) | SAM License (Meta, last updated Nov 19, 2025). It covers both code and weights | `modal_sam/` (optional), pinned to commit `f1647e8`. Weights download at runtime from gated Hugging Face repos; none are in this repo |
| Roboflow serverless SAM 3 (optional) | Roboflow's terms of service | hosted SAM 3 (`SAM_PROVIDER=roboflow`) |
| Modal (optional) | Modal's terms of service | GPU hosting for `modal_sam/` |
| Gemini API: `gemini-3.8-flash`, `gemini-3.8-flash-tts` | Google's Gemini API terms | hearing questions, translating answers, speaking Amharic |

## Backend (Python)

| Component | Version | License | Used for |
|---|---|---|---|
| FastAPI | ≥ 0.162 | MIT | the API |
| httpx | ≥ 0.28 | BSD-3-Clause | calls to Baseten, Roboflow, Modal and Gemini |
| Pillow | ≥ 13 | MIT-CMU (HPND) | photo resizing |
| python-multipart | ≥ 0.0.32 | Apache-2.0 | form uploads |
| Uvicorn | ≥ 0.30 | BSD-3-Clause | the server |
| pytest | dev only | MIT | tests |
| ruff | dev only | MIT | lint and format |

## SAM service on Modal (`modal_sam/`, built in Modal's image, not a backend dependency)

| Component | Version | License | Used for |
|---|---|---|---|
| Modal client (`modal`) | 1.6 | Apache-2.0 | deploying the endpoint |
| PyTorch, torchvision | 2.10 | BSD-3-Clause | running SAM |
| FastAPI (`fastapi[standard]`) | latest | MIT | the endpoint |
| Pillow | latest | MIT-CMU (HPND) | decoding the photo |
| SciPy, scikit-image | latest | BSD-3-Clause | SAM's tracking and mask helpers |
| OpenCV (`opencv-python-headless`) | latest | Apache-2.0 | SAM's frame loader |
| psutil | latest | BSD-3-Clause | SAM's memory checks |
| setuptools | < 81 | MIT | `pkg_resources` for SAM's model builder |

## App (Expo)

| Component | Version | License | Used for |
|---|---|---|---|
| Expo SDK (expo, expo-camera, expo-speech, expo-haptics, expo-image-manipulator, expo-file-system, expo-status-bar, expo-image-picker, expo-audio, expo-splash-screen) | 58 | MIT | camera, speech, vibration, photo resize, upload, photo picker, voice recording and playback, splash screen |
| React Native | 0.88 | MIT | the app |
| React, React DOM | 19.3 | MIT | the app |
| react-native-web | 0.21 | MIT | web preview of the app |
| TypeScript | dev only | Apache-2.0 | app type checking |
| ESLint, eslint-config-expo | dev only | MIT | app lint |

## Logo

| Component | License | Used for |
|---|---|---|
| Noto Sans Ethiopic Black (Google) | SIL Open Font License 1.1 | the ብር glyphs in the logo, converted to outlines in `app/assets/logo.svg`. The font itself is not distributed |
