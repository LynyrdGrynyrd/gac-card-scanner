"""Permanent delete on request, its tombstones, photo/export retention and the memory clean-up. Split out of app/ui.py (audit 2026-10 P2)."""
import os, csv, json, time, sqlite3
from fastapi import Body, HTTPException, Request
from fastapi.responses import JSONResponse
from . import store, auth
from . import ui as U

@U.router.post("/api/admin/cards/{cid}/delete")
def hard_delete(cid: U.CardId, request: Request, body: dict = Body(default={})):
    """Removal request: delete the card, its photo, metadata, history and any undo snapshots holding its data.
    Exported files already downloaded are outside the app; stored export copies containing it are deleted too."""
    if body.get("confirm") != cid: return JSONResponse({"error": "Confirm by sending {\"confirm\": <card id>}."}, 422)
    # audit 2026-10 P0-5: under WRITE_LOCK (a save that already passed its version check can't write merged values back),
    # database first and in ONE transaction together with its audit rows, files after the commit, VACUUM last and optional
    with U.WRITE_LOCK: return _hard_delete(cid, request.state.user)

TOMBSTONES = os.path.join(U.DATA, "deleted_cards.json")
def _tombstones():
    try:
        with open(TOMBSTONES) as fh: return {int(k): v for k, v in json.load(fh).items()}
    except (FileNotFoundError, ValueError): return {}
def _add_tombstone(cid, created=None):
    """Audit 2026-10 P1 (F07): remember every card deleted on request, so restoring an older backup can't bring it back
    (backup.restore keeps this file; apply_tombstones() deletes such cards again at the next start)."""
    t = _tombstones(); t[cid] = {"deleted": time.time(), "created": created}; tmp = TOMBSTONES + ".tmp"
    with open(tmp, "w") as fh: json.dump({str(k): v for k, v in t.items()}, fh)
    os.replace(tmp, TOMBSTONES)
def apply_tombstones():
    # the card's scan time must match too, so a tombstone can never hit a different card that got the same number
    gone = [cid for cid, v in _tombstones().items() if (c := store.get(cid)) and (not isinstance(v, dict) or v.get("created") in (None, c["created"]))]
    for cid in gone:
        with U.WRITE_LOCK: _hard_delete(cid, {"initials": "SYS", "username": "restore"})
    if gone: auth.alog("restore", f"deleted {len(gone)} card(s) again that had been deleted on request before the restored backup was made: " + ", ".join(f"#{i}" for i in gone))
    return gone

def _hard_delete(cid, user):
    from . import exporting
    c = store.get(cid)
    if not c: raise HTTPException(404, "Card not found")
    photos = [c.get("image"), U.meta(cid).get("back_image")]
    if os.path.isdir(U.CORR):
        for fn in os.listdir(U.CORR):
            if fn.startswith(f"card{cid}_"): os.remove(os.path.join(U.CORR, fn))
        gp = os.path.join(U.CORR, "gt.json")
        if os.path.isfile(gp):
            with open(gp) as fh: gt = json.load(fh)
            with open(gp, "w") as fh: json.dump({k: v for k, v in gt.items() if not k.startswith(f"card{cid}_")}, fh, indent=1)
    removed_exports = 0; removed_merged = 0; export_files = []
    x0 = U.db(); x0.execute("PRAGMA secure_delete=ON")   # overwrite freed pages so the text can't be recovered from the file
    with x0 as x:
        x.execute("DELETE FROM cards WHERE id=?", (cid,)); x.execute("DELETE FROM card_meta WHERE card_id=?", (cid,))
        # Audit rows are KEPT for accountability (who scanned/edited/approved/exported it and when); only the personal
        # data inside them is removed. Statuses, reviewer initials, time and card number stay (PRIVACY-NOTE.md).
        for h in x.execute("SELECT id, action, detail FROM card_history WHERE card_id=?", (cid,)).fetchall():
            x.execute("UPDATE card_history SET detail=? WHERE id=?", (json.dumps(_redact(h["action"], h["detail"])), h["id"]))
        targets = {}   # card that received this card's details -> (merge time, values copied)
        for h in x.execute("SELECT id, card_id, ts, action, detail FROM card_history WHERE action IN ('merged_from','back_added')").fetchall():
            try: dd = json.loads(h["detail"] or "{}")
            except Exception: continue
            if isinstance(dd, dict) and h["action"] == "merged_from" and dd.get("card") == cid and dd.get("added"):
                removed_merged += _unmerge(x, h["card_id"], dd["added"], cid, dd.get("replaced") or {})        # the contact details the merge copied over
                pv = targets.get(h["card_id"]); targets[h["card_id"]] = (min(h["ts"], pv[0]) if pv else h["ts"], (pv[1] if pv else []) + _vals(dd["added"]))
            elif isinstance(dd, dict) and dd.get("from_card") == cid: targets.setdefault(h["card_id"], (h["ts"], []))
            if isinstance(dd, dict) and (dd.get("card") == cid or dd.get("from_card") == cid):   # details copied from it
                x.execute("UPDATE card_history SET detail=? WHERE id=?", (json.dumps({"card": cid, "added": {}, "removed_on_request": True}), h["id"]))
        # chained merges (A -> B, then B -> C): C received A's values through B, so it is a target too
        added_by = {tid: list(v[1]) for tid, v in targets.items()}
        frontier = list(targets)
        while frontier:
            b_ = frontier.pop()
            for h in x.execute("SELECT card_id, ts, detail FROM card_history WHERE action='merged_from' AND ts>=?", (targets[b_][0],)).fetchall():
                try: dd = json.loads(h["detail"] or "{}")
                except Exception: continue
                if not (isinstance(dd, dict) and dd.get("card") == b_ and dd.get("added")) or h["card_id"] in targets or h["card_id"] == cid: continue
                carried = {k: v for k, v in dd["added"].items() if set(_vals({k: v})) & set(added_by[b_])}
                if carried: removed_merged += _unmerge(x, h["card_id"], carried, b_)
                targets[h["card_id"]] = (h["ts"], added_by[b_]); added_by[h["card_id"]] = added_by[b_]; frontier.append(h["card_id"])
        for tid in targets:   # a stored AI suggestion of a target can quote merged values: drop it
            x.execute("UPDATE card_meta SET ai_detail=NULL WHERE card_id=? AND ai_detail IS NOT NULL", (tid,))
        # the merge target's LATER history rows (edits, back-to-pending problems) can quote the merged values: blank them
        for tid, (since, vals) in targets.items():
            for h in x.execute("SELECT id, detail FROM card_history WHERE card_id=? AND ts>=? AND action IN ('edited','back_to_pending','decision')", (tid, since)).fetchall():
                det = h["detail"] or ""; new = det
                for v in vals:
                    if v and len(v) >= 3: new = new.replace(json.dumps(v)[1:-1], "[removed on request]")
                if new != det: x.execute("UPDATE card_history SET detail=? WHERE id=?", (new, h["id"]))
        # undo snapshots: of this card, and of any card its details were merged into (they hold copies of those details)
        for a in x.execute("SELECT id, snapshot FROM actions").fetchall():
            if any(sn["card"]["id"] == cid or sn["card"]["id"] in targets for sn in json.loads(a["snapshot"] or "[]")): x.execute("DELETE FROM actions WHERE id=?", (a["id"],))
        for e in x.execute("SELECT id, ts, stored, card_ids, listed_ids FROM exports WHERE stored IS NOT NULL").fetchall():
            ids_ = json.loads(e["card_ids"] or "[]") + json.loads(e["listed_ids"] or "[]")   # v0.4.12 (review F1): left-out cards too
            if e["listed_ids"] is None and _listed_in_csv(e["stored"], cid): ids_.append(cid)   # exports made before listed_ids
            if cid in ids_ or any(t in ids_ and e["ts"] >= targets[t][0] for t in targets):   # also exports of a merge target made after the merge
                ep = os.path.join(U.EXP, e["stored"]); export_files += [ep] + [ep + "." + n for n in U.COMPANION]
                x.execute("UPDATE exports SET stored=NULL WHERE id=?", (e["id"],)); removed_exports += 1
        # v0.4.12 (review F2): the person's match keys (email, name|company) in the MC Trade export records, and drafts of the card.
        # A key another card of the same export also has stays (it is that person's too).
        mine = exporting.card_keys(c)
        for e in x.execute("SELECT id, card_ids, people FROM exports WHERE people IS NOT NULL").fetchall():
            ppl = json.loads(e["people"] or "[]")
            if not mine & set(ppl): continue
            others = set().union(*[exporting.card_keys(o) for o in (store.get(i) for i in json.loads(e["card_ids"] or "[]") if i != cid) if o])
            x.execute("UPDATE exports SET people=? WHERE id=?", (json.dumps([k for k in ppl if k not in mine or k in others]), e["id"]))
        x.execute("DELETE FROM drafts WHERE card_id=?", (cid,))
        # the audit rows are part of the same transaction: no delete without its record, no record without the delete
        x.execute("INSERT INTO card_history(card_id,ts,reviewer,action,from_status,to_status,detail) VALUES(?,?,?,?,?,?,?)",
                  (cid, time.time(), user["initials"], "deleted_on_request", None, None, json.dumps({"export_copies": removed_exports, "merged_removed": removed_merged})))
        x.execute("INSERT INTO auth_log(ts,username,event,ip) VALUES(?,?,?,?)", (time.time(), user["username"],
                  f"deleted card #{cid} on request (photo, details; history kept without personal data; {removed_exports} stored export file(s))", None))
    _add_tombstone(cid, c.get("created"))
    exporting._IDX_CACHE.update(sig=None, val=None); exporting._PEOPLE_CACHE.clear()   # they held the person's keys
    for ph in photos: U.remove_photo(ph)   # F08: front and back, with their thumbnails
    for q in export_files:
        try: os.remove(q)
        except FileNotFoundError: pass
    try: x0.execute("VACUUM")   # compacts the file so freed pages are gone; best-effort (the delete is already committed)
    except sqlite3.OperationalError as e: print("VACUUM after delete skipped:", e, flush=True)
    finally: x0.close()
    for fn in os.listdir(U.DONE):   # job records (they hold the original file name)
        p_ = os.path.join(U.DONE, fn)
        try:
            with open(p_) as fh: jd = json.load(fh)
            if jd.get("card_id") == cid: os.remove(p_)
        except Exception: pass
    with U.JLOCK:
        for jid in [k for k, j in U.JOBS.items() if (j.get("card") or {}).get("id") == cid]: U.JOBS.pop(jid, None)
    U.AI_WAIT.pop(cid, None)
    return {"deleted": cid, "export_copies_deleted": removed_exports, "merged_details_removed": removed_merged}

def _listed_in_csv(stored, cid):
    """Exports before v0.4.12 have no listed_ids: their extra-columns CSV lists every card of the export (ScanCardID first)."""
    p = os.path.join(U.EXP, stored + ".extra.csv")
    try:
        with open(p, encoding="utf-8-sig", newline="") as fh: return any(r and r[0].strip() == str(cid) for r in csv.reader(fh))
    except OSError: return False

def _redact(action, detail):
    """What is left of a history row's detail after a removal request: no names, contact details, file names or notes."""
    try: d = json.loads(detail) if detail else None
    except Exception: d = None
    out = {"redacted": True}
    if isinstance(d, dict):
        if action == "edited": out["fields"] = sorted(d.keys())
        if action == "decision": out.update({k: True for k in ("bulk",) if d.get(k)}); out.update({"override": True} if d.get("override") else {})
        if action == "merged_from" and d.get("card"): out["card"] = d["card"]
        if action == "duplicate_kept_both" and d.get("cards"): out["cards"] = d["cards"]
        if action in ("exported", "redownloaded") and d.get("export_id"): out["export_id"] = d["export_id"]
        if action == "exported" and d.get("file"): out["file"] = d["file"]   # export file names hold no personal data
        for k in ("why", "undid", "seconds", "after_days"):
            if k in d and action != "back_to_pending": out[k] = d[k]
    elif action == "mc_trade_choice": out["choice"] = d
    return out

def _vals(added):
    out = []
    for k, v in (added or {}).items():
        if k == "phones":   # also the reformatted forms a later edit/export may show (330-555-0181, +13305550181, digits)
            from . import mctrade_export as _mx
            for p in v:
                n_ = p.get("number") or ""; out += [n_, _mx.phone(n_), _mx.phone(n_, "e164"), U._digits(n_)]
        elif isinstance(v, list): out += [str(e) for e in v]
        else: out.append(str(v))
    return out

def _unmerge(x, tid, added, cid, replaced=None):
    """Remove from card tid the values a merge copied in from a card that is being deleted on request."""
    r = x.execute("SELECT fields, note FROM cards WHERE id=?", (tid,)).fetchone()
    if not r: return 0
    f = json.loads(r["fields"]); n = 0
    for k, v in added.items():
        if k == "note":
            nt = (r["note"] or "").replace(f" | From #{cid}: {v}", "").replace(f"From #{cid}: {v}", "").strip(" |")
            x.execute("UPDATE cards SET note=? WHERE id=?", (nt, tid)); n += 1
        elif k == "phones":
            gone = {U._digits(p.get("number")) for p in v}; before = len(f.get("phones") or [])
            f["phones"] = [p for p in f.get("phones") or [] if U._digits(p.get("number")) not in gone]; n += before - len(f["phones"])
        elif isinstance(v, list):
            before = len(f.get(k) or []); f[k] = [e for e in f.get(k) or [] if e not in v]; n += before - len(f[k])
            if isinstance((replaced or {}).get(k), list): f[k] = list((replaced or {})[k]) + f[k]   # round 9: misread emails the merge replaced
        elif f.get(k) == v: f[k] = (replaced or {}).get(k, ""); n += 1   # round 8: a merge may have replaced a flagged value
    x.execute("UPDATE cards SET fields=? WHERE id=?", (json.dumps(f), tid))
    return n

# ---------------------------------------------------------------- retention
def purge(now=None, who="retention"):
    """Delete card photos older than image_retention_days and stored export files older than export_retention_days.
    Card text (the contact details) stays, so approved contacts and the audit trail survive."""
    now = now or time.time(); res = {"images": 0, "exports": 0}
    if auth.get_setting("retention_enabled") != "1": return res
    di = int(auth.get_setting("image_retention_days")); de = int(auth.get_setting("export_retention_days"))
    for r in U.db().execute("SELECT id,image,created FROM cards WHERE image IS NOT NULL AND image!='' AND status!='pending' AND created<?", (now - di * 86400,)).fetchall():
        U.remove_photo(r["image"]); U.remove_photo(U.meta(r["id"]).get("back_image"))   # F08: both sides, with thumbnails
        with U.db() as c: c.execute("UPDATE cards SET image='' WHERE id=?", (r["id"],))
        U.set_meta(r["id"], image_deleted=now); U.log(r["id"], who, "photo_deleted", detail={"after_days": di}); res["images"] += 1
    for r in U.db().execute("SELECT id,stored,ts FROM exports WHERE stored IS NOT NULL AND ts<?", (now - de * 86400,)).fetchall():
        p = os.path.join(U.EXP, r["stored"])
        for q in [p] + [p + "." + n for n in U.COMPANION]:
            try: os.remove(q)
            except FileNotFoundError: pass
        with U.db() as c: c.execute("UPDATE exports SET stored=NULL WHERE id=?", (r["id"],))
        res["exports"] += 1
    # undo snapshots hold full copies of card data but can only be used for 24 h: drop them after 2 days
    with U.db() as c: res["undo_snapshots"] = c.execute("UPDATE actions SET snapshot='[]' WHERE ts<? AND snapshot!='[]'", (now - 2 * 86400,)).rowcount
    # orphan photos (e.g. an upload that crashed before its card was saved) follow the same retention clock
    known = {r[0] for r in U.db().execute("SELECT image FROM cards WHERE image!=''")} | {r[0] for r in U.db().execute("SELECT back_image FROM card_meta WHERE back_image IS NOT NULL")}
    # labelled correction photos follow the photo retention too (the benchmark keeps only what is still allowed)
    if os.path.isdir(U.CORR):
        for fn in os.listdir(U.CORR):
            fp = os.path.join(U.CORR, fn)
            if not fn.endswith(".json") and os.path.getmtime(fp) < now - di * 86400 and os.path.getmtime(fp) < now - 3600:
                os.remove(fp); res["corrections"] = res.get("corrections", 0) + 1
    for fn in os.listdir(U.UP):
        fp = os.path.join(U.UP, fn)
        if fn not in known and os.path.isfile(fp) and os.path.getmtime(fp) < now - di * 86400 and os.path.getmtime(fp) < now - 3600:
            U.remove_photo(fn); res["orphans"] = res.get("orphans", 0) + 1
    for fn in os.listdir(U.THUMBS):   # F08: thumbnails whose photo is gone (e.g. deleted by an older version)
        base = fn.rsplit(".", 2)[0] if fn.endswith(".webp") else None
        if base and base not in known and not os.path.isfile(os.path.join(U.UP, base)):
            try: os.remove(os.path.join(U.THUMBS, fn)); res["orphan_thumbs"] = res.get("orphan_thumbs", 0) + 1
            except FileNotFoundError: pass
    if res["images"] or res["exports"] or res.get("orphans"): auth.alog(who, f"retention purge: {res['images']} photo(s), {res['exports']} export file(s) deleted")
    return res

JOB_KEEP_S = int(os.environ.get("JOB_KEEP_S", "7200"))
def prune_memory(now=None):
    """Audit 2026-10 P1 (F05): finished jobs and old throttle entries no longer pile up in memory for the whole uptime.
    A finished job is still found through its record in data/jobs_done (24 h) after it leaves memory."""
    from . import reader, phone
    now = now or time.time(); n = 0
    with U.JLOCK:
        for jid in [k for k, j in U.JOBS.items() if j.get("state") in ("done", "error", "cancelled") and (j.get("finished") or j.get("created") or 0) < now - JOB_KEEP_S]:
            U.JOBS.pop(jid, None); n += 1
        for k in [k for k, t in U.CANCELLED_BATCH.items() if t < now - 3600]: U.CANCELLED_BATCH.pop(k, None)
        reader.CANCELLED.intersection_update(set(U.JOBS) | set(reader.RUNNING))
    for cid in [c for c in list(U.AI_RETRIES) if c not in U.AI_WAIT]: U.AI_RETRIES.pop(cid, None)
    auth.prune_fails(now)
    for ip in [ip for ip, ts in list(phone._BAD.items()) if not ts or max(ts) < now - 60]: phone._BAD.pop(ip, None)
    return n

def _retention_loop():
    while True:
        try: purge()
        except Exception as e: print("retention error:", e)
        try: prune_memory()
        except Exception as e: print("memory prune error:", e)
        time.sleep(3600)

@U.router.post("/api/admin/retention/run")
def run_purge(request: Request): return purge(who=request.state.user["username"])

@U.router.get("/api/admin/retention/preview")
def purge_preview():
    di = int(auth.get_setting("image_retention_days")); now = time.time()
    n = U.db().execute("SELECT COUNT(*) FROM cards WHERE image IS NOT NULL AND image!='' AND status!='pending' AND created<?", (now - di * 86400,)).fetchone()[0]
    total = U.db().execute("SELECT COUNT(*) FROM cards WHERE image IS NOT NULL AND image!=''").fetchone()[0]
    return {"would_delete": n, "photos_stored": total, "days": di, "enabled": auth.get_setting("retention_enabled") == "1"}
