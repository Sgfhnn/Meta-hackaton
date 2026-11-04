# Birr web demo

Try Birr in a browser, no install: https://birr-demo.vercel.app

The page sends one photo to the same scan backend as the phone app (`birr/`), running as a Vercel
Python function (`api/index.py`). Muse Spark Open reads the notes twice; a total is spoken only
when both reads agree. Answers in English or Amharic (fixed templates, so no model can change an
amount), spoken with the browser's voice. The phone app adds Meta Omnilingual ASR (spoken
questions) and Meta MMS-TTS (Amharic voice), which are too large for a serverless function.

A per-visitor limit (15 scans an hour) and a daily cap protect the Muse budget.

Deploy: `web/deploy.sh` (see the header). `BASETEN_API_KEY` lives in the Vercel project settings.
