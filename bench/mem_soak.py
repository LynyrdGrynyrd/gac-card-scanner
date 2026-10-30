"""v0.4.5 #1: memory soak. Starts the app on a throwaway port with a COPY of a data folder, then runs the skeptic's load
(9 loops: sign in every 30 s, 5 GETs every few seconds, plus one sign-in every 3 s) and samples RSS. Fails if RSS keeps
growing after warm-up or passes the cap.
  python bench/mem_soak.py --data /tmp/copy --minutes 30 [--port 8811] [--max-mb 900] [--max-growth-mb 150]
The data folder must be a throwaway copy: the script adds two test users to it."""
import argparse, http.cookiejar, json, os, subprocess, sys, threading, time, urllib.request
ap = argparse.ArgumentParser(); ap.add_argument("--data", required=True); ap.add_argument("--minutes", type=float, default=30)
ap.add_argument("--port", type=int, default=8811); ap.add_argument("--max-mb", type=int, default=900); ap.add_argument("--max-growth-mb", type=int, default=150)
ap.add_argument("--card", action="append", default=[])
a = ap.parse_args(); B = f"http://127.0.0.1:{a.port}"; PW = "soak-pass-12345"
env = dict(os.environ, GAC_DATA_DIR=a.data, VLM_URL="http://127.0.0.1:9", GAC_HOST="127.0.0.1")
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
subprocess.run([sys.executable, "-c", f"from app import auth\nfor u in ('soakrev','soakadm'):\n  try: auth.create_user(u, u, '{PW}', role='admin' if u=='soakadm' else 'reviewer')\n  except Exception: pass"], env=env, cwd=ROOT, check=True)
srv = subprocess.Popen([sys.executable, "-m", "uvicorn", "app.main:app", "--host", "127.0.0.1", "--port", str(a.port)], env=env, cwd=ROOT,
                       stdout=open("/tmp/mem_soak_server.log", "w"), stderr=subprocess.STDOUT)
def rss():
    with open(f"/proc/{srv.pid}/status") as fh: return int(fh.read().split("VmRSS:")[1].split()[0]) // 1024
for _ in range(60):
    try: urllib.request.urlopen(B + "/health", timeout=2); break
    except Exception: time.sleep(1)
end = time.time() + a.minutes * 60; stop = threading.Event(); err = [0]
def login(user="soakrev"):
    cj = http.cookiejar.CookieJar(); op = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(cj))
    op.open(urllib.request.Request(B + "/api/auth/login", data=json.dumps({"username": user, "password": PW}).encode(),
                                   headers={"Content-Type": "application/json", "Origin": B}), timeout=30).read()
    return op
cards = a.card or ["1", "2"]
def poller():
    while not stop.is_set():
        try: op = login()
        except Exception: err[0] += 1; time.sleep(3); continue
        t0 = time.time()
        while time.time() - t0 < 30 and not stop.is_set():
            for p in ["/api/cards?status=pending"] + [f"/api/cards/{c}" for c in cards] + ["/api/exports", "/health"]:
                try: op.open(B + p, timeout=60).read()
                except Exception: err[0] += 1
            time.sleep(6)
def signer():
    while not stop.is_set():
        try: login("soakadm")
        except Exception: err[0] += 1
        time.sleep(3)
ts = [threading.Thread(target=poller, daemon=True) for _ in range(9)] + [threading.Thread(target=signer, daemon=True)]
[t.start() for t in ts]
samples = []
try:
    while time.time() < end:
        time.sleep(15); r = rss(); samples.append(r); print(time.strftime("%H:%M:%S"), r, "MB", flush=True)
        if r > a.max_mb * 2: break
finally:
    stop.set(); srv.kill()
warm = samples[min(len(samples) - 1, 8):]   # after ~2 minutes
growth = (sum(warm[-4:]) / len(warm[-4:])) - (sum(warm[:4]) / len(warm[:4])) if len(warm) >= 8 else 0
print(f"samples={len(samples)} start={samples[0] if samples else 0} max={max(samples or [0])} end={samples[-1] if samples else 0} growth_after_warmup={growth:.0f} MB errors={err[0]}")
ok = samples and max(samples) <= a.max_mb and growth <= a.max_growth_mb
print("PASS" if ok else "FAIL"); sys.exit(0 if ok else 1)
