"""Run Roboflow SAM 3 exactly as the backend does (768 px, prompt banknote) and save raw regions.

Usage: run_sam.py PHOTO_DIR OUT_JSON ID[,ID...]
"""
import asyncio, json, sys
import httpx
sys.path.insert(0, str(__import__("pathlib").Path(__file__).resolve().parents[2]))  # repo root
from birr.config import get_settings
from birr.image import prepare_jpeg
from birr.segment import sam

async def main():
    photo_dir, out, ids = sys.argv[1], sys.argv[2], sys.argv[3].split(",")
    settings = get_settings()
    result = {}
    async with httpx.AsyncClient(timeout=30) as client:
        for pid in ids:
            jpeg, w, h = prepare_jpeg(open(f"{photo_dir}/{pid}.jpg", "rb").read(), 768)
            try:
                regions = await sam.segment(client, jpeg, w, h, settings)
                result[pid] = [{"box": list(r.box), "score": r.score} for r in regions]
                print(pid, "raw regions:", len(regions), flush=True)
            except Exception as exc:
                result[pid] = None
                print(pid, "SAM failed:", type(exc).__name__, flush=True)
    json.dump(result, open(out, "w"), indent=1)

asyncio.run(main())
