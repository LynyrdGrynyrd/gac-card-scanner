"""How useful are the cross-field consistency flags? For each benchmark card: which fields were flagged, and were they wrong.
   python bench/consistency_report.py bench/real_gt.json bench/real"""
import json, os, re, sys, unicodedata
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
from app import pipeline
def n(s): return re.sub(r"[^a-z0-9@]", "", unicodedata.normalize("NFKD", s or "").encode("ascii", "ignore").decode().lower().replace("www.", "").replace("https://", "").replace("http://", ""))
def dig(s): return re.sub(r"\D", "", s or "")
gt = json.load(open(sys.argv[1])); d = sys.argv[2]; stats = {"cards": 0, "flags": 0, "flag_true": 0, "flag_false": 0, "boosted_right": 0, "boosted_wrong": 0}; ex = []
for fn, g in gt.items():
    p = os.path.join(d, fn)
    if not os.path.isfile(p): continue
    f = pipeline.scan(open(p, "rb").read(), use_vlm=False)["fields"]; stats["cards"] += 1
    right = {"name": n(f["first_name"]) == n(g.get("first_name")) and n(f["last_name"]) == n(g.get("last_name")),
             "emails": sorted(map(n, f["emails"])) == sorted(map(n, g.get("emails", []))), "website": n(f["website"]) == n(g.get("website")),
             "company": n(f["company"]) == n(g.get("company")), "address": n(f["address"]) == n(g.get("address")),
             "phones": sorted(dig(x["number"])[-7:] for x in f["phones"]) == sorted(dig(x["number"])[-7:] for x in g.get("phones", []))}
    for fl in f.get("consistency", []):
        stats["flags"] += 1; bad = any(not right.get(k, True) for k in fl["fields"])
        stats["flag_true" if bad else "flag_false"] += 1; ex.append((fn, fl["code"], "caught an error" if bad else "false alarm", fl["text"]))
    for k, v in (f.get("consistency_notes") or {}).items():
        if v == "match":
            ks = {"email_web": ["emails", "website"], "email_company": ["company"], "email_name": ["name"], "area_state": ["phones", "address"]}[k]
            stats["boosted_right" if all(right.get(x, True) for x in ks) else "boosted_wrong"] += 1
print(json.dumps(stats, indent=1))
for e in ex: print(" ", *e)
