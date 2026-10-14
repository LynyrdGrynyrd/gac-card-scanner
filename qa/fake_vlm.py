"""Tiny stand-in for the llama.cpp vision server (tests only): /health, and /v1/chat/completions that
returns the OCR hint's fields with the job title replaced, after FAKE_VLM_DELAY seconds."""
import json, os, re, time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
D = float(os.getenv("FAKE_VLM_DELAY", "3"))
class H(BaseHTTPRequestHandler):
    def log_message(self, *a): pass
    def _send(self, obj):
        b = json.dumps(obj).encode(); self.send_response(200); self.send_header("Content-Type", "application/json"); self.send_header("Content-Length", str(len(b))); self.end_headers(); self.wfile.write(b)
    def do_GET(self): self._send({"status": "ok"})
    def do_POST(self):
        n = int(self.headers.get("Content-Length") or 0); body = json.loads(self.rfile.read(n)); time.sleep(D)
        txt = body["messages"][0]["content"][1]["text"]
        ad = re.search(r"(\d+ [^\n,]+)[\n,] ?([^\n,]+, ?[A-Z]{2},? \d{5})", txt)   # street + city line -> add a suite number
        em = re.findall(r"[\w.+-]+@[\w-]+\.[\w.]+", txt)
        out = {"first_name": "Testy", "last_name": "McFake", "title": "Chief Fake Officer", "company": "Fake Industries", "department": "",
               "emails": em[:1], "phones": [], "website": "www.fake-industries.example", "address": f"{ad.group(1)} Ste 1, {ad.group(2)}" if ad else "1 Fake Way, Akron, OH 44308"}
        self._send({"choices": [{"message": {"content": json.dumps(out)}}]})
ThreadingHTTPServer(("127.0.0.1", int(os.getenv("FAKE_VLM_PORT", "8799"))), H).serve_forever()
