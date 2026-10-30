"""Local stand-in for Baseten (Muse reads) and Gemini (intent, translation, TTS), for an
app <-> backend voice test. Muse reads 100 + 50. Gemini hears "paid 500, price 320" in Amharic,
translates by prefixing "AM:" (digits kept), and speaks a short tone."""

import base64
import io
import json
import math
import struct
import wave
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

LOG = []


def tone_wav(seconds=0.4, rate=24000):
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(rate)
        frames = b"".join(
            struct.pack("<h", int(8000 * math.sin(2 * math.pi * 440 * i / rate)))
            for i in range(int(seconds * rate))
        )
        w.writeframes(frames)
    return buf.getvalue()


WAV = base64.b64encode(tone_wav()).decode()


def generated(obj):
    return {"candidates": [{"content": {"parts": [{"text": json.dumps(obj, ensure_ascii=False)}]}}]}


class H(BaseHTTPRequestHandler):
    def do_POST(self):
        raw = self.rfile.read(int(self.headers.get("Content-Length", 0)))
        req = json.loads(raw or b"{}")
        if self.path.endswith("/chat/completions"):
            body = {"choices": [{"message": {"content": '{"notes": ["100", "50"]}'}}]}
            kind = "muse"
        elif self.path.endswith(":generateContent"):
            parts = req["contents"][0]["parts"]
            audio = [p for p in parts if "inlineData" in p]
            if audio:
                kind = f"intent({audio[0]['inlineData']['mimeType']}, {len(audio[0]['inlineData']['data'])} b64 chars)"
                body = generated({"transcript": "...", "lang": "am", "intent": "change", "paid": 500, "price": 320})
            else:
                prompt = parts[0]["text"]
                texts = json.loads(prompt.split("Messages:\n", 1)[1])
                kind = f"translate({len(texts)})"
                body = generated({"texts": [f"AM: {t}" for t in texts]})
        elif self.path.endswith("/interactions"):
            kind = "tts"
            body = {"steps": [{"type": "model_output", "content": [{"type": "audio", "data": WAV}]}]}
        else:
            self.send_response(404)
            self.end_headers()
            return
        LOG.append(kind)
        print(kind, flush=True)
        out = json.dumps(body).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(out)))
        self.end_headers()
        self.wfile.write(out)

    def log_message(self, *a):
        pass


ThreadingHTTPServer(("127.0.0.1", 8300), H).serve_forever()
