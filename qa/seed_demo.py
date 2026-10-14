"""Seed the running server (8765) with 6 demo cards in batch "Demo · sample cards" (stdlib only).
Usage: .venv/bin/python qa/seed_demo.py <admin-user> <password>"""
import sys, time, glob, uuid, json, urllib.request, http.cookiejar
B = "http://127.0.0.1:8765"
op = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(http.cookiejar.CookieJar()))
def call(path, data=None, ctype=None):
    rq = urllib.request.Request(B + path, data=data, headers={"Content-Type": ctype} if ctype else {})
    return json.load(op.open(rq, timeout=120))
call("/api/auth/login", json.dumps({"username": sys.argv[1], "password": sys.argv[2]}).encode(), "application/json")
files = sorted(glob.glob("tests/synth2/*.jpg"))[:5] + ["qa/fixtures/qr_vcard_card.jpg"]
batch = uuid.uuid4().hex[:8]; ids = []
for f in files:
    bd = uuid.uuid4().hex; parts = []
    for k, v in (("batch", batch), ("batch_label", "Demo · sample cards")):
        parts.append(f'--{bd}\r\nContent-Disposition: form-data; name="{k}"\r\n\r\n{v}\r\n'.encode())
    parts.append(f'--{bd}\r\nContent-Disposition: form-data; name="image"; filename="{f.split("/")[-1]}"\r\nContent-Type: image/jpeg\r\n\r\n'.encode() + open(f, "rb").read() + f"\r\n--{bd}--\r\n".encode())
    ids.append(call("/api/jobs", b"".join(parts), f"multipart/form-data; boundary={bd}")["job"])
for _ in range(120):
    js = call("/api/jobs?ids=" + ",".join(ids))["jobs"]
    if all(j["state"] in ("done", "error") for j in js): break
    time.sleep(2)
print(sum(j["state"] == "done" for j in js), "demo cards added")
call("/api/auth/logout", b"{}", "application/json")
