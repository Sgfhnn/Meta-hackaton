"""Dev piles without truths: what each read saw, SAM's count, and the total the system would speak.

Usage: score_dev_piles.py SAM_JSON LABEL=results.jsonl [LABEL=...]
Rule (same as the locked-20 tests): speak only when reads C and CR list the same notes AND SAM's count matches.
"""

import json
import sys

sys.path.insert(0, str(__import__("pathlib").Path(__file__).resolve().parents[2]))  # repo root
from birr.segment.filter import Region, filter_regions  # noqa: E402

VALID = {5, 10, 50, 100, 200}


def load(path):
    reads, lat, cost = {}, {}, 0.0
    for line in open(path):
        r = json.loads(line)
        cost += r.get("cost") or 0
        if r.get("notes") is None:
            continue
        vals = [n.get("value") for n in r["notes"]]
        ok = bool(vals) and all(v in VALID and n.get("status") == "read" for v, n in zip(vals, r["notes"]))
        shown = sorted(v if (v in VALID and n.get("status") == "read") else 0 for v, n in zip(vals, r["notes"]))
        reads[(r["id"], r["arm"])] = (sorted(vals) if ok else None, shown)
        lat[(r["id"], r["arm"])] = r["latency_s"]
    return reads, lat, cost


def fmt(read):
    if read is None:
        return "-"
    ok, shown = read
    return str(ok) if ok else str(["?" if v == 0 else v for v in shown])


def main():
    sam_raw = json.load(open(sys.argv[1]))
    sam = {p: (len(filter_regions([Region(box=tuple(x["box"]), score=x["score"]) for x in v])[0]) if v is not None else None)
           for p, v in sam_raw.items()}
    for arg in sys.argv[2:]:
        label, path = arg.split("=", 1)
        reads, lat, cost = load(path)
        piles = sorted({p for p, _ in reads} | set(sam))
        spoken, scans = [], []
        print(f"=== {label}: ${cost:.4f}")
        for pid in piles:
            c, cr = reads.get((pid, "C")), reads.get((pid, "CR"))
            if (pid, "C") in lat and (pid, "CR") in lat:
                scans.append(max(lat[(pid, "C")], lat[(pid, "CR")]))
            agree = c and cr and c[0] and c[0] == cr[0]
            say = agree and sam.get(pid) == len(c[0])
            if say:
                spoken.append(f"{pid}={sum(c[0])}")
            why = ("SPEAK " + str(sum(c[0]))) if say else ("reads agree, SAM count differs" if agree else "no total")
            print(f"  {pid:11s} C={fmt(c):28s} CR={fmt(cr):28s} SAM={sam.get(pid)}  -> {why}")
        scans.sort()
        print(f"  would speak a total on {len(spoken)}/{len(piles)}: {' '.join(spoken) or 'none'}")
        if scans:
            print(f"  scan time (slower of 2 reads) median {scans[len(scans) // 2]}s, max {scans[-1]}s")


if __name__ == "__main__":
    main()
