"""Benchmark: per-field + per-category accuracy.
Usage: python bench/eval_bench.py [gt.json img_dir] [--show] [--only=FILE] [--vlm|--vlm-live] [--min FIELD=COUNT ...] [--min-overall PCT]
(no paths: tests/synth2_gt.json tests/synth2). Exit code 1 when below a --min / --min-overall threshold, 2 when no card could be scored.
Audit 2026-10 (F12): Unicode-aware text comparison (different Japanese names no longer both normalise to ""), phones compared on all
digits (a 10-digit US number equals its +1 form; other country codes must match), emails exact (case-insensitive), list fields matched
one-to-one, and photos missing from img_dir are counted and reported instead of silently skipped."""
import argparse, json, os, re, sys, time, unicodedata
from itertools import permutations
ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
sys.path.insert(0, ROOT)
FIELDS = ["first_name","last_name","title","company","department","emails","phones","phone_types","website","address"]

def n(s):
    s = unicodedata.normalize("NFKC", s or "").casefold()
    s = s.replace("https://","").replace("http://","").replace("www.","")
    return "".join(ch for ch in s if ch.isalnum())
def dig(s): return re.sub(r"\D", "", s or "")
def ph_key(s):
    """(national digits, extension): '+1 330-555-0101' == '330.555.0101'; '+44 …' != '+49 …'"""
    m = re.match(r"(.*?)\s*(?:ext\.?|x|#)\s*(\d+)\s*$", s or "", re.I)
    main, ext = (m.group(1), m.group(2)) if m and len(dig(m.group(1))) >= 7 else (s or "", "")
    d = dig(main)
    if len(d) == 11 and d.startswith("1"): d = d[1:]
    return d, ext
def ph_eq(a, b):
    ka, kb = ph_key(a), ph_key(b)
    return len(ka[0]) >= 5 and ka == kb
def em_eq(a, b): return (a or "").strip().casefold() == (b or "").strip().casefold()
def one_to_one(gl, fl, eq):
    """every expected item matched to its own found item, nothing extra"""
    if len(gl) != len(fl): return False
    if len(fl) <= 7: return any(all(eq(x, y) for x, y in zip(gl, p, strict=True)) for p in permutations(fl))
    left = list(fl)
    for x in gl:
        y = next((y for y in left if eq(x, y)), None)
        if y is None: return False
        left.remove(y)
    return True
def type_ok(x, y): return x["type"] == y["type"] or (x["type"] == "home" and y["type"] == "work")

def compare(f, g):
    r = {}
    for k in ["first_name","last_name","title","company","department","website","address"]: r[k] = n(f.get(k)) == n(g.get(k, ""))
    r["emails"] = one_to_one(g.get("emails", []), f.get("emails") or [], em_eq)
    gp, fp = g.get("phones", []), f.get("phones") or []
    r["phones"] = one_to_one(gp, fp, lambda x, y: ph_eq(x["number"], y["number"]))
    r["phone_types"] = r["phones"] and one_to_one(gp, fp, lambda x, y: ph_eq(x["number"], y["number"]) and type_ok(x, y))
    return r

def main(argv=None):
    ap = argparse.ArgumentParser(description="per-field accuracy of pipeline.scan against a ground-truth JSON")
    ap.add_argument("gt", nargs="?", default=os.path.join(ROOT, "tests", "synth2_gt.json"))
    ap.add_argument("img_dir", nargs="?", default=os.path.join(ROOT, "tests", "synth2"))
    ap.add_argument("--show", action="store_true"); ap.add_argument("--only", action="append", default=[])
    ap.add_argument("--vlm", action="store_true"); ap.add_argument("--vlm-live", action="store_true")
    ap.add_argument("--min", action="append", default=[], metavar="FIELD=COUNT", help="fail when FIELD has fewer correct cards")
    ap.add_argument("--min-overall", type=float, metavar="PCT", help="fail when overall accuracy is below PCT percent")
    a = ap.parse_args(argv)
    mins = {}
    for m in a.min:
        k, _, c = m.partition("=")
        if k not in FIELDS or not c.isdigit(): ap.error(f"--min {m}: expected FIELD=COUNT with FIELD in {', '.join(FIELDS)}")
        mins[k] = int(c)
    from app import pipeline
    calib = {"wrong": 0, "wrong_flagged": 0, "right": 0, "right_flagged": 0}
    gt = json.load(open(a.gt)); tot = {f: [0,0] for f in FIELDS}; cats = {}; rows = []; t0 = time.time()
    missing, no_cache = [], []
    for fn, g in gt.items():
        if a.only and fn not in a.only: continue
        if not os.path.isfile(os.path.join(a.img_dir, fn)): missing.append(fn); continue   # e.g. a correction photo removed by retention
        vr = None
        if a.vlm:
            cp = os.path.join(os.getenv("VLM_CACHE_DIR") or os.path.join(os.path.dirname(os.path.abspath(__file__)), "vlm_cache"), fn + ".json")
            vr = json.load(open(cp)) if os.path.exists(cp) else None
            if vr is None and not a.vlm_live: no_cache.append(fn); continue
        f = pipeline.scan(open(os.path.join(a.img_dir, fn), "rb").read(), use_vlm=a.vlm_live, vlm_result=vr)["fields"]
        r = compare(f, g); fp = f.get("phones") or []
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
    for fn, x, y, m, e in rows:
        print(f"{fn}: {x}/{y}")
        if a.show:
            for k in m: print(f"    {k}: got={m[k]!r}  want={e.get(k)!r}")
    print("\nPer-field:"); A = B = 0
    for k, (x, y) in tot.items(): print(f"  {k:12s} {x}/{y} = {x/max(y,1):.0%}"); A += x; B += y
    print(f"OVERALL {A}/{B} = {A/max(B,1):.1%}   ({(time.time()-t0)/max(len(rows),1):.1f}s/card)")
    print(f"Calibration: wrong non-empty fields flagged <0.6: {calib['wrong_flagged']}/{calib['wrong']}; correct fields falsely flagged: {calib['right_flagged']}/{calib['right']}")
    print("\nPer-category:")
    for c, (x, y) in sorted(cats.items(), key=lambda kv: kv[1][0]/kv[1][1]): print(f"  {c:22s} {x}/{y} = {x/y:.0%}")
    if missing: print(f"\nSKIPPED {len(missing)} card(s): photo missing from {a.img_dir}: {', '.join(missing[:10])}{' …' if len(missing) > 10 else ''}")
    if no_cache: print(f"SKIPPED {len(no_cache)} card(s): no cached AI answer (--vlm): {', '.join(no_cache[:10])}{' …' if len(no_cache) > 10 else ''}")
    fails = [f"{k} {tot[k][0]} < {c}" for k, c in mins.items() if tot[k][0] < c]
    if a.min_overall is not None and 100 * A / max(B, 1) < a.min_overall: fails.append(f"overall {100*A/max(B,1):.1f}% < {a.min_overall}%")
    if fails: print("BELOW THRESHOLD: " + "; ".join(fails)); return 1
    if not rows: print("NO CARDS SCORED"); return 2
    return 0

if __name__ == "__main__": sys.exit(main())
