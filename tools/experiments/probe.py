"""Probe the Cline API: list Muse models, then one tiny text call per reasoning setting."""
import json, sys, time
import httpx

KEY = open(sys.argv[1]).read().strip()
BASE = "https://api.cline.bot/api/v1"
H = {"Authorization": f"Bearer {KEY}"}

with httpx.Client(timeout=120) as c:
    r = c.get(f"{BASE}/models", headers=H)
    print("models:", r.status_code)
    try:
        data = r.json().get("data", r.json())
        for m in data:
            mid = m.get("id", "") if isinstance(m, dict) else str(m)
            if "muse" in mid.lower() or "meta/" in mid.lower():
                keep = {k: m.get(k) for k in ("id", "pricing", "context_length", "supported_parameters") if isinstance(m, dict) and k in m}
                print(" ", json.dumps(keep)[:400])
    except Exception as e:
        print("  could not parse model list:", type(e).__name__, r.text[:300])
