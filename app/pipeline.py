"""Single entry point: image bytes -> fields. Used by web app (/scan, /api/scan) and benchmarks.
Stages: QR/vCard decode -> hybrid OCR (PP-OCR det + Tesseract rec) -> rule parser -> optional local VLM merge."""
import os
from . import ocr, parser, qr
def scan(data: bytes, engine=None, use_vlm=None, vlm_result=None):
    r = ocr.run_ocr(data, engine)
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
    if os.getenv("CONSISTENCY", "1") == "1":
        from . import consistency
        consistency.apply(f)
        from . import plausibility; plausibility.apply(f)   # suggestions only (f['suggestions']); values untouched
    if use_vlm is None: use_vlm = os.getenv("USE_VLM", "0") == "1"
    if use_vlm or vlm_result is not None:
        from . import vlm, merge
        try:
            v = vlm_result if vlm_result is not None else vlm.extract(data, r["text"])
            f = merge.merge(f, v, r["text"]); f["sources"]["vlm"] = os.getenv("VLM_NAME", "qwen3-vl-4b")
        except Exception as e: f["sources"]["vlm_error"] = str(e)[:200]
    return {"engine": r["engine"], "text": r["text"], "fields": f}
