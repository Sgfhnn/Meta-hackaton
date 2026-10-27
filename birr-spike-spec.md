# Meta Hackathon — Birr Cash Assistant: Spike & A/B Gate Harness

## Project
Voice-first Ethiopian birr cash assistant for blind/low-vision users.
Flow: voice intent (Amharic) → SAM 3.1 segments each note → Muse Spark reads each
note individually → totals computed in code → confidence/rescan → spoken
Amharic/English answer. No counterfeit claims; never a one-shot photo→label.

## Status from Slack (latest @muse post, in Claude's plan thread)
- No Modal $100 credit; Modal is free Starter only and needs a card for GPU.
  SAM 3.1 route = Kaggle free T4 notebook (dev) or Roboflow SAM 3 fallback.
  Muse Spark stays on the confirmed Baseten $100 credit
  (`meta-models/muse-spark-open-1026`, vision+audio).
- Discord office-hours rulings:
  - Submission = a public repo that runs and is verifiable; no hosted backend required.
  - No rule restricting builders to partner platforms; Meta models must just be genuinely used.
  - "Simple image analyzer" has no written definition, but precedents allow our
    agent-loop / input-step design.
  - SAM 3.1 / $10K Best Build bonus still unruled → hedge: Muse Spark on Baseten.
- Gate unchanged: Wed 28 Oct 12:00 EAT — 18/20 exact totals, >=95% per-note,
  SAM+Muse >=2 exact totals ahead of Muse alone.

## Done (from Slack)
- Vote decided: cash assistant (gated); Auditor is the fallback.
- Repo `Sgfhnn/Meta-hackaton` created, currently empty; rules:
  `agent/topic` branches -> PR into `main`, @anu merges, no secrets in repo.
- Task split agreed:
  @muse = A/B harness, @hark = SAM deploy, @cue = voice spec,
  @claude = architecture + foundation PR, @hermes = eval matrix + go/no-go report.

## Blocked (Anu-only, no agent tool reaches them)
1. HF access request to `facebook/sam3.1` — token goes to Hark only, never Slack/repo.
2. Photo set: 30 dev + 20 locked birr photos + 1 fanned-note video.
3. Roboflow key + saved Baseten key.
4. Final "approved" to build (foundation PR can proceed sooner).

## A/B Gate Harness (staged here; PR opened when repo is public + approved)
Inputs:
- `photos/dev/*.jpg`, `photos/test/*.jpg`
- `labels/manifest.yaml`: {photo_name: [true_denominations]}
- The 20 locked test photos are never tuned on.

Arms:
- Arm A (baseline): Muse Spark alone, per photo via Baseten partner route.
- Arm B (candidate): SAM segmentation -> per-note Muse Spark read -> code sum.

Scoring (per photo, computed in code — the model never guesses a total):
- per-note denomination accuracy (correct denominations / total notes)
- exact-total flag (code sum == true total)
Low-confidence notes -> rescan prompt, not a guess.

Gate pass on the 20 locked photos:
- >=18/20 exact totals
- >=95% per-note accuracy
- Arm B >=2 exact totals better than Arm A

Output:
- `evidence/<photo>.json`: per-note reads, confidences, total, match.
- `gate_report.json`: per-arm scores + pass/fail vs thresholds at cutoff.

PR plan: branch `muse/bir-ab-harness` -> PR into `main` (not merged by author).
Hermes owns the eval matrix + go/no-go report; one shared harness, not two.

## Next
- Scaffold `bir_ab_harness.py` once dev photos/keys are ready.
