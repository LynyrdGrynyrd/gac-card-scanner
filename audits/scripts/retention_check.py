"""Retention + deletion verification on a COPY: GAC_DIR=<copy> python audits/scripts/retention_check.py <admin> <pw>"""
import os, sys, json, sqlite3, urllib.request, http.cookiejar
B = os.environ.get("GAC_BASE", "http://127.0.0.1:8775"); D = os.environ.get("GAC_DIR", "/workspace/gac-audit-copy")
op = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(http.cookiejar.CookieJar()))
def j(m, u, b=None):
    r = urllib.request.Request(B + u, data=json.dumps(b).encode() if b is not None else None, headers={"Content-Type": "application/json"}, method=m)
    try: return json.loads(op.open(r).read())
    except urllib.error.HTTPError as e: return {"_code": e.code, **json.loads(e.read() or b"{}")}
j("POST", "/api/auth/login", {"username": sys.argv[1], "password": sys.argv[2]})
up, ex = os.path.join(D, "data/uploads"), os.path.join(D, "data/exports"); out = {}
db = sqlite3.connect(os.path.join(D, "data/cards.db"))
out["before"] = {"photos_on_disk": len(os.listdir(up)), "export_copies": len(os.listdir(ex)),
                 "cards_with_photo": db.execute("SELECT COUNT(*) FROM cards WHERE image!=''").fetchone()[0]}
old = j("GET", "/api/admin/settings")
j("POST", "/api/admin/settings", {"image_retention_days": "0", "export_retention_days": "0", "retention_enabled": "1"})
out["purge"] = j("POST", "/api/admin/retention/run")
out["after"] = {"photos_on_disk": len(os.listdir(up)), "export_copies": len(os.listdir(ex)),
                "cards_with_photo": db.execute("SELECT COUNT(*) FROM cards WHERE image!=''").fetchone()[0],
                "cards_with_text_kept": db.execute("SELECT COUNT(*) FROM cards").fetchone()[0]}
j("POST", "/api/admin/settings", {k: old[k] for k in ("image_retention_days", "export_retention_days", "retention_enabled")})
# hard delete of one card by request
cid = db.execute("SELECT id FROM cards WHERE status='pending' ORDER BY id DESC LIMIT 1").fetchone()[0]
import uuid; email = f"unique.{uuid.uuid4().hex[:8]}@removal-test.org"
j("POST", f"/api/cards/{cid}", {"fields": {"emails": [email]}})   # leaves it in fields, history and the undo snapshot
out["hard_delete"] = j("POST", f"/api/admin/cards/{cid}/delete", {"confirm": cid}); db.close(); db = sqlite3.connect(os.path.join(D, "data/cards.db"))
dump = "\n".join(db.iterdump())
out["hard_delete_left_in_db"] = {"card_row": bool(db.execute("SELECT 1 FROM cards WHERE id=?", (cid,)).fetchone()),
                                 "history": db.execute("SELECT COUNT(*) FROM card_history WHERE card_id=?", (cid,)).fetchone()[0],
                                 "email_anywhere_in_db": email in dump}
db.execute("PRAGMA wal_checkpoint"); raw = open(os.path.join(D, "data/cards.db"), "rb").read()
out["hard_delete_left_in_db"]["email_in_raw_db_file_bytes"] = email.encode() in raw
print(json.dumps(out, indent=1)); json.dump(out, open("/workspace/gac-card-scanner/audits/raw/retention_check.json", "w"), indent=1)
