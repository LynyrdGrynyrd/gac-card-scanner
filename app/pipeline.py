"""Single entry point: image bytes -> fields. Used by web app (/scan, /api/scan) and benchmarks.
Stages: QR/vCard decode -> hybrid OCR (PP-OCR det + Tesseract rec) -> rule parser -> optional local VLM merge."""
import difflib, json, os, re
from . import ocr, parser, qr
FIX_KEYS = ("title", "company", "emails", "phones", "website", "address")

def postfix_marked(f):
    """Run the real-card clean-ups and (v0.4 #9, display only) remember what they changed, so the review screen can mark
    the field "changed". The values and the rules are exactly postfix.apply's; nothing is undone or blocked here."""
    from . import postfix
    k_ = lambda v: json.dumps(v, sort_keys=True, default=str)
    raw = {k: json.loads(k_(f.get(k))) for k in FIX_KEYS}
    f = postfix.apply(f)
    f["auto_fixed"] = {k: raw[k] for k in FIX_KEYS if k_(f.get(k)) != k_(raw[k])}
    return f

def _sq(s): return re.sub(r"\s+", " ", str(s or "")).strip()

def _closest(val, lines):
    """The OCR line (or run of text) that a value was most likely read from."""
    best, bs = "", 0.0
    for ln in lines:
        r = difflib.SequenceMatcher(None, val.lower(), ln.lower()).ratio()
        if r > bs: best, bs = ln, r
    return best if bs >= 0.5 else ""

def mark_read_changes(f, text):
    """v0.4.1 #3 (datamanager H2): EVERY automatic change is marked, not only the post-fix ones. A value that is not
    printed as-is in the OCR text was changed by the clean-up (spacing, a fixed letter in a phone number, a joined word):
    auto_fixed gets what was read. Phones changed this way get a low confidence, so the field shows 'Check'."""
    raw = text or ""; lines = [_sq(l) for l in raw.splitlines() if l.strip()]
    flat = " \n ".join(lines).lower(); af = f.setdefault("auto_fixed", {})
    def present(v): return _sq(v).lower() in flat
    for k in ("title", "company", "website"):
        v = f.get(k)
        if v and k not in af and not present(v) and not all(present(p) for p in re.split(r",\s*", v) if p.strip()):
            af[k] = _closest(_sq(v), lines) or None
    addr = f.get("address")
    if addr and "address" not in af and not all(present(p) for p in re.split(r",\s*", addr) if p.strip()):
        af["address"] = _closest(_sq(addr), lines) or None
    ems = f.get("emails") or []
    if ems and "emails" not in af and not all(present(e) for e in ems):
        af["emails"] = [_closest(e, lines) or e for e in ems]
    ph = f.get("phones") or []
    rawd = [re.sub(r"\D", "", l) for l in lines]   # phones: the digits must be printed in that order (the format may change)
    changed = [p for p in ph if isinstance(p, dict) and p.get("number") and not any(re.sub(r"\D", "", p["number"]) in d for d in rawd)]
    if changed and "phones" not in af:
        af["phones"] = [dict(p, number=(_closest(p["number"], lines) or p["number"])) if p in changed else p for p in ph]
    if changed or any(isinstance(p, dict) and p.get("valid") is False for p in ph):
        c = f.setdefault("confidence", {}); c["phones"] = min(c.get("phones", 1.0) or 1.0, 0.5)
    return f

def scan(data: bytes, engine=None, use_vlm=None, vlm_result=None):
    r = ocr.run_ocr(data, engine); lines0 = r.get("lines")   # v0.4: full-frame lines (the crop pass has other coordinates)
    f = parser.from_vlm(r["structured"]) if "structured" in r else parser.parse(r["text"], r.get("lines"))
    # second pass on the perspective-cropped card (phone photos): fill fields the full-frame pass missed
    if r["engine"].startswith("ppocr") and os.getenv("CARD_CROP", "1") == "1":
        r2 = ocr.hybrid_ocr(data, crop=True)
        if r2:
            f2 = parser.parse(r2["text"], r2.get("lines"))
            for k in ("first_name", "last_name", "title", "company", "department", "emails", "phones", "website", "address", "other_address", "social"):
                if not f.get(k) and f2.get(k):
                    if k in ("first_name", "last_name") and f.get("first_name"): continue
                    f[k] = f2[k]
            seen = {ln.strip().lower() for ln in r["text"].splitlines()}
            extra = [ln for ln in r2["text"].splitlines() if ln.strip() and ln.strip().lower() not in seen]   # don't show the front twice
            r = dict(r, text=r["text"] + ("\n\n" + "\n".join(extra) if extra else ""))
    f["ocr_conf"] = r.get("ocr_conf"); f["fallback_reason"] = r.get("fallback_reason"); f["sources"] = {"ocr": r["engine"]}
    # QR vCard: authoritative for the fields it carries
    for t in qr.decode(data):
        v = qr.parse_vcard(t)
        if v:
            for k, val in v.items():
                if val: f[k] = val; f.setdefault("confidence", {})[("name" if k in ("first_name", "last_name") else k)] = 0.99
            f["sources"]["qr"] = "vcard"; break
        elif not f["website"] and t.lower().startswith(("http", "www")): f["website"] = t
    cons = os.getenv("CONSISTENCY", "1") == "1"
    if cons:   # first pass: the AI merge below reads these confidences
        from . import consistency, plausibility
        pre = dict(f.get("confidence") or {}); consistency.apply(f); post = dict(f["confidence"])
        plausibility.apply(f)   # suggestions only (f['suggestions']); values untouched
    if use_vlm is None: use_vlm = os.getenv("USE_VLM", "0") == "1"
    if use_vlm or vlm_result is not None:
        from . import vlm, merge
        try:
            v = vlm_result if vlm_result is not None else vlm.extract(data, r["text"])
            f = merge.merge(f, v, r["text"]); f["sources"]["vlm"] = os.getenv("VLM_NAME", "qwen3-vl-4b")
        except Exception as e: f["sources"]["vlm_error"] = str(e)[:200]
    if os.getenv("REALCARD_POSTFIX", "1") == "1":
        f = postfix_marked(f)
    if cons:   # audit 2026-10: flags and suggestions describe the final (merged + post-fixed) values; the first pass's untouched adjustments are undone so they don't stack
        conf = f.setdefault("confidence", {})
        for k, x in post.items():
            if k in pre and conf.get(k) == x: conf[k] = pre[k]
        consistency.apply(f); plausibility.apply(f)
    mark_read_changes(f, r["text"])
    try:
        from . import boxes; f["boxes"] = boxes.locate(f, lines0)   # v0.4 tap-to-zoom (display only)
    except Exception: f["boxes"] = {}
    return {"engine": r["engine"], "text": r["text"], "fields": f}
