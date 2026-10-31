"""Muse Spark 1.3 on the locked 20 via the Cline API, one call at a time.

Usage: run13.py KEYFILE PHOTO_DIR OUT_JSONL ARMS EFFORT [IDS]
  ARMS   comma list of prompt arms: S (strict, Hark's rule), L (narrow colour rule)
  EFFORT default | low | minimal | medium | high
Stops early if the reported spend passes COST_CAP_USD. Never prints or stores the key.
"""

import base64
import json
import sys
import time

import httpx

sys.path.insert(0, str(__import__("pathlib").Path(__file__).resolve().parents[2]))  # repo root
from birr.image import prepare_jpeg  # noqa: E402  same resize/re-encode as the backend

URL = "https://api.cline.bot/api/v1/chat/completions"
MODEL = "meta/muse-spark-1.3"
COST_CAP_USD = 3.0

COMMON = """You are reading cash for a blind user. The photo shows Ethiopian birr banknotes, often held in a hand, fanned, folded or overlapping. List EVERY banknote you can see, including notes at the back of the pile that show only a strip or a corner.

Ethiopian birr notes in circulation: 5, 10, 50, 100, 200.
5   = grey-blue (front has a green tint); boxed "5"; Ge'ez ፭; front: coffee picker; back: kudu + wild cat; older design with a triangle mark.
10  = bright green; Ge'ez ፲; front: camels + coffee picker; back: four people joining hands + mesob basket.
50  = red/pink; Ge'ez ፶; front: tractor ploughing; back: factory with three chimneys.
100 = blue (back also teal + orange-brown cave); Ge'ez ፻; front: castle + obelisk; back: Sof Omar cave + Harar gate.
200 = purple; Ge'ez ፪፻; front: white dove; back: Walia ibex.
Every back shows the Ge'ez numeral, "ብር" and the Latin numeral in the top-right and bottom-left corners: look there first.
The lion head and the Ethiopia map are on every front: they do NOT identify a note.
Count a note once even if a fold or another note splits it into two visible pieces.
Judge colour from the printed bands, not from yellowed paper, glare or shadow.
"""

RULES = {
    "S": """How to decide a value:
- Decide each note's value from a Latin or Ge'ez numeral, the amount text, or the front or back picture (a clear fragment such as ibex horns or the chimneys counts).
- Colour alone never decides a value. Use colour only to choose between values the other signals leave open.
- A strip, edge or corner where you cannot see a numeral, amount text or picture is "unclear".
""",
    "L": """How to decide a value:
- Prefer a Latin or Ge'ez numeral, the amount text, or the front or back picture (a clear fragment such as ibex horns or the chimneys counts).
- Colour alone may decide a value ONLY when the strip is large, evenly lit and plainly one of: vivid purple/violet = 200, vivid red/pink = 50, saturated bright green = 10.
- Never decide by colour alone for grey-blue, blue, teal or orange-brown strips (they can be a 5, a 100 front, or the 100 back's teal and cave areas), or for faded, sun-bleached, dim or shadowed strips. Those need a numeral, amount text or picture, otherwise "unclear".
- A thin edge where no corner, numeral or picture of that note is visible is "unclear".
""",
}

OUTPUT = """Reply with ONLY JSON, no other text:
{"notes": [{"value": 5|10|50|100|200|null, "evidence": ["latin numeral"|"geez numeral"|"amount text"|"picture"|"colour"], "status": "read"|"unclear"}]}
Use value null with status "unclear" for a note you cannot identify. Never add up the notes."""


def parse_notes(text):
    """First JSON object in the reply that has a notes list, or None."""
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
    keyfile, photo_dir, out_path, arms, effort = sys.argv[1:6]
    ids = sys.argv[6].split(",") if len(sys.argv) > 6 else [f"L{n:02d}" for n in range(1, 21)]
    key = open(keyfile).read().strip()
    headers = {"Authorization": f"Bearer {key}"}
    spent = 0.0
    with httpx.Client(timeout=180) as client, open(out_path, "a") as out:
        for pid in ids:
            jpeg, w, h = prepare_jpeg(open(f"{photo_dir}/{pid}.jpg", "rb").read(), 768)
            url = "data:image/jpeg;base64," + base64.b64encode(jpeg).decode()
            for arm in arms.split(","):
                prompt = COMMON + "\n" + RULES[arm] + "\n" + OUTPUT
                body = {
                    "model": MODEL,
                    "temperature": 0,
                    "stream": False,
                    "messages": [{"role": "user", "content": [
                        {"type": "text", "text": prompt},
                        {"type": "image_url", "image_url": {"url": url}},
                    ]}],
                }
                if effort != "default":
                    body["reasoning_effort"] = effort
                rec = {"id": pid, "arm": arm, "effort": effort, "size": [w, h]}
                t = time.perf_counter()
                try:
                    r = client.post(URL, headers=headers, json=body)
                    rec["latency_s"] = round(time.perf_counter() - t, 1)
                    rec["status"] = r.status_code
                    d = r.json()
                    d = d.get("data", d)
                    msg = (d.get("choices") or [{}])[0].get("message", {})
                    rec["content"] = msg.get("content")
                    rec["notes"] = parse_notes(rec["content"])
                    usage = d.get("usage") or {}
                    rec["cost"] = float(usage.get("cost") or 0)
                    rec["reasoning_tokens"] = (usage.get("completion_tokens_details") or {}).get("reasoning_tokens")
                    rec["prompt_tokens"] = usage.get("prompt_tokens")
                    if d.get("error"):
                        rec["error"] = str(d["error"])[:300]
                except Exception as exc:  # record and continue; never retry silently
                    rec["latency_s"] = round(time.perf_counter() - t, 1)
                    rec["error"] = type(exc).__name__
                spent += rec.get("cost") or 0
                rec["spent_total"] = round(spent, 4)
                out.write(json.dumps(rec, ensure_ascii=False) + "\n")
                out.flush()
                n = len(rec["notes"]) if rec.get("notes") is not None else None
                print(f"{pid} {arm} {effort} {rec.get('status')} {rec['latency_s']}s notes={n} "
                      f"cost=${rec.get('cost', 0):.4f} total=${spent:.3f} err={rec.get('error')}", flush=True)
                if spent > COST_CAP_USD:
                    print(f"STOP: spend ${spent:.2f} passed the ${COST_CAP_USD} cap", flush=True)
                    return


if __name__ == "__main__":
    main()
