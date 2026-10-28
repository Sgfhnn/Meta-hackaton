# Birr gate-eval matrix

Columns produced by `evals/eval_matrix.py` from `evidence/*.json`, used by the
gated spike. The gate itself stays **gate v2** (`docs/architecture.md`); this
adds the **plain-vs-guided rescan** and `hint_correct` columns that Hark asked
for, to decide whether SAM guidance actually moves the result.

| Column | Values | Notes |
|---|---|---|
| photo | filename | locked-20 or dev photo |
| arm | `A` \| `B` | A = Muse alone; B = SAM segment + per-note Muse |
| gt_total | int | summed truth from the label manifest |
| arm_total | int/`null` | code-computed total for that arm |
| total_exact | bool | `arm_total == gt_total` |
| per_note_acc | float | correct denominations / notes |
| rescan_strategy | `plain` \| `guided` \| `none` | plain = "please rescan"; guided = SAM mask → "slide that note out" |
| rescan_used | bool | whether a rescan happened |
| hint_correct | bool/empty | guided rescans only: did the corrected scan match truth |
| mean_conf | float/empty | mean per-note confidence from Muse |
| timing_ms | int/empty | per-arm call timing |
| pass | bool | `total_exact` AND (`no rescan` OR `hint_correct`) |

**Gate decision (Wed 28 Oct 12:00 EAT, gate v2):**
- ≥18/20 exact totals (after at most one rescan each arm)
- ≥95% per-note accuracy
- SAM+Muse ≥2 exact totals ahead of Muse alone

Generate after the run with:

```bash
python evals/eval_matrix.py   # writes evals/results/eval_matrix.csv + gate summary
```
