"""OCR backends. Default: Tesseract (CPU, local). Optional: local vision LLM via Ollama (pluggable)."""
import io, os, re, json, base64, urllib.request
from PIL import Image, ImageOps, ImageFilter
import pytesseract
os.environ.setdefault("OMP_THREAD_LIMIT", "1")   # tesseract: no thread oversubscription (QA P4)

def preprocess(img: Image.Image) -> Image.Image:
    img = ImageOps.exif_transpose(img).convert("L")
    w, h = img.size
    if max(w, h) < 1600:  # upscale small phone crops
        s = 1600 / max(w, h); img = img.resize((int(w*s), int(h*s)), Image.LANCZOS)
    img = ImageOps.autocontrast(img)
    # invert dark-background cards
    if sum(img.histogram()[:128]) > sum(img.histogram()[128:]):
        img = ImageOps.invert(img)
    return img.filter(ImageFilter.SHARPEN)

def _wordscore(t):
    return sum(len(w) for w in re.findall(r"[A-Za-z]+", t) if re.fullmatch(r"[A-Z][a-z]{2,}|[A-Z]{3,}|[a-z]{3,}", w))

def _alpha(s): return sum(c.isalnum() for c in s) / max(len(s), 1)

def layout_lines(img):
    """Layout-aware OCR: tesseract words -> visual lines -> split at large horizontal gaps (columns)
    -> cluster segments into columns by left x -> emit column by column, top to bottom.
    Low-confidence or header-band segments are re-OCRed as a single line (psm 7) on a full-width crop."""
    W, H = img.size
    d = pytesseract.image_to_data(img, config="--psm 3", output_type=pytesseract.Output.DICT)
    words = [dict(t=d["text"][i].strip(), x=d["left"][i], y=d["top"][i], w=d["width"][i], h=d["height"][i],
                  c=float(d["conf"][i]), k=(d["block_num"][i], d["par_num"][i], d["line_num"][i]))
             for i in range(len(d["text"])) if d["text"][i].strip() and float(d["conf"][i]) >= 0]
    groups = {}
    for w in words: groups.setdefault(w["k"], []).append(w)
    segs = []
    for ws in groups.values():
        ws.sort(key=lambda w: w["x"]); cur = [ws[0]]
        hmed = sorted(w["h"] for w in ws)[len(ws)//2]
        for w in ws[1:]:
            gap = w["x"] - (cur[-1]["x"] + cur[-1]["w"])
            if gap > max(2.5 * hmed, 0.08 * W): segs.append(cur); cur = [w]
            else: cur.append(w)
        segs.append(cur)
    out = []
    for s in segs:
        x0 = min(w["x"] for w in s); x1 = max(w["x"]+w["w"] for w in s)
        y0 = min(w["y"] for w in s); y1 = max(w["y"]+w["h"] for w in s)
        text = " ".join(w["t"] for w in s); conf = sum(w["c"] for w in s) / len(s)
        out.append(dict(text=text, x=x0, x1=x1, y=y0, h=y1-y0, conf=conf, hm=min(w["h"] for w in s), ym=sorted(w["y"] for w in s)[len(s)//2]))
    return arrange(out, img)

def arrange(out, img, reocr=True):
    W, H = img.size
    # re-OCR weak/header segments (logos, spaced letters) as one line on a full-width band
    for l in (out if reocr else []):
        if l["conf"] < 75 or (l["y"] < 0.25 * H and l["conf"] < 92):
            same = [o for o in out if o is not l and min(o["y"]+o["h"], l["y"]+l["h"]) - max(o["y"], l["y"]) > 0.3 * l["h"]]
            lb = max([o["x1"] for o in same if o["x1"] <= l["x"]] + [0]) + 4
            rb = min([o["x"] for o in same if o["x"] >= l["x1"]] + [W]) - 4
            pad = int(0.35 * l["h"])
            best, bs = l["text"], _wordscore(l["text"])
            hm = l["hm"]; rb2 = min(rb, int(l["x1"] + 1.5 * hm))
            bands = [(l["ym"] - int(0.2*hm), l["ym"] + int(1.2*hm)), (l["y"] - pad, l["y"] + l["h"] + pad)]
            for (ya, yb) in bands:
                for left in sorted({lb, *(max(lb, int(l["x"] - k * hm)) for k in (3, 2, 1.5, 0.5))}):
                    band = img.crop((left, max(0, ya), rb2, min(H, yb)))
                    t = pytesseract.image_to_string(band, config="--psm 7").strip()
                    t = re.sub(r"^[^A-Za-z0-9]+\s*", "", t)
                    tk = t.split()
                    if len(tk) >= 3 and len(tk[0]) <= 2 and tk[0] != "A": t = " ".join(tk[1:])  # logo-icon artifact
                    if os.getenv("OCR_DEBUG"): print("REOCR", left, ya, yb, repr(t))
                    sc = _wordscore(t) - 0.5 * len(t.split())
                    if sc > bs: best, bs = t, sc
            if best != l["text"]: l["text"], l["reocr"] = best, True
    # dedupe lines that re-OCR made identical
    seen, uniq = set(), []
    for l in sorted(out, key=lambda l: l["y"]):
        if l["text"] in seen: continue
        seen.add(l["text"]); uniq.append(l)
    # column clustering by horizontal overlap (works for left-aligned AND centered layouts);
    # header-band lines are emitted first, top to bottom
    head = [l for l in uniq if l["y"] < 0.25 * H and not any(
        o is not l and min(o["y"]+o["h"], l["y"]+l["h"]) - max(o["y"], l["y"]) > 0.3 * l["h"]
        and min(o["x1"], l["x1"]) - max(o["x"], l["x"]) <= 0 for o in uniq)]
    body = [l for l in uniq if l not in head]
    cols = []
    # narrow lines define columns first; wide lines (logos, slogans) join the best-overlapping column without widening it
    for l in sorted(body, key=lambda l: (l["x1"] - l["x"])):
        hits = [c for c in cols if min(c["x1"], l["x1"]) - max(c["x"], l["x"]) > 0]
        if len(hits) == 1:
            c = hits[0]; c["lines"].append(l); c["x"] = min(c["x"], l["x"]); c["x1"] = max(c["x1"], l["x1"])
        elif hits:
            max(hits, key=lambda c: min(c["x1"], l["x1"]) - max(c["x"], l["x"]))["lines"].append(l)
        else: cols.append({"x": l["x"], "x1": l["x1"], "lines": [l]})
    # merge columns that ended up overlapping
    merged = True
    while merged:
        merged = False
        for a in cols:
            for b2 in cols:
                if a is not b2 and min(a["x1"], b2["x1"]) - max(a["x"], b2["x"]) > 0.5 * min(a["x1"]-a["x"], b2["x1"]-b2["x"]):
                    a["lines"] += b2["lines"]; a["x"] = min(a["x"], b2["x"]); a["x1"] = max(a["x1"], b2["x1"]); cols.remove(b2); merged = True; break
            if merged: break
    for l in head: l["col"] = -1
    for ci, c in enumerate(sorted(cols, key=lambda c: c["x"])):
        for l in c["lines"]: l["col"] = ci
    head.sort(key=lambda l: l["y"])
    body = [l for c in sorted(cols, key=lambda c: c["x"]) for l in sorted(c["lines"], key=lambda l: l["y"])]
    res, prev = [], None
    for l in head + body:
        if prev is not None and (l.get("col") != prev.get("col") or l["y"] - (prev["y"] + prev["h"]) > 1.2 * l["h"]):
            res.append(dict(text="", blank=True))
        res.append(l); prev = l
    return res

_RAPID = None
def _rapid():
    global _RAPID
    if _RAPID is None:
        from rapidocr_onnxruntime import RapidOCR
        n = int(os.getenv("OCR_THREADS", "2"))
        try: _RAPID = RapidOCR(intra_op_num_threads=n, inter_op_num_threads=1)
        except TypeError: _RAPID = RapidOCR()
    return _RAPID

def _nospace(t): return re.sub(r"[^a-z0-9@]", "", t.lower())

def hybrid_segments(img):
    """PP-OCR (RapidOCR/ONNX) text DETECTION + per-box Tesseract RECOGNITION (keeps word spaces),
    falling back to the PP-OCR transcription when Tesseract disagrees badly."""
    import numpy as np, cv2
    from difflib import SequenceMatcher
    rgb = np.array(img.convert("RGB"))
    res, _ = _rapid()(rgb)
    out = []
    for quad, txt, conf in (res or []):
        q = np.array(quad, dtype="float32")
        w = int(max(np.linalg.norm(q[1]-q[0]), np.linalg.norm(q[2]-q[3]))); h = int(max(np.linalg.norm(q[3]-q[0]), np.linalg.norm(q[2]-q[1])))
        if w < 4 or h < 4: continue
        pad = int(0.15 * h)
        dst = np.array([[pad, pad], [w+pad, pad], [w+pad, h+pad], [pad, h+pad]], dtype="float32")
        M = cv2.getPerspectiveTransform(q, dst)
        crop = cv2.warpPerspective(rgb, M, (w + 2*pad, h + 2*pad), borderMode=cv2.BORDER_REPLICATE)
        g = cv2.cvtColor(crop, cv2.COLOR_RGB2GRAY)
        if h < 48: g = cv2.resize(g, None, fx=48/h, fy=48/h, interpolation=cv2.INTER_CUBIC)
        if g.mean() < 127: g = 255 - g
        t = pytesseract.image_to_string(Image.fromarray(g), config="--psm 7").strip()
        t = re.sub(r"^[^A-Za-z0-9(+@#]+|[^A-Za-z0-9).]+$", "", t)
        sim = SequenceMatcher(None, _nospace(t), _nospace(txt)).ratio() if t else 0
        final = _transfer_spaces(t, txt) if sim >= 0.6 else _space_fix(txt)
        xs, ys = q[:, 0], q[:, 1]
        out.append(dict(text=final, x=int(xs.min()), x1=int(xs.max()), y=int(ys.min()), h=int(ys.max()-ys.min()),
                        conf=float(conf)*100, hm=h, ym=int(ys.min()), alt=txt, tess=t, sim=round(sim, 2)))
    return out

def _transfer_spaces(tess, rapid):
    """Keep PP-OCR characters (more accurate) but copy word-space positions from Tesseract via alignment."""
    from difflib import SequenceMatcher
    if " " in rapid.strip(): return rapid
    r = rapid.replace(" ", ""); ts = tess.replace(" ", "")
    # space positions in tesseract (index in no-space string before which a space occurs)
    sp, k = set(), 0
    for ch in tess:
        if ch == " ": sp.add(k)
        else: k += 1
    sm = SequenceMatcher(None, ts.lower(), r.lower(), autojunk=False)
    rsp = set()
    for tag, i1, i2, j1, j2 in sm.get_opcodes():
        if tag == "equal":
            for p in sp:
                if i1 < p <= i2 and (p - i1) + j1 < len(r): rsp.add(p - i1 + j1)
    out = "".join((" " if i in rsp else "") + c for i, c in enumerate(r))
    return _space_fix(out) if not rsp else out

def _space_fix(t):
    """PP-OCR English model often drops spaces: re-insert at case/digit boundaries and after punctuation."""
    if "@" in t or re.fullmatch(r"[\w.-]+\.[a-z]{2,}(/\S*)?", t, re.I): return t
    t = re.sub(r"(?<=[a-z])(?=[A-Z])", " ", t)
    t = re.sub(r"(?<=[,;:])(?=\S)", " ", t)
    t = re.sub(r"(?<=[A-Za-z]{2})(?=\d)|(?<=\d)(?=[A-Za-z]{2})", " ", t)
    return t

def _box(l, img):
    """v0.4 tap-to-zoom: where the line sits on the photo, as fractions [x, y, w, h] of the (upright) image."""
    try:
        W, H = img.size; x0 = max(0, l["x"]); x1 = min(W, l.get("x1", x0)); y0 = max(0, l["y"]); y1 = min(H, l["y"] + l["h"])
        return [round(x0 / W, 4), round(y0 / H, 4), round(max(0, x1 - x0) / W, 4), round(max(0, y1 - y0) / H, 4)]
    except Exception: return None

def _finish(img, lines, engine):
    real = [l for l in lines if not l.get("blank")]
    text = "\n".join(l["text"] for l in lines)
    conf = sum(l["conf"] for l in real) / len(real) / 100 if real else 0.0
    hs = sorted(l["h"] for l in real); hmed = hs[len(hs)//2] if hs else 1
    meta = [dict(text=l["text"], rel_h=round(l["h"]/hmed, 2), top=round(l["y"]/img.size[1], 2), col=l["col"], box=_box(l, img))
            for l in real]
    return {"engine": engine, "text": text, "lines": meta, "ocr_conf": round(conf, 2)}

def crop_card(img):
    """Find the card as the largest convex quadrilateral (phone photos) and warp it flat. Returns (img, found)."""
    import numpy as np, cv2
    a = np.array(img); H, W = a.shape[:2]; s = 800 / max(H, W)
    small = cv2.resize(a, (int(W * s), int(H * s)))
    g = cv2.GaussianBlur(cv2.cvtColor(small, cv2.COLOR_RGB2GRAY), (5, 5), 0)
    best = None
    for edges in (cv2.Canny(g, 30, 90), cv2.threshold(g, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)[1]):
        edges = cv2.dilate(edges, np.ones((3, 3), np.uint8))
        cnts, _ = cv2.findContours(edges, cv2.RETR_EXTERNAL if edges.max() and edges.mean() < 128 else cv2.RETR_LIST, cv2.CHAIN_APPROX_SIMPLE)
        for c in sorted(cnts, key=cv2.contourArea, reverse=True)[:5]:
            area = cv2.contourArea(c)
            if area < 0.15 * small.shape[0] * small.shape[1] or area > 0.97 * small.shape[0] * small.shape[1]: continue
            ap = cv2.approxPolyDP(c, 0.02 * cv2.arcLength(c, True), True)
            if len(ap) == 4 and cv2.isContourConvex(ap) and (best is None or area > best[0]): best = (area, ap.reshape(4, 2) / s)
    if best is None: return img, False
    q = best[1].astype("float32"); sm = q.sum(1); df = np.diff(q, axis=1).ravel()
    q = np.array([q[sm.argmin()], q[df.argmin()], q[sm.argmax()], q[df.argmax()]], dtype="float32")
    w = int(max(np.linalg.norm(q[1] - q[0]), np.linalg.norm(q[2] - q[3]))); h = int(max(np.linalg.norm(q[3] - q[0]), np.linalg.norm(q[2] - q[1])))
    if w < 200 or h < 120: return img, False
    M = cv2.getPerspectiveTransform(q, np.array([[0, 0], [w, 0], [w, h], [0, h]], dtype="float32"))
    return Image.fromarray(cv2.warpPerspective(a, M, (w, h))), True

def hybrid_ocr(data: bytes, crop=False):
    img = ImageOps.exif_transpose(Image.open(io.BytesIO(data))).convert("RGB")
    if crop:
        img, found = crop_card(img)
        if not found: return None
    T = int(os.getenv("OCR_TARGET", "1200"))
    mp = float(os.getenv("OCR_MAX_MP", "4")) * 1e6   # round 20: text detection memory grows with pixels (11 MP used >1.6 GB; 4 MP keeps the server under ~1.2 GB, same accuracy on 12 MP phone-size photos)
    if img.width * img.height > mp:
        s = (mp / (img.width * img.height)) ** 0.5; img = img.resize((int(img.width*s), int(img.height*s)), Image.LANCZOS)
    if max(img.size) < T:
        s = T / max(img.size); img = img.resize((int(img.width*s), int(img.height*s)), Image.LANCZOS)
    return _finish(img, arrange(hybrid_segments(img), img, reocr=False), "ppocr+tesseract")

def tesseract_ocr(data: bytes):
    img = preprocess(Image.open(io.BytesIO(data)))
    lines = layout_lines(img)
    real = [l for l in lines if not l.get("blank")]
    text = "\n".join(l["text"] for l in lines)
    conf = sum(l["conf"] for l in real) / len(real) / 100 if real else 0.0
    hs = sorted(l["h"] for l in real); hmed = hs[len(hs)//2] if hs else 1
    meta = [dict(text=l["text"], rel_h=round(l["h"]/hmed, 2), top=round(l["y"]/img.size[1], 2), col=l["col"], box=_box(l, img))
            for l in real]
    return {"engine": "tesseract-layout", "text": text, "lines": meta, "ocr_conf": round(conf, 2)}

VLM_PROMPT = ("Extract the business card into JSON with keys first_name,last_name,title,company,"
              "emails(list),phones(list of {type,number}),website,address,social(list). Return only JSON.")

def ollama_vlm(data: bytes, model=None):
    """Optional path. Requires `ollama serve` + e.g. `ollama pull qwen3-vl:4b`. Not used unless OCR_ENGINE=ollama."""
    model = model or os.getenv("OLLAMA_MODEL", "qwen3-vl:4b")
    body = json.dumps({"model": model, "prompt": VLM_PROMPT, "stream": False, "format": "json",
                       "images": [base64.b64encode(data).decode()]}).encode()
    req = urllib.request.Request(os.getenv("OLLAMA_URL", "http://127.0.0.1:11434") + "/api/generate", body,
                                 {"Content-Type": "application/json"})
    out = json.loads(urllib.request.urlopen(req, timeout=180).read())["response"]
    return {"engine": f"ollama:{model}", "text": out, "structured": json.loads(out)}

def run_ocr(data: bytes, engine=None):
    engine = engine or os.getenv("OCR_ENGINE", "hybrid")
    if engine == "hybrid": return hybrid_ocr(data)
    if engine == "ollama":
        try: return ollama_vlm(data)
        except Exception as e:
            r = tesseract_ocr(data); r["fallback_reason"] = f"ollama unavailable: {e}"; return r
    return tesseract_ocr(data)
