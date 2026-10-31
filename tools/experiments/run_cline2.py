"""Muse Spark 1.3 (Cline API) on the locked 20: colour rule with vs without reference images.

Usage: run_bt.py PHOTO_DIR REFS_DIR OUT_JSONL ARMS [IDS]
  ARMS  comma list: C (colour rule), CR (colour rule + reference images)
Key is read from the file in CLINE_KEY_FILE and is never printed or stored.
Model from MODEL (default meta/muse-spark-1.3-contributor). Cost is the exact amount Cline reports.
Stops at the first API error, or when the estimated spend passes COST_CAP_USD.
"""

import base64
import json
import os
import sys
import time

import httpx

sys.path.insert(0, str(__import__("pathlib").Path(__file__).resolve().parents[2]))  # repo root
from birr.image import prepare_jpeg  # noqa: E402  same resize/re-encode as the backend

URL = "https://api.cline.bot/api/v1/chat/completions"
MODEL = os.environ.get("MODEL", "meta/muse-spark-1.3-contributor")
# Total Baseten test budget agreed with the user is $2. Pass ALREADY_SPENT_USD so a follow-up run counts
# what earlier runs used and the total never passes the budget.
COST_CAP_USD = float(os.environ["CAP_USD"])  # set below the account balance

INSTRUCTIONS = """You are reading cash for a blind user. The photo shows Ethiopian birr banknotes, often held in a hand, fanned, folded or overlapping. List EVERY banknote you can see, including notes at the back of the pile that show only a strip or a corner.

Ethiopian birr notes in circulation: 5, 10, 50, 100, 200.
5   = grey-blue (front has a green tint); boxed "5"; Ge'ez ፭; front: coffee picker; back: kudu + wild cat; older design with a triangle mark.
10  = bright green; Ge'ez ፲; front: camels + coffee picker; back: four people joining hands + mesob basket.
50  = red/pink; Ge'ez ፶; front: tractor ploughing; back: factory with three chimneys.
100 = periwinkle blue (back also mint/teal + peach-orange cave); Ge'ez ፻; front: castle + obelisk; back: Sof Omar cave + Harar gate.
200 = purple/lilac; Ge'ez ፪፻; front: white dove; back: Walia ibex.
Every back shows the Ge'ez numeral, "ብር" and the Latin numeral in the top-right and bottom-left corners: look there first.
The lion head and the Ethiopia map are on every front: they do NOT identify a note.
Count a note once even if a fold or another note splits it into two visible pieces. Count a strip as its own note only when it is clearly a separate piece of paper.

How to decide a value:
- Use every signal you can see: a Latin or Ge'ez numeral, the amount text, the front or back picture (or a fragment of it), and the colour.
- Colour alone can decide a value: purple/lilac = 200, red/pink = 50, bright green = 10, periwinkle blue = 100, grey-blue = 5.
- Two colour families are easy to confuse, so take extra care:
  * Blue: a faded 100 can look as pale as a 5. The 100 is periwinkle with mint/teal areas and a peach cave on the back; the 5 is grey-blue engraving on whitish or yellowed paper. If you cannot tell which, mark the note "unclear".
  * Pink: in warm light the 200's lilac turns pink like the 50, and the 50 can look orange. Look for the ibex or dove (200) versus the chimneys or tractor (50). If only a pink strip shows and you cannot tell, mark it "unclear".

Reply with ONLY JSON, no other text:
{"notes": [{"value": 5|10|50|100|200|null, "evidence": ["latin numeral"|"geez numeral"|"amount text"|"picture"|"colour"], "status": "read"|"unclear"}]}
Use value null with status "unclear" for a note you cannot identify. Never add up the notes."""


def img_part(jpeg_bytes):
    return {"type": "image_url",
            "image_url": {"url": "data:image/jpeg;base64," + base64.b64encode(jpeg_bytes).decode()}}


def reference_parts(refs_dir):
    """Two labelled reference sheets (Baseten allows at most 8 images per request)."""
    return [
        {"type": "text", "text": "Reference images of Ethiopian birr notes follow. Use them to judge colours and "
                                 "pictures. They are NOT part of the photo to read."},
        {"type": "text", "text": "Reference sheet 1: clean notes, each tile shows the front (top) and back (bottom). "
                                 "Each tile is labelled with its value."},
        img_part(open(f"{refs_dir}/clean_sheet.jpg", "rb").read()),
        {"type": "text", "text": "Reference sheet 2: real, worn notes photographed in daylight and in warm indoor "
                                 "light. Each tile is labelled. Note how the 100 looks pale blue with a peach cave, "
                                 "the worn 5 is grey-blue on whitish or yellowed paper, the 50 turns orange in warm "
                                 "light, and the 200 turns pink in warm light."},
        img_part(open(f"{refs_dir}/real_sheet.jpg", "rb").read()),
    ]


def example_parts(refs_dir, photo_dir, skip_id):
    """Worked examples from other hard piles, with their correct notes. Never the pile being read."""
    parts = [{"type": "text", "text": "Worked examples of hard piles with the correct answer. They are NOT the photo "
                                      "to read; learn from them how strips, folds and fans are counted."}]
    for ex in json.load(open(f"{refs_dir}/examples.json")):
        if ex["id"] == skip_id:
            continue
        jpeg, _, _ = prepare_jpeg(open(f"{photo_dir}/{ex['id']}.jpg", "rb").read(), 640)
        parts.append({"type": "text", "text": f"Example: correct notes {ex['notes']}. {ex['lesson']}"})
        parts.append(img_part(jpeg))
    return parts


def parse_notes(text):
    dec = json.JSONDecoder()
    for i, ch in enumerate(text or ""):
        if ch != "{":
            continue
        try:
            obj, _ = dec.raw_decode(text, i)
        except json.JSONDecodeError:
            continue
        if isinstance(obj, dict) and isinstance(obj.get("notes"), list):
            return obj["notes"]
    return None


def main():
    photo_dir, refs_dir, out_path, arms = sys.argv[1:5]
    ids = sys.argv[5].split(",") if len(sys.argv) > 5 else [f"L{n:02d}" for n in range(1, 21)]
    headers = {"Authorization": f"Bearer {open(os.environ['CLINE_KEY_FILE']).read().strip()}"}
    refs = reference_parts(refs_dir)
    spent = 0.0
    with httpx.Client(timeout=180) as client, open(out_path, "a") as out:
        for pid in ids:
            jpeg, w, h = prepare_jpeg(open(f"{photo_dir}/{pid}.jpg", "rb").read(), 768)
            for arm in arms.split(","):
                content = [{"type": "text", "text": INSTRUCTIONS}]
                if arm in ("CR", "CRX"):
                    content += refs
                if arm == "CRX":
                    content += example_parts(refs_dir, photo_dir, pid)
                content += [{"type": "text", "text": "Photo to read:"}, img_part(jpeg)]
                body = {"model": MODEL, "temperature": 0, "stream": False,
                        "messages": [{"role": "user", "content": content}]}
                effort = os.environ.get("EFFORT", "default")
                if effort != "default":
                    body["reasoning_effort"] = effort
                rec = {"id": pid, "arm": arm, "effort": effort, "model": MODEL, "size": [w, h]}
                t = time.perf_counter()
                try:
                    r = client.post(URL, headers=headers, json=body)
                    rec["latency_s"] = round(time.perf_counter() - t, 1)
                    rec["status"] = r.status_code
                    d = r.json()
                    d = d.get("data", d)  # Cline wraps the OpenAI-style body in "data"
                    if r.status_code != 200 or d.get("error"):
                        rec["error"] = str(d.get("error") or d)[:300]
                    else:
                        rec["content"] = d["choices"][0]["message"]["content"]
                        rec["notes"] = parse_notes(rec["content"])
                        u = d.get("usage") or {}
                        rec["prompt_tokens"] = u.get("prompt_tokens")
                        rec["completion_tokens"] = u.get("completion_tokens")
                        rec["reasoning_tokens"] = (u.get("completion_tokens_details") or {}).get("reasoning_tokens")
                        rec["cost"] = float(u.get("cost") or 0)  # exact, as reported by Cline
                except Exception as exc:
                    rec["latency_s"] = round(time.perf_counter() - t, 1)
                    rec["error"] = type(exc).__name__
                spent += rec.get("cost") or 0
                rec["spent_total"] = round(spent, 4)
                out.write(json.dumps(rec, ensure_ascii=False) + "\n")
                out.flush()
                n = len(rec["notes"]) if rec.get("notes") is not None else None
                print(f"{pid} {arm} {rec.get('status')} {rec['latency_s']}s notes={n} in={rec.get('prompt_tokens')} "
                      f"out={rec.get('completion_tokens')} ${rec.get('cost', 0):.5f} total=${spent:.4f} "
                      f"err={rec.get('error')}", flush=True)
                if rec.get("error"):
                    print("STOP: API error, not sending more calls", flush=True)
                    return
                if spent > COST_CAP_USD:
                    print(f"STOP: estimated spend ${spent:.2f} passed the ${COST_CAP_USD} cap", flush=True)
                    return


if __name__ == "__main__":
    main()
