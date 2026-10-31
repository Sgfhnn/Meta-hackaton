# Demo video plan (3 minutes)

The plan for the submission video. It shows one scan with its trace, one question in Amharic, one change check, the app used with TalkBack on and the screen off, and our measured numbers, including the wrong ones.

## What existed before the event

Say this out loud in the video, and put it in the submission form.

- **Before the event (Oct 26, 2026):** the idea, and photos of Birr notes we had taken for testing. Those photos are not in this repo and do not appear in the video.
- **During the event:** everything in this repo. The first commit is dated Oct 26, 2026, 17:44 UTC, and every commit since is in the git history (`git log --reverse`).
- **Made by others:** the models and libraries we build on, such as Muse Spark Open, Omnilingual ASR, MMS-TTS and Expo. They are listed in `docs/licenses.md`.

## Before recording

- Use notes photographed on the day, never the pre-event photos.
- Live settings as on demo day: `SAM_OFF=1`, `MUSE_ONLY_TOTALS=1`, one worker, MMS voice on, `ASR_URL` set to the Omnilingual service.
- Check `GET /health`: `refs` true, and `voice` shows `"hears": "omnilingual"` and `"speaks": ["am"]`.
- Hide anything private on the laptop: no server address, keys, `.env`, Slack or Drive in view. Show a trace from the trace folder in an editor, not a terminal with history.
- Phone: Android, TalkBack on, and the screen dimmed with TalkBack's hide-screen shortcut, so the display is black. Film the hands, the notes and the phone. Captions carry what the phone says.
- Do three takes of each phone shot. Use a take as it happened; if the app asks for a rescan, keep that take or show it as a rescan. Do not cut a wrong total out of a take and present it as right.

## Shot list

| Time | Shot | Audio and captions |
|---|---|---|
| 0:00 – 0:15 | A hand holding a few folded Birr notes, close up | "In Ethiopia, Birr notes of different values can feel almost the same. For a blind person, every payment means trusting someone else's count." |
| 0:15 – 0:30 | Title card: Birr cash assistant, the logo, "Built with Muse Spark Open" | "Birr is a voice-first app that counts Ethiopian cash and checks change. The idea was ours before the event. Every line of code was written during it, from Oct 26." |
| 0:30 – 0:45 | Phone in hand. Turn TalkBack on, then hide the screen; the display goes black | Caption: "TalkBack on. Screen off. Everything from here is by sound." TalkBack speaks the app's button. |
| 0:45 – 1:15 | **Scan.** Notes fanned on a table. One tap; the phone vibrates and speaks the total | Phone: the total, spoken. Caption shows the same words. |
| 1:15 – 1:35 | **Trace.** Cut to the laptop: the JSON trace for that scan | "Every scan leaves a trace. Two Muse reads ran in parallel. Code compares them: a total is spoken only when both list the same notes. Code adds the total, not the model. The trace keeps the labels and timings, never the photo." Point at `reads`, `outcome`, `total`, `timing_ms`. |
| 1:35 – 2:00 | **Amharic question.** Hold the screen and ask "ስንት ብር አለኝ?" ("How much money do I have?"), let go, tap to scan | Phone answers in Amharic with the MMS voice. Caption: the Amharic answer and its English. "Meta Omnilingual ASR hears the question on our own server. The Amharic sentence is a fixed template, and code writes every number." |
| 2:00 – 2:20 | **Change check.** Tap Ask: "I paid 500 for something that costs 320." The app reads the amounts back. Tap to scan the change in hand: 130 Birr (one 100 and three 10s), so it is short | Phone: "You got 130 birr change. You should get 180 birr. You are 50 birr short." Caption shows it. |
| 2:20 – 2:45 | **Numbers.** A plain card with the table below | "We measured the live reader on 37 photos, three scans each. In a normal run: 80 exact, 30 rescans, and 1 wrong total. On a day Baseten was slow: 60 exact, 50 rescans, 1 wrong. Both wrong totals were the same photo: 465 said for 365. Zero wrong totals is our goal. We are not there yet." |
| 2:45 – 3:00 | Close: logo, repo name, limits | "It reads 5, 10, 50, 100 and 200 Birr notes. It does not detect counterfeits. A native speaker has not yet checked the Amharic and Oromo wording. The code, our failed experiments and the licenses are in the repo." |

### Numbers card (2:20)

| Live reader, 37 photos x 3 | Exact | Wrong | No total |
|---|---|---|---|
| Normal run | 80 | 1 | 30 |
| Baseten slow | 60 | 1 | 50 |

Both wrong totals: photo L04, 465 for 365, with both reads agreeing on an extra 100.

## Notes for the edit

- Keep the voice-over to what the app does and what we measured. No claims of accuracy beyond the table.
- If the Amharic answer is not right on any take, say so in the video and show the take as it was.
- If Omnilingual ASR is not running on the day, the question shot changes: the app falls back to Gemini for hearing. Say that in the caption, since the README says Gemini is only a fallback.
- The MMS voice is CC-BY-NC 4.0, so the video is non-commercial.
