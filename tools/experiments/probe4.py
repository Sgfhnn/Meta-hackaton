import json, sys, time
import httpx
KEY = open(sys.argv[1]).read().strip()
URL = "https://api.cline.bot/api/v1/chat/completions"
H = {"Authorization": f"Bearer {KEY}"}
msg = [{"role": "user", "content": "What is 17 + 25? Reply with ONLY JSON: {\"answer\": <number>}"}]
variants = {"default": {}, "reasoning_effort=low": {"reasoning_effort": "low"},
            "reasoning.effort=low": {"reasoning": {"effort": "low"}},
            "reasoning_effort=minimal": {"reasoning_effort": "minimal"}}
with httpx.Client(timeout=180) as c:
    for name, extra in variants.items():
        t = time.perf_counter()
        r = c.post(URL, headers=H, json={"model": sys.argv[2], "temperature": 0, "stream": False, "messages": msg, **extra})
        dt = time.perf_counter() - t
        d = r.json(); d = d.get("data", d)
        ch = (d.get("choices") or [{}])[0]
        gw = ch.get("message", {}).get("provider_metadata", {}).get("gateway", {})
        print(f"{name:26s} {r.status_code} {dt:4.1f}s content={ch.get('message', {}).get('content')!r} "
              f"cost=${gw.get('cost')} usage={json.dumps(d.get('usage'))[:160]} err={str(d.get('error'))[:120] if d.get('error') else None}")
