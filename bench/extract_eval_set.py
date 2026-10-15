"""Turn the pilot's approved cards into a labelled test set for bench/eval_bench.py, and report what reviewers corrected.

Reads the app's database READ-ONLY (it never changes cards, history or settings). For every approved card whose photo is still
kept, the approved fields become the expected answer ("ground truth") and the photo is copied next to a gt.json in the same
format bench/eval_bench.py reads. Unlike the app's built-in capture (Admin > Settings > "Keep corrected cards as test
examples", app/ui.py save_correction), this works on cards approved before that setting was on, and it also keeps cards that
were approved UNCHANGED: without them the set holds only the parser's failures and every accuracy number is biased low.

Usage (with the app stopped or running; reads only):
    python bench/extract_eval_set.py --data-dir "<data folder>"            # writes <data folder>/corrections (see --out)
    python bench/extract_eval_set.py --data-dir "<data folder>" --dry-run  # report only, copies nothing
    python bench/eval_bench.py "<out>/gt.json" "<out>" --show              # then score the current code on it

Each card is tagged in "cat" (eval_bench prints accuracy per tag):
  pilot       every card from this script
  reviewed    a person approved it on its own page, or edited/confirmed a field   |  bulk  approved only through bulk approve
  edited      a person or an accepted AI suggestion changed at least one field    |  unchanged  approved as the machine read it
Cards are skipped (and counted) when: not approved, photo deleted by retention or on request, personal details removed on
request, or details were merged in from a back photo or another card (those values are not on the front photo, so the
benchmark could never read them).

PRIVACY: the output holds real people's photos and contact details. By default it goes to the folder the app itself uses for
correction examples (<data folder>/corrections), so the app's photo retention and delete-on-request also clean these copies
(photos keep their original file date, so the retention clock is not restarted). Anywhere else, you delete them yourself. The
script refuses to write inside the git repository unless the folder is git-ignored (bench/corrections/ and bench/real/ are).
"""
import argparse, json, os, shutil, sqlite3, subprocess, sys, time
from collections import Counter

ROOT = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
GT_KEYS = ("first_name", "last_name", "title", "company", "department", "emails", "phones", "website", "address")   # = app/ui.py GT_KEYS
CONF_KEY = {"first_name": "name", "last_name": "name"}   # the parser keeps one confidence for both name parts
LOW = 0.6   # the review screen's "needs attention" threshold (bench/eval_bench.py calibration uses the same)


def default_out(data_dir):
    """The app's correction-examples folder for this data folder (app/ui.py CORR), so retention covers the copies."""
    if os.environ.get("CORRECTIONS_DIR"): return os.environ["CORRECTIONS_DIR"]
    if os.path.abspath(data_dir) == os.path.join(ROOT, "data"): return os.path.join(ROOT, "bench", "corrections")
    return os.path.join(data_dir, "corrections")


def inside_repo_unignored(path):
    """True when path is inside this git checkout and git would track files there (real cards must never be committed)."""
    p = os.path.abspath(path)
    if os.path.commonpath([p, ROOT]) != ROOT: return False
    probe = os.path.join(os.path.relpath(p, ROOT), "probe.jpg")
    try: r = subprocess.run(["git", "-C", ROOT, "check-ignore", "-q", probe], capture_output=True, timeout=10)
    except (OSError, subprocess.SubprocessError): return True   # can't ask git: assume tracked
    return r.returncode != 0   # 0 = ignored


def gt_entry(f):
    """Approved fields -> one eval_bench ground-truth record (same shape as app/ui.py save_correction)."""
    g = {k: f.get(k) or ([] if k in ("emails", "phones") else "") for k in GT_KEYS}
    g["phones"] = [{"type": p.get("type", "work"), "number": p.get("number", "")} for p in f.get("phones") or [] if isinstance(p, dict)]
    return g


def norm(k, v):
    if k == "phones": return sorted("".join(ch for ch in str(p.get("number", "")) if ch.isdigit()) for p in v or [] if isinstance(p, dict))
    if k == "emails": return sorted(str(x).strip().casefold() for x in v or [])
    return " ".join(str(v or "").split()).casefold()


def load(con, since=None, batch=None):
    meta = {r["card_id"]: dict(r) for r in con.execute("SELECT * FROM card_meta")}
    hist = {}
    for r in con.execute("SELECT card_id, reviewer, action, from_status, to_status, detail FROM card_history ORDER BY id"):
        d = r["detail"]
        try: d = json.loads(d) if d else {}
        except ValueError: d = {}
        hist.setdefault(r["card_id"], []).append((r["action"], r["to_status"], d if isinstance(d, dict) else {}))
    q, a = "SELECT * FROM cards WHERE status='approved'", []
    if since: q += " AND created>=?"; a.append(since)
    cards = [dict(r) for r in con.execute(q + " ORDER BY id", a)]
    if batch: cards = [c for c in cards if (meta.get(c["id"]) or {}).get("batch_label") == batch or (meta.get(c["id"]) or {}).get("batch") == batch]
    return cards, meta, hist


def card_record(c, m, h):
    """(skip_reason, None) or (None, record) for one approved card."""
    if any(d.get("redacted") for _, _, d in h) or any(a == "deleted_on_request" for a, _, _ in h): return "details removed on request", None
    if m.get("image_deleted") or not c.get("image"): return "photo deleted", None
    if m.get("back_image") or any(a in ("back_added", "merged_from") for a, _, _ in h): return "details from a back photo or another card", None
    try: f = json.loads(c["fields"] or "{}")
    except ValueError: return "unreadable fields", None
    src = {}
    try: src = json.loads(m.get("field_sources") or "{}") or {}
    except ValueError: pass
    machine = {}   # what the scan produced: the first "from" of every edited field (edits are logged as {field: {from, to}})
    for a, _, d in h:
        if a != "edited": continue
        for k, v in d.items():
            if isinstance(v, dict) and "from" in v and k not in machine: machine[k] = v["from"]
    changed = sorted(k for k in GT_KEYS if k in machine and norm(k, machine[k]) != norm(k, f.get(k)))
    by_ai = sorted(k for k in changed if str(src.get(k, "")).startswith("ai"))
    decisions = [d for a, to, d in h if a == "decision" and to == "approved"]
    looked = any(not d.get("bulk") for d in decisions) or bool(machine) or any(str(v).startswith(("edited", "confirmed")) for v in src.values())
    conf = f.get("confidence") or {}
    rec = {"gt": gt_entry(f) | {"cat": ["pilot", "reviewed" if looked else "bulk", "edited" if changed else "unchanged"],
                                "corrected_fields": changed, "card_id": c["id"], "saved": time.time()},
           "fields": {k: {"changed": k in changed, "by_ai": k in by_ai, "empty": not norm(k, f.get(k)) and not norm(k, machine.get(k)),
                          "conf": conf.get(CONF_KEY.get(k, k))} for k in GT_KEYS}}
    return None, rec


def report(recs, skipped, out=None):
    pr = lambda *a: print(*a, file=out or sys.stdout)
    n = len(recs); cats = Counter(t for r in recs for t in r["gt"]["cat"])
    pr(f"Approved cards usable as test examples: {n}   (reviewed {cats['reviewed']}, bulk-approved {cats['bulk']}; "
       f"edited {cats['edited']}, unchanged {cats['unchanged']})")
    for why, k in skipped.most_common(): pr(f"  skipped {k}: {why}")
    if not n: return {}
    pr("\nPer field: how often the approved value differs from what the scan produced (cards where the field is non-empty)")
    pr(f"  {'field':12s} {'cards':>5s} {'fixed':>6s} {'by AI':>6s} {'rate':>6s}   low-confidence (<{LOW}) among fixed / among kept")
    out_ = {}
    for k in GT_KEYS:
        fs = [r["fields"][k] for r in recs if not r["fields"][k]["empty"]]
        fixed = [x for x in fs if x["changed"]]; kept = [x for x in fs if not x["changed"]]
        lo = lambda xs: (sum(1 for x in xs if x["conf"] is not None and x["conf"] < LOW), sum(1 for x in xs if x["conf"] is not None))
        lf, kf = lo(fixed), lo(kept)
        out_[k] = {"cards": len(fs), "fixed": len(fixed), "by_ai": sum(x["by_ai"] for x in fixed),
                   "low_conf_fixed": lf, "low_conf_kept": kf}
        rate = f"{len(fixed) / len(fs):.0%}" if fs else "-"
        pr(f"  {k:12s} {len(fs):5d} {len(fixed):6d} {out_[k]['by_ai']:6d} {rate:>6s}   {lf[0]}/{lf[1]} fixed flagged   {kf[0]}/{kf[1]} kept flagged")
    pr("\nRead: a high 'fixed' rate is where the parser fails most. Good confidence scores flag most fixed fields and few kept ones.")
    if cats["bulk"]: pr("Bulk-approved cards are weaker labels (nobody opened them); compare eval_bench's 'reviewed' and 'bulk' rows.")
    return out_


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--data-dir", default=os.environ.get("GAC_DATA_DIR") or os.path.join(ROOT, "data"),
                    help="the app's data folder (desktop app: Admin > Settings or File > Open data folder)")
    ap.add_argument("--db", help="database file (default: <data-dir>/cards.db, or GAC_DB)")
    ap.add_argument("--uploads", help="photo folder (default: <data-dir>/uploads)")
    ap.add_argument("--out", help="output folder (default: the app's correction-examples folder, <data-dir>/corrections)")
    ap.add_argument("--since", help="only cards scanned on or after this date (YYYY-MM-DD)")
    ap.add_argument("--batch", help="only this batch (its label or id)")
    ap.add_argument("--reviewed-only", action="store_true", help="leave out cards that were only bulk-approved")
    ap.add_argument("--dry-run", action="store_true", help="print the report; copy nothing")
    a = ap.parse_args(argv)
    db = a.db or os.environ.get("GAC_DB") or os.path.join(a.data_dir, "cards.db")
    up = a.uploads or os.path.join(a.data_dir, "uploads")
    out = os.path.abspath(a.out or default_out(a.data_dir))
    if not os.path.isfile(db): ap.error(f"no database at {db} (use --data-dir or --db)")
    if not a.dry_run and inside_repo_unignored(out):
        ap.error(f"{out} is inside the git repository and not git-ignored: real cards must never be committed. Use bench/corrections/ or a folder outside the repo.")
    since = time.mktime(time.strptime(a.since, "%Y-%m-%d")) if a.since else None
    con = sqlite3.connect(f"file:{os.path.abspath(db)}?mode=ro", uri=True); con.row_factory = sqlite3.Row
    try: cards, meta, hist = load(con, since, a.batch)
    finally: con.close()
    recs, skipped = [], Counter()
    for c in cards:
        why, rec = card_record(c, meta.get(c["id"]) or {}, hist.get(c["id"], []))
        if not why and not os.path.isfile(os.path.join(up, os.path.basename(c["image"]))): why = "photo file missing"
        if not why and a.reviewed_only and "bulk" in rec["gt"]["cat"]: why = "bulk-approved only (--reviewed-only)"
        if why: skipped[why] += 1; continue
        rec["image"] = c["image"]; rec["name"] = f"card{c['id']}_{((meta.get(c['id']) or {}).get('sha256') or 'nohash')[:8]}{os.path.splitext(c['image'])[1] or '.jpg'}"
        recs.append(rec)
    stats = report(recs, skipped)
    if a.dry_run or not recs: return 0
    os.makedirs(out, exist_ok=True)
    gp = os.path.join(out, "gt.json")
    try:
        with open(gp, encoding="utf-8") as fh: gt = json.load(fh)
    except (FileNotFoundError, ValueError): gt = {}
    for r in recs:   # one entry per card: replaces an earlier extraction or app capture of the same card
        gt = {k: v for k, v in gt.items() if not k.startswith(f"card{r['gt']['card_id']}_")}
        for fn in os.listdir(out):
            if fn.startswith(f"card{r['gt']['card_id']}_") and fn != r["name"] and not fn.endswith(".json"): os.remove(os.path.join(out, fn))
        shutil.copy2(os.path.join(up, os.path.basename(r["image"])), os.path.join(out, r["name"]))   # copy2: keeps the file date (retention)
        gt[r["name"]] = r["gt"]
    with open(gp + ".tmp", "w", encoding="utf-8") as fh: json.dump(gt, fh, indent=1)
    os.replace(gp + ".tmp", gp)
    with open(os.path.join(out, "field_report.json"), "w", encoding="utf-8") as fh: json.dump({"made": time.time(), "cards": len(recs), "fields": stats}, fh, indent=1)
    print(f"\nWrote {len(recs)} card(s) to {out}\nScore the current code on them:  python bench/eval_bench.py \"{gp}\" \"{out}\" --show")
    if os.path.abspath(out) != os.path.abspath(default_out(a.data_dir)):
        print("NOTE: this folder is outside the app's retention and delete-on-request: delete it yourself when you are done.")
    return 0


if __name__ == "__main__": sys.exit(main())
