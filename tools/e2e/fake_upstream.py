"""Local stand-in for Baseten (chat completions) and Roboflow SAM 3, for an app<->backend test.
Muse answers two readable notes (100 and 50) after 2 s; SAM answers two matching regions."""
import json, time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

MUSE = {"choices": [{"message": {"content": json.dumps({"notes": [
    {"value": 100, "evidence": ["latin numeral"], "status": "read"},
    {"value": 50, "evidence": ["colour"], "status": "read"}]})}}]}
SAM = {"prompt_results": [{"predictions": [
    {"confidence": 0.93, "masks": [[[40, 40], [360, 40], [360, 260], [40, 260]]]},
    {"confidence": 0.91, "masks": [[[400, 300], [740, 300], [740, 540], [400, 540]]]}]}]}

class H(BaseHTTPRequestHandler):
    def do_POST(self):
        self.rfile.read(int(self.headers.get("Content-Length", 0)))
        if self.path.endswith("/chat/completions"):
            time.sleep(2); body = MUSE
        else:
            body = SAM
        out = json.dumps(body).encode()
        self.send_response(200); self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(out))); self.end_headers(); self.wfile.write(out)
    def log_message(self, *a): pass

ThreadingHTTPServer(("127.0.0.1", 8300), H).serve_forever()
