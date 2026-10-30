"""Score single-note photos: each photo's notes should all be the folder's value (S100_03 -> 100).

Usage: score_singles.py RESULTS_JSONL [...]
Per read (arm): photos right / wrong value / unclear, per-note accuracy, latency, cost.
Also the two-reads rule: a value is spoken only when both reads list the same notes.
"""

import json
import statistics
import sys
from collections import defaultdict

VALID = {5, 10, 50, 100, 200}


def truth_of(pid):
    head = pid.split("_")[0]  # "S100_03" or "10_flat_01"
    return int(head[1:]) if head.startswith("S") else int(head)


def main():
    recs = [json.loads(line) for p in sys.argv[1:] for line in open(p)]
    by_arm = defaultdict(list)
    reads = {}
    for r in recs:
        by_arm[(r["arm"], r["effort"])].append(r)
    for (arm, effort), rs in sorted(by_arm.items()):
        ok = wrong = unclear = err = notes_right = notes_total = 0
        wrong_list, unclear_list, lat, cost = [], [], [], 0.0
        per_value = defaultdict(lambda: [0, 0])
        for r in rs:
            cost += r.get("cost") or 0
            t = truth_of(r["id"])
            if r.get("notes") is None:
                err += 1
                continue
            lat.append(r["latency_s"])
            vals = [(n.get("value"), n.get("status")) for n in r["notes"]]
            read = [v for v, st in vals if v in VALID and st == "read"]
            reads[(r["id"], arm, effort)] = sorted(read) if len(read) == len(vals) and vals else None
            notes_total += len(vals)
            notes_right += sum(1 for v in read if v == t)
            per_value[t][1] += 1
            if any(v != t for v in read):
                wrong += 1
                wrong_list.append(f"{r['id']}:{read}")
            elif len(read) < len(vals) or not vals:
                unclear += 1
                unclear_list.append(r["id"])
            else:
                ok += 1
                per_value[t][0] += 1
        n = len(rs)
        print(f"=== read {arm}, effort {effort}: {n} photos, ${cost:.4f}, latency median "
              f"{statistics.median(lat) if lat else None}s max {max(lat) if lat else None}s")
        print(f"  right {ok}  wrong value {wrong}  unclear {unclear}  errors {err}  "
              f"per-note accuracy {notes_right}/{notes_total} = {100 * notes_right / max(notes_total, 1):.0f}%")
        print("  by note:", ", ".join(f"{v}: {a}/{b}" for v, (a, b) in sorted(per_value.items())))
        if wrong_list:
            print("  wrong:", " ".join(wrong_list))
        if unclear_list:
            print("  unclear:", " ".join(unclear_list))
    efforts = {e for _, _, e in reads}
    for effort in sorted(efforts):
        ids = sorted({pid for pid, _, e in reads if e == effort})
        right = wrong = silent = 0
        for pid in ids:
            a, b = reads.get((pid, "C", effort)), reads.get((pid, "CR", effort))
            if a and a == b:
                if all(v == truth_of(pid) for v in a):
                    right += 1
                else:
                    wrong += 1
            else:
                silent += 1
        print(f"=== both reads must agree, effort {effort}: right {right}  wrong {wrong}  no answer {silent}  "
              f"of {len(ids)}")


if __name__ == "__main__":
    main()
