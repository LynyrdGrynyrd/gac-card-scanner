"""Load + crash-recovery test against a COPY. Usage:
   python audits/scripts/load_test.py load  <user> <pw> [N=100]
   python audits/scripts/load_test.py crash <user> <pw> [N=20]     (kills and restarts the copy server itself)
Env: GAC_BASE (default http://127.0.0.1:8775), GAC_DIR (copy dir, for restart), OUT"""
import os, sys, io, json, time, glob, random, subprocess, threading, statistics, urllib.request, http.cookiejar, uuid
from concurrent.futures import ThreadPoolExecutor
B = os.environ.get("GAC_BASE", "http://127.0.0.1:8775"); D = os.environ.get("GAC_DIR", "/workspace/gac-audit-copy"); PORT = B.rsplit(":", 1)[1]
mode, U, P = sys.argv[1], sys.argv[2], sys.argv[3]; N = int(sys.argv[4]) if len(sys.argv) > 4 else (100 if mode == "load" else 20)
cj = http.cookiejar.CookieJar(); op = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(cj))
def call(method, path, body=None, headers=None, timeout=60):
    t = time.time(); r = urllib.request.Request(B + path, data=body, headers=headers or {}, method=method)
    try: resp = op.open(r, timeout=timeout); d = resp.read(); code = resp.status
    except urllib.error.HTTPError as e: d = e.read(); code = e.code
    return code, d, time.time() - t
def login(): call("POST", "/api/auth/login", json.dumps({"username": U, "password": P}).encode(), {"Content-Type": "application/json"})
def srv_pid():
    out = subprocess.run(["pgrep", "-f", f"port {PORT}"], capture_output=True, text=True).stdout.split(); return int(out[0]) if out else None
def rss_mb(pid):
    try: return int(open(f"/proc/{pid}/status").read().split("VmRSS:")[1].split()[0]) / 1024
    except Exception: return None
files = sorted(glob.glob("/workspace/gac-card-scanner/tests/synth2/*.jpg") + glob.glob("/workspace/gac-card-scanner/tests/cards/*.jpg"))
def submit(i, batch):
    from PIL import Image
    im = Image.open(files[i % len(files)]).convert("RGB"); px = im.load(); px[i % im.size[0], 0] = (i % 255, 7, 7)   # unique bytes per card
    b = io.BytesIO(); im.save(b, "JPEG", quality=90); data = b.getvalue(); bd = uuid.uuid4().hex
    body = (f"--{bd}\r\nContent-Disposition: form-data; name=\"batch\"\r\n\r\n{batch}\r\n--{bd}\r\nContent-Disposition: form-data; name=\"batch_label\"\r\n\r\nLoad {batch}\r\n--{bd}\r\nContent-Disposition: form-data; name=\"allow_duplicate\"\r\n\r\n1\r\n"
            f"--{bd}\r\nContent-Disposition: form-data; name=\"image\"; filename=\"load_{i:03d}.jpg\"\r\nContent-Type: image/jpeg\r\n\r\n").encode() + data + f"\r\n--{bd}--\r\n".encode()
    c, d, t = call("POST", "/api/jobs", body, {"Content-Type": "multipart/form-data; boundary=" + bd})
    return c, json.loads(d), t
def start_server():
    env = dict(os.environ, VLM_URL="http://127.0.0.1:9")
    subprocess.Popen(f"cd {D} && exec .venv/bin/python -m uvicorn app.main:app --host 127.0.0.1 --port {PORT} >> /tmp/copy{PORT}.log 2>&1", shell=True, env=env, start_new_session=True)
    for _ in range(60):
        try:
            if call("GET", "/health", timeout=2)[0] == 200: return True
        except Exception: pass
        time.sleep(0.5)
def poll(jobs, samples, t0, stop_when_done=True, until=None):
    while True:
        pid = srv_pid()
        try:
            ch, _, th = call("GET", "/health", timeout=30); cc, dc, tc = call("GET", "/api/cards?status=pending", timeout=60)
            cj_, dj, tj = call("GET", "/api/jobs?ids=" + ",".join(jobs), timeout=30); js = json.loads(dj)["jobs"]
        except Exception as e:
            samples.append({"t": round(time.time() - t0, 1), "error": str(e)}); time.sleep(1); continue
        st = {}
        for x in js: st[x["state"]] = st.get(x["state"], 0) + 1
        samples.append({"t": round(time.time() - t0, 1), "health_ms": round(th * 1000), "cards_ms": round(tc * 1000), "jobs_ms": round(tj * 1000), "rss_mb": rss_mb(pid), "states": st, "known": len(js)})
        print(samples[-1], flush=True)
        if until and until(st): return js
        if stop_when_done and st.get("done", 0) + st.get("error", 0) == len(jobs): return js
        time.sleep(2)
res = {"mode": mode, "n": N}
login()
if mode == "load":
    batch = "load-" + str(int(time.time())); t0 = time.time(); rss0 = rss_mb(srv_pid())
    with ThreadPoolExecutor(25) as ex: subs = list(ex.map(lambda i: submit(i, batch), range(N)))
    res["submit_seconds_all"] = round(time.time() - t0, 1); lat = [s[2] for s in subs]
    res["submit_latency_ms"] = {"median": round(statistics.median(lat) * 1000), "max": round(max(lat) * 1000)}
    res["submit_codes"] = {str(c): sum(1 for s in subs if s[0] == c) for c in {s[0] for s in subs}}
    jobs = [s[1]["job"] for s in subs if s[0] == 200]; samples = []
    js = poll(jobs, samples, t0); res["total_seconds"] = round(time.time() - t0, 1)
    res["per_card_seconds"] = round(res["total_seconds"] / max(1, len(jobs)), 2); res["rss_start_mb"] = rss0
    res["rss_peak_mb"] = max(s.get("rss_mb") or 0 for s in samples); res["health_ms_max"] = max(s.get("health_ms", 0) for s in samples)
    res["cards_api_ms_max"] = max(s.get("cards_ms", 0) for s in samples); res["errors"] = [x.get("error") for x in js if x["state"] == "error"]
    res["ahead_reported_last"] = subs[-1][1].get("ahead"); res["samples"] = samples
    res["inbox_left"] = len(os.listdir(os.path.join(D, "data", "inbox")))
else:
    batch = "crash-" + str(int(time.time())); t0 = time.time()
    with ThreadPoolExecutor(10) as ex: subs = list(ex.map(lambda i: submit(i + 500, batch), range(N)))
    jobs = [s[1]["job"] for s in subs if s[0] == 200]; samples = []
    poll(jobs, samples, t0, until=lambda st: st.get("done", 0) >= 4)
    pid = srv_pid(); res["inbox_before_kill"] = len([f for f in os.listdir(os.path.join(D, "data", "inbox")) if f.endswith(".json")])
    os.kill(pid, 9); time.sleep(1); res["killed_pid"] = pid; res["done_before_kill"] = samples[-1]["states"].get("done", 0)
    t1 = time.time(); start_server(); res["restart_seconds"] = round(time.time() - t1, 1); login()
    js = poll(jobs, samples, t0); res["after_restart_states"] = samples[-1]["states"]
    res["recovered_job_ids_still_tracked"] = samples[-1]["known"] == len(jobs)
    c, d, _ = call("GET", "/api/cards"); cards = [x for x in json.loads(d) if x.get("batch") == batch]
    res["cards_in_batch"] = len(cards); res["duplicate_filenames"] = len(cards) - len({x["filename"] for x in cards})
    res["inbox_left"] = len(os.listdir(os.path.join(D, "data", "inbox"))); res["samples"] = samples
out = os.environ.get("OUT", f"/workspace/gac-card-scanner/audits/raw/{mode}_test.json"); json.dump(res, open(out, "w"), indent=1)
print(json.dumps({k: v for k, v in res.items() if k != "samples"}, indent=1))
