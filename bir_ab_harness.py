"""Birr cash-assistant A/B gate harness (scaffold).

Arm A: Muse Spark alone.
Arm B: SAM segmentation -> Muse Spark per-note -> code-side total.

Scoring is computed in code from per-note outputs. The model never totals a pile.
Pass on the 20 locked test photos: >=18/20 exact totals, >=95% per-note, Arm B
>=2 exact totals ahead of Arm A.

PR: muse/bir-ab-harness -> main (not merged by author). Hermes owns the eval
matrix + go/no-go report.
"""
from __future__ import annotations
import json
from pathlib import Path

try:
    import yaml  # pip install pyyaml
except ImportError:  # manifest can fall back to JSON if needed
    yaml = None

from typing import List, Dict, Any

DEV = Path("photos/dev")
TEST = Path("photos/test")
MANIFEST = Path("labels/manifest.yaml")
EVIDENCE = Path("evidence")
REPORT = Path("gate_report.json")

# Partners
BASETEN_URL = "https://inference.baseten.co/v1"
BASETEN_MODEL = "meta-models/muse-spark-open-1026"
ROBOFLOW_SAM = "roboflow:sam3"  # fallback/endpoint id set in env


def load_manifest() -> Dict[str, List[int]]:
    if yaml:
        return yaml.safe_load(MANIFEST.read_text())
    return json.loads(MANIFEST.read_text())


def sum_denoms(denoms: List[int]) -> int:
    return int(sum(denoms))


def musespark_denominations(image_bytes: bytes) -> List[Dict[str, Any]]:
    """Per-note denomination read. Returns [{denom, conf, box}]."""
    raise NotImplementedError("Call Baseten meta-models/muse-spark-open-1026; parse per-note list.")


def sam_segment(image_bytes: bytes) -> List[Dict[str, Any]]:
    """Segment all notes. Returns [{box, conf}]."""
    raise NotImplementedError("Call Kaggle/Roboflow SAM 3.1 or SAM 3 endpoint; crop each box.")


def score_photo(photo: Path, ground_truth: List[int]):
    gt_total = sum_denoms(ground_truth)
    img = photo.read_bytes()

    a_notes = musespark_denominations(img)
    a_total = sum_denoms([n["denom"] for n in a_notes])

    b_notes = []  # TODO: sam_segment -> crop each -> musespark_denominations(crop)
    b_total = sum_denoms([n["denom"] for n in b_notes])

    return {
        "arm_a_notes": a_notes,
        "arm_a_total": a_total,
        "arm_b_notes": b_notes,
        "arm_b_total": b_total,
        "gt_total": gt_total,
    }


def score_set(photo_results, ground_truth):
    total = len(ground_truth)
    a_exact = sum(1 for r in photo_results if r["gt_total"] == r["arm_a_total"])
    b_exact = sum(1 for r in photo_results if r["gt_total"] == r["arm_b_total"])
    return {
        "a_exact": a_exact,
        "b_exact": b_exact,
        "a_exact_rate": a_exact / total if total else 0.0,
        "b_exact_rate": b_exact / total if total else 0.0,
        "delta": b_exact - a_exact,
    }


def main():
    manifest = load_manifest()
    EVIDENCE.mkdir(exist_ok=True)
    # Run Arm A and Arm B on dev (tune-free) then TEST; never tune on TEST.
    raise NotImplementedError("Wire provider calls, scoring, and gate_report generation.")


if __name__ == "__main__":
    main()
