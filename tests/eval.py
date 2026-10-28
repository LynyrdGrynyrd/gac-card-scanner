"""Field-level accuracy of the production pipeline (pipeline.scan, rules only) vs ground truth. Exact match after light normalization.
Usage: python tests/eval.py [--min COUNT | --min FIELD=COUNT ...]   (exit code 1 when below a threshold)
Audit 2026-10 (F12): runs pipeline.scan(use_vlm=False) (QR, card-crop pass, consistency, post-fixes) instead of ocr + parser."""
import argparse, json, os, sys, unicodedata
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from app import pipeline
D = os.path.dirname(__file__); gt = json.load(open(os.path.join(D, "ground_truth.json")))
def n(s):
    s = unicodedata.normalize("NFKC", s or "").casefold().replace("https://", "").replace("www.", "")
    return "".join(ch for ch in s if ch.isalnum() or ch == "@")
FIELDS = ["first_name","last_name","title","company","department","other_address","emails","phones","phone_types","website","address","social"]
ap = argparse.ArgumentParser(); ap.add_argument("--min", action="append", default=[], metavar="COUNT|FIELD=COUNT")
a = ap.parse_args()
tot = {f: [0,0] for f in FIELDS}; rows = []
for fn, g in gt.items():
    f = pipeline.scan(open(os.path.join(D,"cards",fn),"rb").read(), use_vlm=False)["fields"]
    res = {}
    for k in ["first_name","last_name","title","company","department","other_address","website","address"]: res[k] = n(f.get(k)) == n(g.get(k,""))
    res["emails"] = sorted(map(n,f["emails"])) == sorted(map(n,g["emails"]))
    res["phones"] = sorted(n(p["number"]) for p in f["phones"]) == sorted(n(p["number"]) for p in g["phones"])
    res["phone_types"] = sorted((p["type"],n(p["number"])) for p in f["phones"]) == sorted((p["type"],n(p["number"])) for p in g["phones"])
    res["social"] = sorted(map(n,f.get("social") or [])) == sorted(map(n,g["social"]))
    for k,v in res.items(): tot[k][0] += v; tot[k][1] += 1
    miss = {k: (f.get(k) if k!="phone_types" else f["phones"]) for k,v in res.items() if not v and k!="phone_types"}
    rows.append((fn, sum(res.values()), len(res), miss))
for fn,x,y,m in rows: print(f"{fn}: {x}/{y}  misses={m}")
syn = [r for r in rows if not r[0].startswith("real")]; real = [r for r in rows if r[0].startswith("real")]
for lab, rs in (("synthetic", syn), ("real", real)):
    if rs: print(f"{lab}: {sum(r[1] for r in rs)}/{sum(r[2] for r in rs)}")
print("\nPer-field accuracy:")
for k,(x,y) in tot.items(): print(f"  {k:12s} {x}/{y}")
A = sum(x for x,y in tot.values()); B = sum(y for x,y in tot.values()); print(f"OVERALL {A}/{B} = {A/B:.0%}")
fails = []
for m in a.min:
    k, _, c = m.rpartition("=")
    if not c.isdigit() or (k and k not in tot): ap.error(f"--min {m}: expected COUNT or FIELD=COUNT")
    if (tot[k][0] if k else A) < int(c): fails.append(f"{k or 'overall'} {tot[k][0] if k else A} < {c}")
# v0.4.6 #5: misread detection (a digit inside a word, '|' in a title/department) must block approval; real digits must not
import tempfile
from app import store as _store; _store.DB = os.path.join(tempfile.mkdtemp(prefix="gac-eval-"), "eval.db")   # never the real cards.db
from app import ui as _ui
MIS = [("company", "Rubb3r City Robotics", 1), ("company", "Kent Partn3rs", 1), ("department", "L3gal", 1), ("title", "Own3r 4", 1),
       ("first_name", "Morg4n", 1), ("department", "Acc|ounts", 1), ("title", "Vice Pres|dent", 1), ("title", "Ex3cutive Director", 1),
       ("company", "3M", 0), ("company", "B2B Sales Co", 0), ("company", "21st Century Insurance", 0), ("company", "7-Eleven", 0),
       ("department", "Level 3 Support", 0), ("company", "H2O Labs", 0), ("first_name", "Morgan", 0),
       # v0.4.7 #6: real names with digits and a '|' separator pass; mid-word '|' and look-alikes with a close fix are still caught
       ("company", "4imprint", 0), ("company", "E2open", 0), ("company", "4thought Marketing", 0), ("company", "Q3 Partners", 0),
       ("title", "Manager | Sales", 0), ("title", "Manag|ng Director", 1), ("department", "Sa|es", 1), ("company", "Rnbber City Robotics", 1),
       # v0.4.8 #9: '4ward' / 'Owner|Founder' are real; 'Vlce', 'Managr', 'Rnbert', '4nalytics' are misreads
       ("company", "4ward Logistics", 0), ("title", "Owner|Founder", 0), ("company", "2go Couriers", 0), ("first_name", "Robert", 0),
       ("title", "Vlce President", 1), ("title", "Sales Managr", 1), ("first_name", "Rnbert", 1), ("last_name", "Rnbert", 1),
       ("company", "4nalytics Group", 1), ("title", "Seninr Director", 1), ("title", "Vice President", 0)]
mok = 0
for fld, val, want in MIS:
    e = _ui.hard_errors({"first_name": "Ann", "last_name": "Lee", "emails": ["a@b.example.com"], "phones": [], fld: val})
    got = int(("name" if fld == "first_name" else fld) in e); mok += got == want
    if got != want: print(f"  MISREAD CHECK WRONG: {fld}={val!r} flagged={bool(got)} expected={bool(want)}")
print(f"Misread detection {mok}/{len(MIS)}")
if mok < len(MIS): fails.append(f"misread detection {mok} < {len(MIS)}")
if fails: print("BELOW THRESHOLD: " + "; ".join(fails)); sys.exit(1)
