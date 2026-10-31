"""Hardest piles: CR alone vs CRX (worked examples) alone, and C + CRX agreement (+SAM).

Usage: score_hard.py OLD_SCRATCHPAD BASE_FILES(comma) CRX_FILE
BASE_FILES hold the earlier C and CR reads for the same model and effort.
"""
import importlib.util, sys
spn_scripts = __file__.rsplit("/", 1)[0]
spec = importlib.util.spec_from_file_location("sa", f"{spn_scripts}/score_agree.py"); sa = importlib.util.module_from_spec(spec); spec.loader.exec_module(sa)
sys.path.insert(0, str(__import__("pathlib").Path(__file__).resolve().parents[2]))  # repo root
from birr.segment.filter import filter_regions
s = sa.s
old, base_files, crx_file = sys.argv[1], sys.argv[2].split(","), sys.argv[3]
sam_now = {p: len(filter_regions(r)[0]) for p, r in s.sam_regions(old).items()}
base, _, _ = sa.load(base_files)
crx, lat, cost = sa.load([crx_file])
hard = sorted({pid for pid, _ in crx})
tally = {"CR alone": [0, []], "CRX alone": [0, []], "C + CR agree + SAM": [0, []], "C + CRX agree + SAM": [0, []], "C + CRX agree (no SAM)": [0, []]}
for pid in hard:
    t = s.TRUTH[pid]
    c, cr, x = base.get((pid, "C")), base.get((pid, "CR")), crx.get((pid, "CRX"))
    out = {"CR alone": cr, "CRX alone": x,
           "C + CR agree + SAM": c if c and c == cr and sam_now.get(pid) == len(c) else None,
           "C + CRX agree + SAM": c if c and c == x and sam_now.get(pid) == len(c) else None,
           "C + CRX agree (no SAM)": c if c and c == x else None}
    for k, v in out.items():
        if v:
            if sum(v) == t: tally[k][0] += 1
            else: tally[k][1].append(f"{pid}:{sum(v)}")
    print(f"  {pid} truth={t:<4} C={c} CR={cr} CRX={x} sam={sam_now.get(pid)}")
print(f"--- {len(hard)} hardest piles, CRX cost ${cost:.4f}, CRX latency median {sorted(lat.values())[len(lat)//2]}s")
for k, (ex, wr) in tally.items():
    print(f"  {k:26s} right {ex:>2}  wrong {len(wr)} {' '.join(wr)}")
