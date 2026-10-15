"""Round 18: extra upload formats (HEIC/HEIF photos, PDF scans) and a multi-card splitter.

Everything here turns an upload into one or more plain JPEG "card photos" BEFORE the normal checks (_check_image) and the
normal pipeline run, so the rest of the scanner only ever sees JPEG/PNG/etc.

* HEIC/HEIF (iPhone default) is decoded with pillow-heif, turned upright from its EXIF orientation, and re-saved as JPEG.
  Other EXIF (GPS, camera) is not carried over.
* PDF is opened with pdfium (pypdfium2). Only page CONTENT is rendered: no form layer, no JavaScript (pypdfium2 never
  starts pdfium's JS engine unless forms are initialised, which we never do). Each page is rendered at ~200 dpi (round 20), capped at
  PAGE_MAX_PIXELS, one page at a time, inside a memory-limited reader subprocess (app/reader.py).
  Encrypted / damaged PDFs give a friendly message. The PDF text layer is not used (the image is always OCR'd).
* split_cards() finds several cards laid out on one page / flatbed scan (OpenCV contours). It only splits when it finds
  at least two clean card-shaped rectangles of similar size; otherwise the page/photo stays ONE card.
"""
import io

MAX_PDF_PAGES = 200
PDF_DPI = 200                    # round 20: was 300 (a 300-dpi wide page was 11 MP and OCR on it used >1.6 GB)
PAGE_MAX_PIXELS = 12_000_000     # round 20 (skeptic C1): was 40 MP; a 14400x14400 pt page rendered at 40 MP OOM-killed the server
PAGE_MAX_SIDE = 5000
PHOTO_MAX_PIXELS = 16_000_000    # round 20: photos above this are downscaled before they are queued (phones are 12 MP)
MAX_CARDS_PER_PAGE = 16
HEIF_BRANDS = {b"heic", b"heix", b"heim", b"heis", b"hevc", b"hevx", b"hevm", b"hevs", b"mif1", b"msf1", b"mif2"}


class FormatError(Exception):
    """Message is shown to the user as is."""


def is_pdf(data: bytes) -> bool:
    return b"%PDF-" in data[:1024]


def is_heif(data: bytes) -> bool:
    return len(data) >= 12 and data[4:8] == b"ftyp" and data[8:12] in HEIF_BRANDS


def _heif_ready():
    try:
        import pillow_heif
    except ImportError:
        return False
    pillow_heif.register_heif_opener()
    return True


def to_jpeg(im, quality=92) -> bytes:
    b = io.BytesIO()
    im.convert("RGB").save(b, "JPEG", quality=quality, optimize=True)
    return b.getvalue()


def heif_to_jpeg(data: bytes, max_pixels=60_000_000) -> bytes:
    from PIL import Image, ImageOps
    if not _heif_ready():
        raise FormatError("iPhone HEIC photos need an extra component that isn't installed. Export the photo as JPG instead.")
    try:
        im = Image.open(io.BytesIO(data), formats=["HEIF"])
        if im.size[0] * im.size[1] > max_pixels:
            raise FormatError("This picture is far too large (too many pixels). Use a normal phone photo.")
        im.load()
        im = ImageOps.exif_transpose(im)      # bake the EXIF orientation into the pixels
    except FormatError:
        raise
    except Exception:
        raise FormatError("This HEIC photo is damaged. Save it as JPG and try again.")
    return to_jpeg(im)


def page_scale(w, h, dpi=PDF_DPI):
    """Render scale for a page of w x h points: dpi/72, lowered so the page stays under PAGE_MAX_PIXELS / PAGE_MAX_SIDE."""
    scale = dpi / 72
    px = w * scale * h * scale
    if px > PAGE_MAX_PIXELS: scale *= (PAGE_MAX_PIXELS / px) ** 0.5 * 0.995   # pdfium rounds the size up
    if max(w, h) * scale > PAGE_MAX_SIDE: scale = PAGE_MAX_SIDE / max(w, h) * 0.995
    return scale


def _open_pdf(data):
    try:
        import pypdfium2 as pdfium
    except ImportError:
        raise FormatError("PDF support isn't installed on this scanner. Save the pages as JPG instead.")
    try:
        return pdfium.PdfDocument(data)
    except pdfium.PdfiumError as e:
        if "password" in str(e).lower():
            raise FormatError("This PDF has a password. Remove it and try again.")
        raise FormatError("This PDF is damaged and can't be opened. Save it again and retry.")


def pdf_page_count(data: bytes, max_pages=MAX_PDF_PAGES) -> int:
    """Round 20: pages are counted (no rendering) before any job is made, so the limits are checked first."""
    doc = _open_pdf(data)
    try:
        n = len(doc)
        if n == 0: raise FormatError("This PDF has no pages.")
        if n > max_pages: raise FormatError(f"This PDF has {n} pages; the limit is {max_pages}. Split it into smaller PDFs.")
        return n
    finally:
        doc.close()


def render_page(data: bytes, i: int, dpi=PDF_DPI):
    """Round 20: ONE page (0-based) -> PIL RGB image, at most PAGE_MAX_PIXELS."""
    doc = _open_pdf(data)
    try:
        page = doc[i]
        try:
            w, h = page.get_size()
            bm = page.render(scale=page_scale(w, h, dpi), may_draw_forms=False)   # no form layer, no JS
            im = bm.to_pil().convert("RGB"); bm.close()
            return im
        except MemoryError:
            raise
        except Exception:
            raise FormatError(f"Page {i + 1} of this PDF is damaged and can't be read.")
        finally:
            page.close()
    finally:
        doc.close()


def page_parts(im, stem, p, n):
    """One rendered page -> [(jpeg_bytes, label)], one per card found on it."""
    parts = split_cards(im)
    out = []
    for k, part in enumerate(parts, 1):
        lab = f"{stem}.pdf (page {p} of {n}" + (f", card {k} of {len(parts)}" if len(parts) > 1 else "") + ")"   # round 21: named by PDF and page
        out.append((to_jpeg(part), lab))
    del parts
    return out


def shrink(im, max_pixels=PHOTO_MAX_PIXELS):
    """Downscale (in place of a copy) so the image has at most max_pixels."""
    w, h = im.size
    if w * h <= max_pixels: return im
    s = (max_pixels / (w * h)) ** 0.5
    return im.resize((max(1, int(w * s)), max(1, int(h * s))), 1)   # LANCZOS


RASTER = ["JPEG", "PNG", "WEBP", "GIF", "BMP", "TIFF", "MPO"]   # same allowlist as ui.FORMATS (no EPS & co., which shell out)
DECODE_MAX_PIXELS = 60_000_000                                     # same cap as ui.MAX_PIXELS


def prepare_for_ocr(data: bytes) -> bytes:
    """Round 20: a photo above PHOTO_MAX_PIXELS is re-saved smaller (OCR memory grows with pixels).
    Audit 2026-10 C2: this runs in the web server, so only plain raster formats are opened, and a picture above the
    decode cap is left as it is (ui._check_image then refuses it) instead of being decoded and shrunk past that cap."""
    from PIL import Image
    try:
        im = Image.open(io.BytesIO(data), formats=RASTER)
        if im.size[0] * im.size[1] <= PHOTO_MAX_PIXELS or im.size[0] * im.size[1] > DECODE_MAX_PIXELS: return data
        from PIL import ImageOps
        im = ImageOps.exif_transpose(im)
        return to_jpeg(shrink(im))
    except Exception:
        return data


def expand_safe(data: bytes, fname: str):
    """Round 20: like expand(), but every page is read in the memory-limited reader subprocess, one at a time,
    and parts are yielded one by one (offline tools / measurement; the server uses app.reader directly)."""
    from . import reader
    if not is_pdf(data):
        r = reader.run_photo(data, fname)
        if r is None: yield data, fname
        else: yield from r
        return
    n = reader.run_count(data)
    for i in range(n):
        yield from reader.run_page(data, i, n, fname)


def pdf_pages(data: bytes, max_pages=MAX_PDF_PAGES, dpi=PDF_DPI):
    """Yields (page_no, n_pages, PIL image). Raises FormatError for encrypted/damaged/too-long PDFs."""
    try:
        import pypdfium2 as pdfium
    except ImportError:
        raise FormatError("PDF support isn't installed on this scanner. Save the pages as JPG instead.")
    try:
        doc = pdfium.PdfDocument(data)
    except pdfium.PdfiumError as e:
        if "password" in str(e).lower():
            raise FormatError("This PDF has a password. Remove it and try again.")
        raise FormatError("This PDF is damaged and can't be opened. Save it again and retry.")
    try:
        n = len(doc)
        if n == 0: raise FormatError("This PDF has no pages.")
        if n > max_pages: raise FormatError(f"This PDF has {n} pages; the limit is {max_pages}. Split it into smaller PDFs.")
        for i in range(n):
            page = doc[i]
            try:
                w, h = page.get_size()            # points (1/72 in)
                im = page.render(scale=page_scale(w, h, dpi), may_draw_forms=False).to_pil()   # no form layer, no JS
            except Exception:
                raise FormatError(f"Page {i + 1} of this PDF is damaged and can't be read.")
            finally:
                page.close()
            yield i + 1, n, im.convert("RGB")
    finally:
        doc.close()


def find_cards(img, min_frac=0.03):
    """Card-shaped rectangles on a page/scan. Returns (boxes, confidence) where boxes are cv2.minAreaRect tuples in image
    pixels, sorted top-to-bottom then left-to-right. confidence in 0..1."""
    import numpy as np, cv2
    a = np.asarray(img.convert("RGB")); H, W = a.shape[:2]
    s = 1200 / max(H, W) if max(H, W) > 1200 else 1.0
    sm = cv2.resize(a, (max(1, int(W * s)), max(1, int(H * s))), interpolation=cv2.INTER_AREA)
    h, w = sm.shape[:2]
    lab = cv2.cvtColor(sm, cv2.COLOR_RGB2LAB).astype(np.int16)
    bw = max(2, min(h, w) // 100)
    border = np.concatenate([lab[:bw].reshape(-1, 3), lab[-bw:].reshape(-1, 3), lab[:, :bw].reshape(-1, 3), lab[:, -bw:].reshape(-1, 3)])
    bg = np.median(border, axis=0)
    spread = np.median(np.abs(border - bg), axis=0).max()
    if spread > 18: return [], 0.0                       # busy background (table, hand-held photo): don't guess
    diff = np.abs(lab - bg).max(axis=2).astype(np.uint8)
    mask = (diff > max(8, 3 * spread)).astype(np.uint8) * 255
    g = cv2.GaussianBlur(cv2.cvtColor(sm, cv2.COLOR_RGB2GRAY), (5, 5), 0)
    mask |= cv2.dilate(cv2.Canny(g, 40, 120), np.ones((3, 3), np.uint8))
    k = max(3, min(h, w) // 120)
    # pass 1 finds card outlines; pass 2 (wider closing) joins the printing on white cards scanned on a white page
    for kk, strict in ((k, False), (3 * k, True)):
        m = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, cv2.getStructuringElement(cv2.MORPH_RECT, (kk, kk)))
        m = cv2.morphologyEx(m, cv2.MORPH_OPEN, np.ones((3, 3), np.uint8))
        r = _boxes(m, s, min_frac, strict)
        if len(r[0]) >= 2: return r
    return [], 0.0


def _boxes(mask, s, min_frac, strict):
    import numpy as np, cv2
    h, w = mask.shape[:2]
    cnts, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    good, other = [], []
    for c in cnts:
        area = cv2.contourArea(c)
        if area < 0.002 * h * w: continue
        (cx, cy), (rw, rh), ang = cv2.minAreaRect(c)
        if rw < 2 or rh < 2: continue
        rect = area / (rw * rh); ar = max(rw, rh) / min(rw, rh)
        item = ((cx / s, cy / s), (rw / s, rh / s), ang, rect, area, ar)
        if min_frac * h * w <= area <= 0.6 * h * w and rect >= 0.85 and 1.25 <= ar <= 2.1: good.append(item)
        else: other.append(item)
    if len(good) < 2: return [], 0.0
    med = float(np.median([g_[4] for g_ in good]))
    # a card whose outline came out ragged (photo-cropped card, dark corner) but is card-sized and roughly card-shaped
    # is kept too, at lower confidence; anything else counts against splitting
    rough = [o for o in other if 0.5 * med <= o[4] <= 1.5 * med and o[3] >= 0.7 and 1.15 <= o[5] <= 2.3]
    if strict: rough = []
    if any(o[4] >= 0.25 * med for o in other if o not in rough): return [], 0.0   # something card-sized we can't outline
    junk_area = sum(o[4] for o in other if o not in rough)
    areas = sorted(g_[4] for g_ in good + rough)
    if areas[-1] / areas[0] > 2.5: return [], 0.0        # cards on one sheet are about the same size
    good_area = sum(areas)
    if junk_area > 0.25 * good_area: return [], 0.0      # lots of non-card content: probably a single document
    allc = good + rough
    conf = (sum(g_[3] for g_ in allc) / len(allc)) * (good_area / (good_area + junk_area)) * (1 - 0.1 * len(rough) / len(allc))
    good = allc
    if len(good) > MAX_CARDS_PER_PAGE: return [], 0.0
    rowh = np.median([min(g_[1]) for g_ in good]) * 0.5
    good.sort(key=lambda g_: (round(g_[0][1] / rowh), g_[0][0]))
    return [g_[:3] for g_ in good], round(float(conf), 3)


def _crop(img, box, pad=0.02):
    """Warp one minAreaRect to an upright crop (corners ordered TL, TR, BR, BL; tilts up to 45 degrees)."""
    import numpy as np, cv2
    from PIL import Image
    (cx, cy), (rw, rh), ang = box
    q = cv2.boxPoints(((cx, cy), (rw * (1 + pad), rh * (1 + pad)), ang)).astype("float32")
    sm = q.sum(1); df = np.diff(q, axis=1).ravel()
    q = np.array([q[sm.argmin()], q[df.argmin()], q[sm.argmax()], q[df.argmax()]], dtype="float32")
    w = int(round(max(np.linalg.norm(q[1] - q[0]), np.linalg.norm(q[2] - q[3]))))
    h = int(round(max(np.linalg.norm(q[3] - q[0]), np.linalg.norm(q[2] - q[1]))))
    M = cv2.getPerspectiveTransform(q, np.array([[0, 0], [w, 0], [w, h], [0, h]], dtype="float32"))
    a = np.asarray(img.convert("RGB"))
    return Image.fromarray(cv2.warpPerspective(a, M, (w, h), flags=cv2.INTER_CUBIC, borderValue=(255, 255, 255)))


def split_cards(img, min_conf=0.8):
    """[img] unless the image clearly holds 2+ cards; then one cropped image per card."""
    boxes, conf = find_cards(img)
    if len(boxes) < 2 or conf < min_conf: return [img]
    return [_crop(img, b) for b in boxes]


def expand(data: bytes, fname: str, split_photos=True):
    """Upload bytes -> None (an ordinary photo: use as is) or a list of (jpeg_bytes, label). Raises FormatError."""
    import os
    base = os.path.basename(fname or "") or "upload"
    stem = os.path.splitext(base)[0]
    if is_pdf(data):
        out = []
        for p, n, im in pdf_pages(data):
            out += page_parts(im, stem, p, n); del im      # round 20: free each page before the next is rendered
        return out
    if is_heif(data):
        jpg = heif_to_jpeg(data)
        return _split_photo(jpg, stem, split_photos) or [(jpg, base + ".jpg")]   # round 22: 'card.heic.jpg' -> caption 'From: card.heic'
    if split_photos: return _split_photo(data, stem, True)
    return None


def _split_photo(data, stem, on):
    if not on: return None
    from PIL import Image
    try:
        im = Image.open(io.BytesIO(data), formats=RASTER)
        if im.size[0] * im.size[1] > DECODE_MAX_PIXELS: return None
        im.load()
        from PIL import ImageOps
        im = ImageOps.exif_transpose(im)
    except Exception:
        return None                                      # let the normal checks explain what's wrong
    parts = split_cards(im)
    if len(parts) < 2:
        if im.size[0] * im.size[1] > PHOTO_MAX_PIXELS: return [(to_jpeg(shrink(im)), stem + ".jpg")]   # round 20
        return None
    return [(to_jpeg(p), f"{stem} (card {k} of {len(parts)}).jpg") for k, p in enumerate(parts, 1)]


def is_jpeg(data: bytes) -> bool:
    return data[:3] == b"\xff\xd8\xff"


def normalize_photo(data: bytes) -> bytes:
    """For single-photo endpoints (back of card, /api/scan): HEIC/HEIF -> JPEG; PDF refused with a clear message."""
    if is_pdf(data): raise FormatError("Use a photo here (JPG, PNG or HEIC), not a PDF. PDFs can be added on the Scan page.")
    if is_heif(data): return heif_to_jpeg(data)
    return data
