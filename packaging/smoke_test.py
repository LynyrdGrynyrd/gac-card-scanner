"""Smoke-test a built bundle: start it headless, wait for /health, scan a synthetic card, check the result, stop it.
  python packaging/smoke_test.py "<path to the bundle executable>" [card.jpg]"""
import json, os, subprocess, sys, tempfile, time, urllib.request, uuid

def main(exe, card="tests/cards/card1_left.jpg"):
    import socket; s = socket.socket(); s.bind(("127.0.0.1", 0)); port = s.getsockname()[1]; s.close()
    data = tempfile.mkdtemp(prefix="gac-smoke-")
    env = dict(os.environ, GAC_DATA_DIR=data)
    p = subprocess.Popen(([sys.executable] if exe.endswith(".py") else []) + [exe, "--headless", "--port", str(port)], env=env)
    base = f"http://127.0.0.1:{port}"; ok = False
    try:
        t0 = time.time()
        while time.time() - t0 < 180:
            if p.poll() is not None: raise SystemExit(f"bundle exited early with code {p.returncode}")
            try:
                h = json.loads(urllib.request.urlopen(base + "/health", timeout=3).read()); assert h.get("ok"), h; print("health:", h, f"({time.time()-t0:.1f}s)"); break
            except Exception: time.sleep(1)
        else: raise SystemExit("no /health within 180 s")
        img = open(card, "rb").read(); b = uuid.uuid4().hex
        body = (f"--{b}\r\nContent-Disposition: form-data; name=\"image\"; filename=\"card.jpg\"\r\nContent-Type: image/jpeg\r\n\r\n").encode() + img + \
               f"\r\n--{b}\r\nContent-Disposition: form-data; name=\"engine\"\r\n\r\ntesseract\r\n--{b}--\r\n".encode()
        req = urllib.request.Request(base + "/api/scan", body, {"Content-Type": "multipart/form-data; boundary=" + b})
        t1 = time.time(); r = json.loads(urllib.request.urlopen(req, timeout=300).read()); f = r["fields"]
        print(f"scan ({time.time()-t1:.1f}s): engine={r['engine']} name={f.get('first_name')} {f.get('last_name')} company={f.get('company')} emails={f.get('emails')} phones={len(f.get('phones') or [])}")
        assert any("summitvalleybank" in e.lower() for e in f.get("emails") or []), "email not read: Tesseract/OCR not working"
        assert (f.get("last_name") or "").lower() == "delgado", "name not read"
        assert r["engine"].startswith("ppocr"), "PP-OCR detector not used (onnx models missing?) engine=" + r["engine"]
        ok = True; print("SMOKE TEST PASSED")
    finally:
        p.terminate()
        try: p.wait(20)
        except Exception: p.kill()
        log = os.path.join(data, "app.log")
        if not ok and os.path.exists(log): print("---- app.log ----\n" + open(log, encoding="utf-8", errors="replace").read()[-6000:])
    return 0

if __name__ == "__main__": sys.exit(main(*sys.argv[1:]))
