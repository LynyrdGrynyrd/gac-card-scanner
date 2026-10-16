"""v0.4 tap-to-zoom: find where each field was read on the photo. Display only: nothing here changes a value, a block or
a confirm. Boxes are fractions [x, y, w, h] of the upright photo; a field without a confident match gets no box (the UI
then shows the whole photo)."""
import re
from difflib import SequenceMatcher

FIELDS = ("name", "title", "company", "department", "website", "address")
MIN = 0.72   # below this the box is more likely wrong than right; no box beats a wrong box


def _n(t): return re.sub(r"[^a-z0-9@]", "", str(t or "").lower())


def _score(v, t):
    if not v or not t: return 0.0
    if v == t: return 1.0
    if len(v) >= 4 and v in t: return 0.8 + 0.2 * len(v) / len(t)
    if len(t) >= 4 and t in v: return 0.75 * len(t) / len(v) + 0.2
    return SequenceMatcher(None, v, t).ratio()


def _union(bs):
    x0 = min(b[0] for b in bs); y0 = min(b[1] for b in bs); x1 = max(b[0] + b[2] for b in bs); y1 = max(b[1] + b[3] for b in bs)
    return [round(x0, 4), round(y0, 4), round(x1 - x0, 4), round(y1 - y0, 4)]


def _find(val, lines, multi=False):
    v = _n(val)
    if len(v) < 2: return None
    sc = sorted(((_score(v, _n(l["text"])), i) for i, l in enumerate(lines)), reverse=True)
    if sc and sc[0][0] >= MIN: return lines[sc[0][1]]["box"]
    if not multi: return None
    # an address (or a long name) is often printed over 2-3 lines: take the lines that are each a piece of the value
    parts = [l for l in lines if len(_n(l["text"])) >= 3 and _n(l["text"]) in v]
    if parts and sum(len(_n(l["text"])) for l in parts) >= 0.6 * len(v): return _union([l["box"] for l in parts])
    return None


def locate(f, lines):
    """{field: [x, y, w, h]} for the review screen. Phones/emails are keyed 'phones.0', 'emails.1', ..."""
    lines = [l for l in (lines or []) if l.get("box") and l["box"][2] > 0 and l["box"][3] > 0 and str(l.get("text") or "").strip()]
    if not lines: return {}
    out = {}
    for k in FIELDS:
        val = " ".join(x for x in (f.get("first_name"), f.get("last_name")) if x) if k == "name" else f.get(k)
        if isinstance(val, str) and val.strip():
            b = _find(val, lines, multi=k in ("address", "name", "company"))
            if b: out[k] = b
    for i, e in enumerate(f.get("emails") or []):
        b = _find(e, lines)
        if b: out[f"emails.{i}"] = b
    for i, p in enumerate(f.get("phones") or []):
        num = p.get("number") if isinstance(p, dict) else p
        d = re.sub(r"\D", "", str(num or ""))
        if len(d) < 6: continue
        # digits only: the printed line carries a label ("T", "Tel.") and other separators than the stored number
        best = max(((SequenceMatcher(None, d[-9:], re.sub(r"\D", "", l["text"])).ratio(), l) for l in lines if re.search(r"\d{3}", l["text"])), default=(0, None), key=lambda x: x[0])
        if best[0] >= 0.8: out[f"phones.{i}"] = best[1]["box"]
    return out
