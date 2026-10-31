"""One tiny text call per reasoning setting: does the API accept it, and what does it cost in time and tokens."""
import json, sys, time
import httpx

KEY = open(sys.argv[1]).read().strip()
URL = "https://api.cline.bot/api/v1/chat/completions"
H = {"Authorization": f"Bearer {KEY}"}
MODEL = sys.argv[2]
msg = [{"role": "user", "content": "What is 17 + 25? Reply with ONLY JSON: {\"answer\": <number>}"}]
variants = {
    "default": {},
    "reasoning_effort=low": {"reasoning_effort": "low"},
    "reasoning.effort=low": {"reasoning": {"effort": "low"}},
}
with httpx.Client(timeout=180) as c:
    for name, extra in variants.items():
        t = time.perf_counter()
        r = c.post(URL, headers=H, json={"model": MODEL, "temperature": 0, "messages": msg, **extra})
        dt = time.perf_counter() - t
        try:
            d = r.json()
            content = (d.get("choices") or [{}])[0].get("message", {}).get("content")
            usage = d.get("usage")
            err = d.get("error")
        except Exception:
            content, usage, err = None, None, r.text[:200]
        print(f"{name:22s} status={r.status_code} {dt:5.1f}s content={str(content)[:60]!r}")
        print(f"{'':22s} usage={json.dumps(usage)[:300]} error={str(err)[:200] if err else None}")
