"""QR / vCard / MECARD decoding (zxing-cpp). If a card carries a contact QR, its data is near-perfect."""
import io, re
from PIL import Image, ImageOps
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
def parse_vcard(t: str):
    if "BEGIN:VCARD" not in t.upper() and not t.upper().startswith("MECARD:"): return None
    f = {"first_name": "", "last_name": "", "title": "", "company": "", "department": "", "emails": [], "phones": [], "website": "", "address": "", "social": []}
    if t.upper().startswith("MECARD:"):
        for k, v in re.findall(r"([A-Z]+):((?:\\;|[^;])*);", t[7:]):
            if k == "N": parts = v.split(","); f["last_name"] = parts[0]; f["first_name"] = parts[1] if len(parts) > 1 else ""
            elif k == "TEL": f["phones"].append({"type": "work", "number": v})
            elif k == "EMAIL": f["emails"].append(v.lower())
            elif k == "URL": f["website"] = v
            elif k == "ORG": f["company"] = v
            elif k == "ADR": f["address"] = v.replace(";", ", ").strip(", ")
        return f
    for line in re.split(r"\r?\n", t):
        if ":" not in line: continue
        k, v = line.split(":", 1); K = k.upper(); key = K.split(";")[0]
        if key == "N":
            p = v.split(";"); f["last_name"] = p[0]; f["first_name"] = p[1] if len(p) > 1 else ""
        elif key == "FN" and not f["first_name"]:
            p = v.split(); f["first_name"], f["last_name"] = (p[0], p[-1]) if len(p) > 1 else (v, "")
        elif key == "ORG": p = v.split(";"); f["company"] = p[0]; f["department"] = p[1] if len(p) > 1 else ""
        elif key == "TITLE": f["title"] = v
        elif key == "EMAIL": f["emails"].append(v.lower())
        elif key == "URL": f["website"] = v
        elif key == "TEL":
            t_ = "fax" if "FAX" in K else "mobile" if "CELL" in K or "MOBILE" in K else "home" if "HOME" in K else "work"
            f["phones"].append({"type": t_, "number": v})
        elif key == "ADR":
            p = [x for x in v.split(";") if x.strip()]
            if len(p) >= 3: f["address"] = f"{', '.join(p[:-3])}, {p[-3]}, {p[-2]} {p[-1]}".strip(", ") if len(p) >= 4 else ", ".join(p)
            else: f["address"] = ", ".join(p)
    return f
