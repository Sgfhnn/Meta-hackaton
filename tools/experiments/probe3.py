import sys, time
import httpx
KEY = open(sys.argv[1]).read().strip()
URL = "https://api.cline.bot/api/v1/chat/completions"
H = {"Authorization": f"Bearer {KEY}"}
body = {"model": sys.argv[2], "temperature": 0, "stream": False,
        "messages": [{"role": "user", "content": "What is 17 + 25? Reply with ONLY JSON: {\"answer\": <number>}"}]}
with httpx.Client(timeout=180) as c:
    t = time.perf_counter(); r = c.post(URL, headers=H, json=body); dt = time.perf_counter() - t
    print(r.status_code, f"{dt:.1f}s", r.headers.get("content-type"))
    print(r.text[:1500])
