"""Benchmark: per-field + per-category accuracy. Usage: python eval_bench.py real_gt.json real [--engine X] [--show]"""
import json, os, re, sys, time, unicodedata
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
from app import pipeline
gt_path, img_dir = sys.argv[1], sys.argv[2]; show = "--show" in sys.argv
only = [a.split("=",1)[1] for a in sys.argv if a.startswith("--only=")]
def n(s):
    s = unicodedata.normalize("NFKD", s or "").encode("ascii", "ignore").decode().lower()
    s = s.replace("https://","").replace("http://","").replace("www.","")
    return re.sub(r"[^a-z0-9@]", "", s)
def dig(s): return re.sub(r"\D", "", s or "")
def ph_eq(a, b):
    a, b = dig(a), dig(b); k = min(len(a), len(b), 9)
    return bool(a) and bool(b) and min(len(a), len(b)) >= 5 and a[-k:] == b[-k:]
FIELDS = ["first_name","last_name","title","company","department","emails","phones","phone_types","website","address"]
calib = {"wrong": 0, "wrong_flagged": 0, "right": 0, "right_flagged": 0}
gt = json.load(open(gt_path)); tot = {f: [0,0] for f in FIELDS}; cats = {}; rows = []; t0 = time.time()
for fn, g in gt.items():
    if only and fn not in only: continue
    if not os.path.isfile(os.path.join(img_dir, fn)): continue   # e.g. a correction photo removed by retention
    vr = None
    if "--vlm" in sys.argv:
        cp = os.path.join(os.getenv("VLM_CACHE_DIR") or os.path.join(os.path.dirname(os.path.abspath(__file__)), "vlm_cache"), fn + ".json")
        vr = json.load(open(cp)) if os.path.exists(cp) else None
        if vr is None and "--vlm-live" not in sys.argv: continue
    f = pipeline.scan(open(os.path.join(img_dir, fn), "rb").read(), use_vlm=("--vlm-live" in sys.argv), vlm_result=vr)["fields"]
    r = {}
    for k in ["first_name","last_name","title","company","department","website","address"]: r[k] = n(f.get(k)) == n(g.get(k,""))
    r["emails"] = sorted(map(n, f["emails"])) == sorted(map(n, g.get("emails", [])))
    gp, fp = g.get("phones", []), f["phones"]
    r["phones"] = len(gp) == len(fp) and all(any(ph_eq(x["number"], y["number"]) for y in fp) for x in gp)
    r["phone_types"] = r["phones"] and all(any(ph_eq(x["number"], y["number"]) and (x["type"] == y["type"] or (x["type"] in ("home",) and y["type"] == "work")) for y in fp) for x in gp)
    cf = f.get("confidence", {})
    ck = {"first_name": "name", "last_name": "name", "phone_types": "phones"}
    for k, v in r.items():
        c = cf.get(ck.get(k, k))
        if c is not None or not v:
            flagged = c is None or c < 0.6
            if not v and (f.get(k) or k == "phone_types"): calib["wrong"] += 1; calib["wrong_flagged"] += flagged
            elif v and c is not None: calib["right"] += 1; calib["right_flagged"] += flagged
    for k, v in r.items():
        tot[k][0] += v; tot[k][1] += 1
        for c in g.get("cat", []): cats.setdefault(c, [0,0]); cats[c][0] += v; cats[c][1] += 1
    miss = {k: (f.get(k) if k != "phone_types" else [(p["type"], p["number"]) for p in fp]) for k, v in r.items() if not v}
    rows.append((fn, sum(r.values()), len(r), miss, {k: g.get(k) for k in miss if k != "phone_types"}))
for fn, a, b, m, e in rows:
    print(f"{fn}: {a}/{b}")
    if show:
        for k in m: print(f"    {k}: got={m[k]!r}  want={e.get(k)!r}")
print("\nPer-field:"); A = B = 0
for k, (a, b) in tot.items(): print(f"  {k:12s} {a}/{b} = {a/max(b,1):.0%}"); A += a; B += b
print(f"OVERALL {A}/{B} = {A/max(B,1):.1%}   ({(time.time()-t0)/max(len(rows),1):.1f}s/card)")
print(f"Calibration: wrong non-empty fields flagged <0.6: {calib['wrong_flagged']}/{calib['wrong']}; correct fields falsely flagged: {calib['right_flagged']}/{calib['right']}")
print("\nPer-category:")
for c, (a, b) in sorted(cats.items(), key=lambda x: x[1][0]/x[1][1]): print(f"  {c:22s} {a}/{b} = {a/b:.0%}")
