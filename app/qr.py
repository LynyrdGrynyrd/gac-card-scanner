"""QR / vCard / MECARD decoding (zxing-cpp). If a card carries a contact QR, its data is near-perfect."""
import base64, io, quopri, re
from PIL import Image, ImageOps
from .parser import surname
def decode(data: bytes):
    try:
        import zxingcpp
    except Exception: return []
    img = ImageOps.exif_transpose(Image.open(io.BytesIO(data))).convert("RGB")
    out = []
    g = ImageOps.autocontrast(ImageOps.grayscale(img))
    big = g.resize((g.width * 2, g.height * 2), Image.LANCZOS)
    for im in (img, g, big, big.point(lambda v: 255 if v > 140 else 0), big.point(lambda v: 255 if v > 100 else 0)):
        for r in zxingcpp.read_barcodes(im):
            if r.text and r.text not in out: out.append(r.text)
        if out: break
    return out
US = {"us", "usa", "unitedstates", "unitedstatesofamerica"}
def _split(v, sep=";"):
    """audit 2026-10: split on separators that are not backslash-escaped"""
    out, cur, i = [], "", 0
    while i < len(v):
        if v[i] == "\\" and i + 1 < len(v): cur += v[i:i+2]; i += 2; continue
        if v[i] == sep: out.append(cur); cur = ""
        else: cur += v[i]
        i += 1
    return out + [cur]
def _un(v): return re.sub(r"\\(.)", lambda m: "\n" if m.group(1) in "nN" else m.group(1), v).strip()
def _decode(v, params):
    """vCard 2.1 ENCODING=QUOTED-PRINTABLE/BASE64 with CHARSET; an unknown charset or bad data keeps the raw text."""
    cs = (re.search(r"CHARSET=([\w.:-]+)", params, re.I) or [None, "utf-8"])[1]
    enc = (re.search(r"ENCODING=([\w-]+)", params, re.I) or [None, ""])[1].upper()
    try:
        raw = quopri.decodestring(v.encode()) if enc in ("QUOTED-PRINTABLE", "QP") else base64.b64decode(v) if enc in ("B", "BASE64") else None
    except Exception: return v
    if raw is None: return v
    try: return raw.decode(cs)
    except (LookupError, UnicodeDecodeError): return raw.decode("utf-8", "replace")
def _adr(p):
    """ADR by position: PO box; extended; street; locality; region; postal code; country -> 'street, ext, PO box, City, ST 12345[, Country]'"""
    p = [_un(x).replace("\n", ", ") for x in p] + [""] * 7
    box, ext, street, city, region, code, country = p[:7]
    if box and box.replace(" ", "").isdigit(): box = "PO Box " + box
    rz = f"{region} {code}".strip()
    parts = [street, ext, box, city, rz] + ([country] if re.sub(r"[^a-z]", "", country.lower()) not in US else [])
    return ", ".join(x.strip(" ,") for x in parts if x.strip(" ,"))
def parse_vcard(t: str):
    if "BEGIN:VCARD" not in t.upper() and not t.upper().startswith("MECARD:"): return None
    f = {"first_name": "", "last_name": "", "title": "", "company": "", "department": "", "emails": [], "phones": [], "website": "", "address": "", "social": []}
    if t.upper().startswith("MECARD:"):
        for k, v in re.findall(r"([A-Z]+):((?:\\.|[^;\\])*);", t[7:]):
            if k == "N": parts = [_un(x) for x in _split(v, ",")]; f["last_name"] = parts[0]; f["first_name"] = parts[1] if len(parts) > 1 else ""
            elif k == "TEL": f["phones"].append({"type": "work", "number": _un(v)})
            elif k == "EMAIL": f["emails"].append(_un(v).lower())
            elif k == "URL": f["website"] = _un(v)
            elif k == "ORG": f["company"] = _un(v)
            elif k == "ADR": p = _split(v, ","); f["address"] = _adr(p) if len(p) == 7 else ", ".join(x for x in map(_un, p) if x)
        return f
    t = re.sub(r"\r?\n[ \t]", "", t)   # audit 2026-10: RFC 6350 line folding
    lines, adr_work = [], False
    for line in re.split(r"\r?\n", t):   # vCard 2.1 quoted-printable soft line breaks ('=' at the end)
        if lines and re.search(r"ENCODING=(QUOTED-PRINTABLE|QP)", lines[-1].split(":", 1)[0], re.I) and lines[-1].endswith("="): lines[-1] = lines[-1][:-1] + line
        else: lines.append(line)
    for line in lines:
        if ":" not in line: continue
        k, v = line.split(":", 1); K = k.upper(); key = K.split(";")[0].split(".")[-1]   # 'item1.EMAIL' (Apple groups)
        v = _decode(v, k)
        if key == "N":
            p = [_un(x) for x in _split(v)]; f["last_name"] = p[0]; f["first_name"] = p[1] if len(p) > 1 else ""
        elif key == "FN" and not f["first_name"]:
            p = _un(v).split(); f["first_name"], f["last_name"] = (p[0], surname(" ".join(p[1:]))) if len(p) > 1 else (_un(v), "")
        elif key == "ORG": p = [_un(x) for x in _split(v)]; f["company"] = p[0]; f["department"] = p[1] if len(p) > 1 else ""
        elif key == "TITLE": f["title"] = _un(v)
        elif key == "EMAIL": f["emails"].append(re.sub(r"(?i)^mailto:", "", _un(v)).lower())
        elif key == "URL": f["website"] = _un(v)
        elif key == "TEL":
            t_ = "fax" if "FAX" in K else "mobile" if "CELL" in K or "MOBILE" in K else "home" if "HOME" in K else "work"
            f["phones"].append({"type": t_, "number": re.sub(r"(?i)^tel:", "", _un(v))})
        elif key == "ADR" and (not f["address"] or ("WORK" in K and not adr_work)):
            f["address"] = _adr(_split(v)); adr_work = "WORK" in K
    return f
