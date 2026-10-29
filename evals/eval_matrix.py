"""Eval matrix for the birr cash-assistant gate v2 run.

Reads per-photo evidence from ``evidence/*.json`` and writes
``evals/results/eval_matrix.csv`` plus a JSON gate summary.

Evidence uses the A/B harness keys: ``arm_a_notes``, ``arm_a_total``,
``arm_b_notes``, ``arm_b_total``, ``gt_total`` and ``true_denoms``. A null arm
total means a rescan, not a wrong total. Failed piles also carry
``plain_resolved`` and ``guided_resolved`` for the two reshoot protocols.
"""

from __future__ import annotations

import csv
import json
import statistics
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
EVIDENCE = ROOT / "evidence"
RESULTS = Path(__file__).resolve().parent / "results"
RESULTS.mkdir(exist_ok=True)

MIN_EXACT_RATE = 0.90  # 18/20 on the locked set
MIN_PER_NOTE = 0.95
MIN_GUIDED_DELTA = 2

COLUMNS = [
    "photo",
    "arm",
    "gt_total",
    "arm_total",
    "outcome",
    "total_exact",
    "per_note_acc",
    "rescan_strategy",
    "rescan_used",
    "plain_resolved",
    "guided_resolved",
    "hint_correct",
    "mean_conf",
    "timing_ms",
    "pass",
]


def load_evidence() -> list[dict]:
    evidence = []
    for path in sorted(EVIDENCE.glob("*.json")):
        ev = json.loads(path.read_text())
        ev.setdefault("photo", path.stem)
        evidence.append(ev)
    return evidence


def true_denoms(ev: dict) -> list[int]:
    return ev.get("true_denoms") or ev.get("ground_truth") or []


def note_score(notes: list[dict], truth_denoms: list[int]) -> tuple[int, int]:
    """Return (correct, total) using multiset matching, not set membership."""
    read = Counter(n.get("denom") for n in notes if n.get("denom") is not None)
    truth = Counter(truth_denoms)
    correct = sum((read & truth).values())
    total = max(sum(read.values()), sum(truth.values()))
    return correct, total


def outcome(total: int | None, gt_total: int | None) -> str:
    if total is None:
        return "rescan"
    return "exact" if total == gt_total else "wrong"


def mean_conf(notes: list[dict]) -> float | str:
    confs = []
    for note in notes:
        conf = note.get("conf")
        if conf is not None:
            confs.append(conf)
    return round(statistics.mean(confs), 4) if confs else ""


def rows(evidence: list[dict]):
    for ev in evidence:
        gt = ev.get("gt_total")
        truth = true_denoms(ev)
        timing = ev.get("timing_ms", {}) or {}
        for arm, prefix in (("A", "arm_a"), ("B", "arm_b")):
            notes = ev.get(f"{prefix}_notes", [])
            total = ev.get(f"{prefix}_total")
            result = outcome(total, gt)
            correct, note_total = note_score(notes, truth)
            yield {
                "photo": ev["photo"],
                "arm": arm,
                "gt_total": gt,
                "arm_total": total,
                "outcome": result,
                "total_exact": result == "exact",
                "per_note_acc": round(correct / note_total, 4) if note_total else "",
                "rescan_strategy": ev.get("rescan_strategy", "none"),
                "rescan_used": ev.get("rescan_used", result == "rescan"),
                "plain_resolved": ev.get("plain_resolved"),
                "guided_resolved": ev.get("guided_resolved"),
                "hint_correct": ev.get("hint_correct"),
                "mean_conf": mean_conf(notes),
                "timing_ms": timing.get(prefix, ""),
                "pass": result == "exact",
            }


def write_csv(path: Path, evidence: list[dict]) -> int:
    out = list(rows(evidence))
    with path.open("w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=COLUMNS)
        writer.writeheader()
        for row in out:
            writer.writerow({k: row.get(k, "") for k in COLUMNS})
    return len(out)


def gate_summary(evidence: list[dict]) -> dict:
    summary = {}
    for arm, prefix in (("A", "arm_a"), ("B", "arm_b")):
        counts = {"exact": 0, "wrong": 0, "rescan": 0}
        note_correct = 0
        note_total = 0
        for ev in evidence:
            counts[outcome(ev.get(f"{prefix}_total"), ev.get("gt_total"))] += 1
            correct, total = note_score(ev.get(f"{prefix}_notes", []), true_denoms(ev))
            note_correct += correct
            note_total += total
        summary[arm] = {
            "photos": len(evidence),
            "exact_totals": counts["exact"],
            "wrong_totals": counts["wrong"],
            "rescans": counts["rescan"],
            "per_note_acc": round(note_correct / note_total, 4) if note_total else 0.0,
        }

    plain = sum(ev.get("plain_resolved") is True for ev in evidence)
    guided = sum(ev.get("guided_resolved") is True for ev in evidence)
    summary["plain_resolved"] = plain
    summary["guided_resolved"] = guided
    summary["guided_minus_plain"] = guided - plain

    photos = len(evidence)
    exact_rate = summary["B"]["exact_totals"] / photos if photos else 0.0
    checks = {
        "exact_rate": round(exact_rate, 4),
        "exact_ok": exact_rate >= MIN_EXACT_RATE,
        "per_note_ok": summary["B"]["per_note_acc"] >= MIN_PER_NOTE,
        "zero_wrong_totals": summary["B"]["wrong_totals"] == 0,
        "guided_delta_ok": summary["guided_minus_plain"] >= MIN_GUIDED_DELTA,
    }
    checks["pass"] = all(
        checks[key] for key in ("exact_ok", "per_note_ok", "zero_wrong_totals", "guided_delta_ok")
    )
    summary["gate_v2"] = checks
    return summary


def main():
    evidence = load_evidence()
    path = RESULTS / "eval_matrix.csv"
    n = write_csv(path, evidence)
    print(f"Wrote {n} rows to {path}")
    print(json.dumps(gate_summary(evidence), indent=2))


if __name__ == "__main__":
    main()
