"""Field-level accuracy of OCR+parser vs ground truth. Exact match after light normalization."""
import json, os, re, sys
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from app import ocr, parser
D = os.path.dirname(__file__); gt = json.load(open(os.path.join(D, "ground_truth.json")))
n = lambda s: re.sub(r"[^a-z0-9@]", "", (s or "").lower().replace("https://","").replace("www.",""))
FIELDS = ["first_name","last_name","title","company","department","other_address","emails","phones","phone_types","website","address","social"]
tot = {f: [0,0] for f in FIELDS}; rows = []
for fn, g in gt.items():
    f = parser.parse(*(lambda r: (r["text"], r.get("lines")))(ocr.run_ocr(open(os.path.join(D,"cards",fn),"rb").read())))
    res = {}
    for k in ["first_name","last_name","title","company","department","other_address","website","address"]: res[k] = n(f[k]) == n(g.get(k,""))
    res["emails"] = sorted(map(n,f["emails"])) == sorted(map(n,g["emails"]))
    res["phones"] = sorted(n(p["number"]) for p in f["phones"]) == sorted(n(p["number"]) for p in g["phones"])
    res["phone_types"] = sorted((p["type"],n(p["number"])) for p in f["phones"]) == sorted((p["type"],n(p["number"])) for p in g["phones"])
    res["social"] = sorted(map(n,f["social"])) == sorted(map(n,g["social"]))
    for k,v in res.items(): tot[k][0] += v; tot[k][1] += 1
    miss = {k: (f[k] if k!="phone_types" else f["phones"]) for k,v in res.items() if not v and k!="phone_types"}
    rows.append((fn, sum(res.values()), len(res), miss))
for fn,a,b,m in rows: print(f"{fn}: {a}/{b}  misses={m}")
syn = [r for r in rows if not r[0].startswith("real")]; real = [r for r in rows if r[0].startswith("real")]
for lab, rs in (("synthetic", syn), ("real", real)):
    if rs: print(f"{lab}: {sum(r[1] for r in rs)}/{sum(r[2] for r in rs)}")
print("\nPer-field accuracy:")
for k,(a,b) in tot.items(): print(f"  {k:12s} {a}/{b}")
A = sum(a for a,b in tot.values()); B = sum(b for a,b in tot.values()); print(f"OVERALL {A}/{B} = {A/B:.0%}")
