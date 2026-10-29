# Birr gate-eval matrix

Columns produced by `evals/eval_matrix.py` from `evidence/*.json`. Evidence uses
the A/B harness keys (`arm_a_notes`, `arm_a_total`, `arm_b_notes`,
`arm_b_total`, `gt_total`, `true_denoms`). A `null` arm total means **rescan**,
not a wrong total.

| Column | Values | Notes |
|---|---|---|
| photo | filename | locked-20 or dev photo |
| arm | `A` \| `B` | A = Muse alone; B = SAM segment + per-note Muse |
| gt_total | int | summed truth from the label manifest |
| arm_total | int/`null` | code-computed total; `null` = rescan |
| outcome | `exact` \| `wrong` \| `rescan` | distinguishes wrong totals from rescans |
| total_exact | bool | `outcome == exact` |
| per_note_acc | float/empty | multiset intersection ÷ max(read count, truth count) |
| rescan_strategy | `plain` \| `guided` \| `none` | rescan prompt used |
| rescan_used | bool | whether a rescan happened |
| plain_resolved | bool/empty | plain "please rescan" reshoot resolved the failed pile |
| guided_resolved | bool/empty | SAM-guided reshoot resolved the same failed pile |
| hint_correct | bool/empty | guided hint matched truth |
| mean_conf | float/empty | mean non-null per-note confidence |
| timing_ms | int/empty | per-arm call timing |
| pass | bool | row has an exact total |

**Gate v2 (locked Wed 28 Oct 12:00 EAT):** pass requires all of:
- ≥18/20 exact totals after at most one rescan
- ≥95% per-note accuracy
- **zero wrong totals spoken**
- on photos with no first-pass total, guided rescans resolve **≥2 more** than plain

The JSON summary reports `wrong_totals`, `plain_resolved`, `guided_resolved`,
`guided_minus_plain`, and these gate checks. Generate with:

```bash
python evals/eval_matrix.py
```
