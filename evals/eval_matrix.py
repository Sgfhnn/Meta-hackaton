"""Evals matrix for the birr cash-assistant gate run.

Adds the columns Hark requested: ``rescan_strategy`` (plain | guided) and
``hint_correct``, alongside per-arm totals and per-note accuracy.

Reads per-photo evidence emitted by ``bir_ab_harness.score_photo`` and writes
``evals/results/eval_matrix.csv`` plus a small JSON gate summary.

The gate itself stays unchanged (gate v2); this only records the columns that
decide whether SAM-guided rescans move the result.
"""
from __future__ import annotations

import csv
import json
import statistics
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
EVIDENCE = ROOT / "evidence"
RESULTS = Path(__file__).resolve().parent / "results"
RESULTS.mkdir(exist_ok=True)

COLUMNS = [
    "photo",
    "arm",
    "gt_total",
    "arm_total",
    "total_exact",
    "per_note_acc",
    "rescan_strategy",
    "rescan_used",
    "hint_correct",
    "mean_conf",
    "timing_ms",
    "pass",
]


def per_note_acc(notes: list[dict], true_denoms: list[int]) -> float:
    if not notes:
        return 0.0
    correct = sum(1 for n in notes if n.get("denom") in true_denoms)
    return correct / len(notes)


def rows():
    for path in sorted(EVIDENCE.glob("*.json")):
        ev = json.loads(path.read_text())
        photo = ev.get("photo", path.stem)
        gt = ev.get("gt_total")
        true_denoms = ev.get("true_denoms", [])
        timing = ev.get("timing_ms", {}) or {}
        rescan_used = ev.get("rescan_used", False)
        strategy = ev.get("rescan_strategy", "plain")
        hint_correct = ev.get("hint_correct", None)
        for arm, prefix in (("A", "arm_a"), ("B", "arm_b")):
            notes = ev.get(f"{prefix}_notes", [])
            total = ev.get(f"{prefix}_total")
            exact = total == gt
            row_pass = exact and (not rescan_used or hint_correct is True)
            yield {
                "photo": photo,
                "arm": arm,
                "gt_total": gt,
                "arm_total": total,
                "total_exact": exact,
                "per_note_acc": round(per_note_acc(notes, true_denoms), 4),
                "rescan_strategy": strategy,
                "rescan_used": rescan_used,
                "hint_correct": hint_correct,
                "mean_conf": round(statistics.mean(n["conf"] for n in notes), 4) if notes else "",
                "timing_ms": timing.get(prefix, ""),
                "pass": row_pass,
            }


def write_csv(path: Path) -> int:
    out = list(rows())
    with path.open("w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=COLUMNS)
        writer.writeheader()
        for r in out:
            writer.writerow({k: r.get(k, "") for k in COLUMNS})
    return len(out)


def gate_summary() -> dict:
    summary = {}
    for arm in ("A", "B"):
        rs = [r for r in rows() if r["arm"] == arm]
        guided = [r for r in rs if r["rescan_strategy"] == "guided"]
        summary[arm] = {
            "exact_totals": sum(bool(r["total_exact"]) for r in rs),
            "per_note_mean": round(statistics.mean(r["per_note_acc"] for r in rs), 4) if rs else 0.0,
            "guided_rescans": len(guided),
            "guided_hint_correct": sum(1 for r in guided if r["hint_correct"] is True),
        }
    summary["delta_exact"] = summary["B"]["exact_totals"] - summary["A"]["exact_totals"]
    return summary


def main():
    path = RESULTS / "eval_matrix.csv"
    n = write_csv(path)
    print(f"Wrote {n} rows to {path}")
    print(json.dumps(gate_summary(), indent=2))


if __name__ == "__main__":
    main()
