# Handoff: birr cash assistant

Read this first in any new session. It holds the state as of 28 Oct 2026, morning (EAT). Check Slack in #meta-hackathon for anything newer.

## Where things stand

- **main** has the foundation (PR #1), the API contract (PR #3 and #4) and the live backend (PR #7, Hark's `/scan`).
- **Open:**
  - PR #2 (Kimi, A/B harness): needs a rebase on main and Hark's review fixes.
  - PR #6 (Hermes, eval matrix): needs the gate v2 fixes and the ruff E501 fix at `evals/eval_matrix.py:95`.
  - PR #8 (`docs/birr-knowledge.md`): knowledge pack, branch `claude/birr-knowledge-pack`.
  - PR #9 (`birr/read/muse.py`, knowledge prompt): branch `claude/knowledge-prompt`. Hark recommends not merging as written.
- **Keys:** `BASETEN_API_KEY` and `ROBOFLOW_API_KEY` must be set in the environment for the session. Never paste them into chat, Slack or the repo.

## Product and gate

- Voice-first Ethiopian birr counter for blind and low-vision users. Scope is 5, 10, 50, 100, 200 (2020 series; older series seen in photos).
- Muse Spark Open (Baseten) reads each note. SAM finds and counts notes (Roboflow hosted SAM 3 live; SAM 3.1 on Kaggle for the gate). Totals and change are computed in code, never by the model.
- A total is spoken only when SAM's count equals Muse's count and no note is partial or unclear.
- **Gate v2 (locked 01:00 EAT, sha256 22c7bcf0…61cbed):** ≥18/20 exact after at most one rescan, ≥95% per-note accuracy, zero wrong totals spoken, and on photos with no first-pass total, guided rescans resolve ≥2 more than plain rescans.
- **Gate v3 (proposed, not locked):** zero wrong totals on the locked 20, plus at least one rescan turned into a correct total by SAM guidance. Lock it before new photos are shot. Decision is Anu's.
- Fallback if the gate fails: narrow the product rather than switch to the Auditor, unless Anu decides otherwise.

## Results so far

- Muse alone, full photo, 8 dev photos: 7/8 exact, 0 wrong totals. Miss on D08 (11 fanned notes, marked unclear).
- SAM box crops + Muse: 5/8. Mask crops + Muse: 5/8.
- Muse reads, SAM count must agree: 7/8, 0 wrong.
- PR #9 live run on the locked 20: 0/20 exact. 46 notes unclear, p50 29 s, p90 53 s. Cause: the two-signal rule marks colour-only notes unclear.
- Muse alone with colour map, 768 px: 12/20 exact, 5 wrong totals. A count check from SAM is still required.
- Hark's A/B (colour counts when SAM count matches; 768 px vs 1280 px) was in progress when this was written. Check thread 1793127996.560999.

## Open decisions for Anu

1. Gate v3 terms, and lock them before fresh photos.
2. Whether PR #9 merges after the A/B.
3. Whether to disclose in the README: gate v1 failed on dev and was replaced, and the late gate v2 run used SAM 3 rather than SAM 3.1.

## Next steps

1. Run the locked-20 and dev sets with real keys. Use the Drive datasets from Anu, kept outside the repo. Do not tune on the locked set.
2. Report exact totals, wrong totals, per-note accuracy and p50/p90 latency in the plan thread (1793094827.681179).
3. Resize to 768 px for latency. Do not cap `max_tokens` at 600: Hark measured 450–770 reasoning tokens.
4. Before submission (Nov 4, 9 PM ET; internal target 8 PM EAT): repo goes public, README disclosure, 3-minute demo video. No secrets or datasets in the repo.

## Working rules

- All work on branches, PRs into main. Anu merges, except where Anu's temporary merge authority applies (green CI, no conflicts, reviewed head, announced in Slack, no force-push, no deletes, no visibility changes, no gate changes, no secrets, no locked-20 changes).
- Do not push or open a PR without the user's approval.
- Keep Slack and chat replies short.
