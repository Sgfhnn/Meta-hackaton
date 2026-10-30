"""Score Muse 1.3 runs on the locked 20: Muse alone, + SAM check (current filter), + SAM check (adjusted filter).

Usage: score13.py OLD_SCRATCHPAD RESULTS_JSONL [RESULTS_JSONL ...]
SAM counts come from the raw boxes saved in yesterday's backend traces (same 768 px images), so no SAM calls.
"""

import glob
import json
import statistics
import sys

sys.path.insert(0, str(__import__("pathlib").Path(__file__).resolve().parents[2]))  # repo root
from birr.segment.filter import Region, filter_regions  # noqa: E402

TRUTH = {"L01": 100, "L02": 205, "L03": 110, "L04": 365, "L05": 115, "L06": 550, "L07": 150,
         "L08": 310, "L09": 75, "L10": 510, "L11": 220, "L12": 370, "L13": 5, "L14": 250,
         "L15": 15, "L16": 320, "L17": 260, "L18": 155, "L19": 400, "L20": 610}
VALID = {5, 10, 50, 100, 200}


def sam_regions(sp):
    """photo id -> raw SAM regions, from the first saved trace that has SAM output."""
    tid2id = {}
    for line in open(f"{sp}/results/locked20_main.jsonl"):
        r = json.loads(line)
        try:
            tid2id[json.loads(r["resp"]).get("trace_id")] = r["id"]
        except Exception:
            pass
    for f in glob.glob(f"{sp}/results/retry_*.json"):
        i, b = open(f).read().split("\t", 1)
        try:
            tid2id[json.loads(b).get("trace_id")] = i
        except Exception:
            pass
    for line in open(f"{sp}/results/locked20_hedge.tsv"):
        i, _, b = line.rstrip("\n").split("\t", 2)
        try:
            tid2id[json.loads(b).get("trace_id")] = i
        except Exception:
            pass
    out = {}
    for f in sorted(glob.glob(f"{sp}/traces/*.json") + glob.glob(f"{sp}/traces2/*.json")):
        d = json.load(open(f))
        pid = tid2id.get(d.get("trace_id"))
        if pid and "sam" in d and pid not in out:
            out[pid] = [Region(box=tuple(x["box"]), score=x["score"]) for x in d["sam"]["filter"]]
    return out


def _inter(a, b):
    ax, ay, aw, ah = a.box
    bx, by, bw, bh = b.box
    return max(0, min(ax + aw, bx + bw) - max(ax, bx)) * max(0, min(ay + ah, by + bh) - max(ay, by))


def adjusted_count(regions):
    """Score >= 0.5, area >= 0.04, box NMS 0.6, then drop any box that encloses 2+ kept boxes."""
    kept = []
    for r in sorted(regions, key=lambda r: -r.score):
        if r.score < 0.5 or r.area < 0.04:
            continue
        ious = [_inter(r, k) / (r.area + k.area - _inter(r, k)) for k in kept]
        if any(v >= 0.6 for v in ious):
            continue
        kept.append(r)
    kept = [k for k in kept if sum(1 for o in kept if o is not k and _inter(k, o) >= 0.7 * o.area) < 2]
    return len(kept)


def pct(xs, q):
    xs = sorted(xs)
    return xs[min(len(xs) - 1, int(round(q * (len(xs) - 1))))] if xs else None


def main():
    sp, paths = sys.argv[1], sys.argv[2:]
    sam = sam_regions(sp)
    sam_old = {p: len(filter_regions(r)[0]) for p, r in sam.items()}
    sam_new = {p: adjusted_count(r) for p, r in sam.items()}
    recs = [json.loads(line) for path in paths for line in open(path)]
    groups = {}
    for r in recs:
        groups.setdefault((r["arm"], r["effort"]), []).append(r)
    for (arm, effort), rs in sorted(groups.items()):
        rs = sorted(rs, key=lambda r: r["id"])
        tally = {k: {"exact": 0, "wrong": [], "none": 0} for k in ("muse_only", "sam_now", "sam_adj")}
        read_exact = unclear = errors = 0
        lat, cost, rows = [], 0.0, []
        for r in rs:
            pid, truth = r["id"], TRUTH[r["id"]]
            notes = r.get("notes")
            cost += r.get("cost") or 0
            if r.get("latency_s") is not None and r.get("status") == 200:
                lat.append(r["latency_s"])
            if notes is None:
                errors += 1
                for k in tally:
                    tally[k]["none"] += 1
                rows.append(f"  {pid} truth={truth:<4} ERROR/unparsed {r.get('error')}")
                continue
            vals = [n.get("value") for n in notes]
            ok = bool(vals) and all(v in VALID and n.get("status") == "read" for v, n in zip(vals, notes))
            unclear += sum(1 for v, n in zip(vals, notes) if not (v in VALID and n.get("status") == "read"))
            total = sum(vals) if ok else None
            read_exact += total == truth
            spoken = {"muse_only": ok,
                      "sam_now": ok and sam_old.get(pid) == len(notes),
                      "sam_adj": ok and sam_new.get(pid) == len(notes)}
            for k, s in spoken.items():
                if not s:
                    tally[k]["none"] += 1
                elif total == truth:
                    tally[k]["exact"] += 1
                else:
                    tally[k]["wrong"].append(f"{pid} {total}")
            shown = [v if (v in VALID and n.get("status") == "read") else "?" for v, n in zip(vals, notes)]
            rows.append(f"  {pid} truth={truth:<4} muse={str(total):<5} notes={shown} "
                        f"sam_now={sam_old.get(pid)} sam_adj={sam_new.get(pid)} {r.get('latency_s')}s")
        print(f"=== arm {arm}, reasoning {effort}: {len(rs)} photos, ${cost:.3f}, "
              f"latency p50 {pct(lat, .5)}s p90 {pct(lat, .9)}s max {max(lat) if lat else None}s")
        print(f"  Muse read the exact total on {read_exact}/{len(rs)}; unclear notes {unclear}; errors {errors}")
        for k, label in (("muse_only", "Muse alone"), ("sam_now", "+ SAM, current filter"),
                         ("sam_adj", "+ SAM, adjusted filter")):
            t = tally[k]
            print(f"  {label:24s} exact {t['exact']:>2}  wrong {len(t['wrong'])} {t['wrong']}  no total {t['none']}")
        print("\n".join(rows))
        print()


if __name__ == "__main__":
    main()
