"""The admin audit log (card history + sign-in log in plain words). Split out of app/ui.py (audit 2026-10 P2)."""
import io, re, csv, json, datetime
from fastapi.responses import Response
from . import auth
from . import ui as U

# ---------------------------------------------------------------- audit log
def _fmtv(v):
    """History values in plain words: phone dicts as 'mobile: 330-555-0101', lists joined."""
    if isinstance(v, list): return ", ".join(_fmtv(x) for x in v)
    if isinstance(v, dict): return f"{v.get('type', '')}: {v.get('number', '')}".strip(": ") if "number" in v else ", ".join(f"{k}: {x}" for k, x in v.items())
    return "" if v is None else str(v)

NAMES = {"scanned": "scanned", "edited": "edited", "exported": "exported", "redownloaded": "re-downloaded in an export",
         "merged_from": "merged details from another card", "mc_trade_choice": "MC Trade choice", "back_added": "back of card added",
         "ai_checked": "double-check", "ai_suggestion": "AI suggestion", "duplicate_kept_both": "marked as a different person"}
def _audit_text(action, frm, to, d):
    d = d or {}
    if isinstance(d, dict) and d.get("redacted"):
        if action == "decision": t = f"{frm} → {to}" + (" (approved despite problems)" if d.get("override") else "") + (" (bulk)" if d.get("bulk") else "")
        elif action == "edited": t = "edited " + ", ".join(U.LABEL.get(k, k) for k in d.get("fields", []))
        elif action == "merged_from" and d.get("card"): t = f"merged details from card #{d['card']}"
        elif action == "exported": t = "exported" + (f" in {d['file']}" if d.get("file") else "")
        elif action == "redownloaded": t = f"re-downloaded in export #{d.get('export_id')}"
        elif action == "duplicate_kept_both" and d.get("cards"): t = "marked as a different person from " + ", ".join(f"#{i}" for i in d["cards"])
        elif action == "undo": t = f"undid: {d.get('undid', '')}"
        else: t = NAMES.get(action, action.replace("_", " "))
        return t + " [personal details removed on request]"
    if action == "hard_check_override":   # round 23: field, value and reason in plain words
        return f"confirmed {U.LABEL.get(d.get('field'), d.get('field') or 'a value')} “{_fmtv(d.get('value'))[:120]}” as correct" + (f" (reason: {d['reason']})" if d.get("reason") else " (no reason recorded)")
    if action == "cross_batch_confirmed":
        return "approved although " + (("#" + ", #".join(str(i) for i in d["cards"])) if d.get("cards") else "a card in another batch") + " may be the same person"
    if action == "deleted_on_request": return f"card deleted on request (photo and details; {d.get('export_copies', 0)} stored export file(s)); its history is kept without personal data"
    if action == "redownloaded": return f"re-downloaded in export #{d.get('export_id')} ({d.get('file')})"
    if action == "decision":
        t = f"{frm} → {to}"
        if isinstance(d, dict) and d.get("override"): t += f' (approved despite problems: "{d["override"]}")'
        if isinstance(d, dict) and d.get("bulk"): t += " (bulk)"
        return t
    if action == "edited": return "edited " + ", ".join(f"{U.LABEL.get(k, k)}: “{_fmtv(v.get('from'))}” → “{_fmtv(v.get('to'))}”" for k, v in d.items() if isinstance(v, dict))
    if action == "scanned": return f"scanned {d.get('file', '')}" + (f" in batch “{d.get('batch')}”" if d.get("batch") else "") + (" (QR code found)" if d.get("qr") else "")
    if action == "exported": return f"exported in {d.get('file')}"
    if action == "merged_from":
        add = d.get("added") or {}
        return f"merged details from card #{d.get('card')}" + (" (added " + ", ".join(U.LABEL.get(k, k.replace("_", " ")) for k in add) + ")" if add else "")
    if action == "mc_trade_choice": return "chose: update existing MC Trade contact" if d == "update_existing" else "chose: add as new MC Trade contact"
    if action == "duplicate_kept_both":
        ids = (d or {}).get("cards") if isinstance(d, dict) else None
        return "marked as a different person from " + ", ".join(f"#{i}" for i in ids) + " (keep both)" if ids else "marked as a different person (keep both)"
    if action == "back_to_pending": return f"moved back to pending ({d.get('why')}): " + "; ".join(d.get("problems") or [])
    if action == "archived": return "archived"
    if action == "upload_cancelled": return "stopped an upload: " + (f"{d['kept']} kept, " if d.get("kept") is not None else "") + f"{d.get('not_scanned', 0)} not scanned" + (f" (batch “{d.get('batch')}”)" if d.get("batch") else "")
    if action == "undo": return f"undid: {d.get('undid')}"
    if action == "ai_checked":
        ch = d.get("changed") or {}
        if d.get("suggested"): return "double-check: suggestions offered for " + ", ".join(U.LABEL.get(k, k) for k in d["suggested"]) + f" ({d.get('seconds')} s)"
        return "double-check: " + (("changed " + ", ".join(f"{U.LABEL.get(k, k)} “{_fmtv(v.get('from'))}” → “{_fmtv(v.get('to'))}”" for k, v in ch.items())) if ch else "no changes needed") + f" ({d.get('seconds')} s)"
    if action == "reexport_needed": return f"needs exporting again ({(d or {}).get('why', '')})"
    if action == "ai_suggestion": return "AI suggestion: " + ", ".join(f"{U.LABEL.get(k, k)}: " + ("used the AI value" if v == "accept" else "kept the current value") for k, v in d.items())
    if action == "back_added" and d.get("from_card"): return f"back photo carried over from card #{d['from_card']}"
    if action == "back_added": return "added the back of the card" + (" (filled " + ", ".join(U.LABEL.get(k, k) for k in d.get("filled", [])) + ")" if d.get("filled") else "")
    if action == "photo_deleted": return f"photo deleted by retention policy ({d.get('after_days')} days)"
    return action.replace("_", " ")

@U.router.get("/api/admin/audit")
def audit(q: str = "", limit: int = 500, fmt: str = "json"):
    rows = []; want = limit
    # round 15 (manager r14 L-r14-2): WHO is always the username (initials are mapped back); the initials stay in their own column
    _ini = {}
    for u_ in auth.db().execute("SELECT username, initials FROM users"): _ini.setdefault(u_["initials"], []).append(u_["username"])
    _u2i = {u_["username"]: u_["initials"] for u_ in auth.db().execute("SELECT username, initials FROM users")}
    def _w(x):
        if not x or x == "system": return "system"
        if x in _u2i: return x
        return _ini[x][0] if len(_ini.get(x) or []) == 1 else x
    if q: limit = 1_000_000   # manager-r9 L-r9-4: search the whole log first, then keep the newest `limit` matches
    for r in U.db().execute("SELECT * FROM card_history ORDER BY id DESC LIMIT ?", (limit,)):
        d = json.loads(r["detail"]) if r["detail"] else None
        txt = _audit_text(r["action"], r["from_status"], r["to_status"], d)
        rows.append({"ts": r["ts"], "who": r["reviewer"] or "system", "what": txt[:400], "card": r["card_id"], "kind": "card"})
    for r in U.db().execute("SELECT * FROM auth_log ORDER BY id DESC LIMIT ?", (limit,)):
        ev = r["event"] or ""
        # round 17 (manager r16 L-1): refused rows are filed under what was refused, not 'account'
        kind = (("export" if ev.startswith("refused export") else "template" if "of the MC Trade template" in ev else "contacts" if "of the MC Trade contacts" in ev else "settings")
                if ev.startswith("refused") else "settings" if ev.startswith("settings") else "export" if ev.startswith(("re-downloaded", "downloaded the", "dry run", "ran the MC Trade dry-run", "viewed the PREVIEW")) else
                "card" if ev.startswith(("deleted card", "Clear all test data", "confirmed as correct on card")) else "account")
        ids_ = list(dict.fromkeys(int(x) for x in re.findall(r"#(\d+)", ev))) if kind in ("export", "card") or ev.startswith("refused export") else []   # round 11: each card once (manager-r10)
        rows.append({"ts": r["ts"], "who": r["username"], "what": ev + (f" (from {r['ip']})" if r["ip"] else ""), "card": ids_[0] if ids_ else None, "cards": ids_, "kind": kind})
    for r in U.db().execute("SELECT * FROM exports ORDER BY id DESC LIMIT ?", (limit,)):
        _ids = json.loads(r["card_ids"] or "[]")
        rows.append({"ts": r["ts"], "who": r["initials"], "what": f"export {r['kind']} · {r['count']} {U._s(r['count'], 'card')} · {U.FILTERS.get(r['filter'], r['filter'])} · {r['filename']}" + (": " + ", ".join(f"#{i}" for i in _ids[:500]) if _ids else ""), "card": _ids[0] if _ids else None, "cards": _ids, "kind": "export"})
    for r in U.db().execute("SELECT * FROM actions WHERE undone IS NOT NULL ORDER BY id DESC LIMIT ?", (limit,)):
        rows.append({"ts": r["undone"], "who": r["username"], "what": f"undo: {r['label']}", "card": None, "kind": "undo"})
    rows.sort(key=lambda x: -x["ts"])
    for r in rows: r["who"] = _w(r["who"]); r["initials"] = _u2i.get(r["who"], "")
    if q: ql = q.lower(); rows = [r for r in rows if ql in (str(r["who"]) + " " + str(r.get("initials") or "") + " " + r["what"] + " #" + str(r["card"])).lower()]
    rows = rows[:want]
    if fmt == "csv":
        b = io.StringIO(); w = csv.writer(b); w.writerow(["time", "who", "initials", "type", "card", "what"])
        for r in rows: w.writerow([U._when(r["ts"]), r["who"], r.get("initials") or "", r["kind"], " ".join(f"#{i}" for i in (r.get("cards") or ([r["card"]] if r["card"] else []))), U.safe_cell(r["what"])])
        return Response(b.getvalue(), media_type="text/csv", headers={"Content-Disposition": f'attachment; filename="GAC-scanner-audit-{datetime.date.today()}.csv"'})
    return rows
