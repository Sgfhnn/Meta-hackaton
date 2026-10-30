"""Compare setups on the locked 20: single reads (+SAM) and the two-reads-must-agree rule (+SAM).

Usage: score_agree.py OLD_SCRATCHPAD LABEL=file1.jsonl,file2.jsonl [LABEL=...]
Each label groups result files from one model + effort; arms C and CR are the two reads.
"""

import importlib.util
import json
import sys

sys.path.insert(0, str(__import__("pathlib").Path(__file__).resolve().parents[2]))  # repo root
from birr.segment.filter import filter_regions  # noqa: E402

spec = importlib.util.spec_from_file_location("score13", __file__.replace("score_agree.py", "score13.py"))
s = importlib.util.module_from_spec(spec)
spec.loader.exec_module(s)


def load(paths):
    reads, lat, cost = {}, {}, 0.0
    for p in paths:
        for line in open(p):
            r = json.loads(line)
            cost += r.get("cost") or 0
            if r.get("notes") is None:
                continue
            vals = [n.get("value") for n in r["notes"]]
            ok = bool(vals) and all(v in s.VALID and n.get("status") == "read" for v, n in zip(vals, r["notes"]))
            reads[(r["id"], r["arm"])] = sorted(vals) if ok else None
            lat[(r["id"], r["arm"])] = r["latency_s"]
    return reads, lat, cost


def pct(xs, q):
    xs = sorted(xs)
    return xs[min(len(xs) - 1, int(round(q * (len(xs) - 1))))] if xs else None


def main():
    sam = s.sam_regions(sys.argv[1])
    sam_now = {p: len(filter_regions(r)[0]) for p, r in sam.items()}
    print(f"{'setup':34s} {'right':>6} {'wrong':>6}  wrong photos")
    for arg in sys.argv[2:]:
        label, files = arg.split("=", 1)
        reads, lat, cost = load(files.split(","))
        tallies = {}
        for name in ("C alone", "C + SAM", "CR alone", "CR + SAM", "agree + SAM"):
            tallies[name] = [0, []]
        scan = []
        for pid, truth in s.TRUTH.items():
            a, b = reads.get((pid, "C")), reads.get((pid, "CR"))
            if (pid, "C") in lat and (pid, "CR") in lat:
                scan.append(max(lat[(pid, "C")], lat[(pid, "CR")]))
            spoken = {
                "C alone": a, "C + SAM": a if a and sam_now.get(pid) == len(a) else None,
                "CR alone": b, "CR + SAM": b if b and sam_now.get(pid) == len(b) else None,
                "agree + SAM": a if a and a == b and sam_now.get(pid) == len(a) else None,
            }
            for name, notes in spoken.items():
                if notes:
                    if sum(notes) == truth:
                        tallies[name][0] += 1
                    else:
                        tallies[name][1].append(f"{pid}:{sum(notes)}")
        print(f"--- {label}: ${cost:.4f}, scan time (slower of 2 parallel reads) "
              f"p50 {pct(scan, .5)}s p90 {pct(scan, .9)}s max {max(scan) if scan else None}s, photos {len(scan)}")
        for name, (ex, wr) in tallies.items():
            print(f"  {name:32s} {ex:>6} {len(wr):>6}  {' '.join(wr)}")


if __name__ == "__main__":
    main()
