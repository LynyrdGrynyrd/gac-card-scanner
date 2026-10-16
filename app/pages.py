"""The /ui page, legacy URLs (redirects / 410) and card photos with cached thumbnails. Split out of app/ui.py (audit 2026-10 P2)."""
import os, re
from fastapi import HTTPException, Request
from fastapi.responses import HTMLResponse, FileResponse, Response, RedirectResponse, JSONResponse
from . import auth
from . import ui as U

# ---------------------------------------------------------------- pages (legacy URLs now lead to /ui)
@U.router.get("/ui")
def ui(request: Request):
    from . import demo
    if demo.enabled(): return demo.page(os.path.join(U.STATIC, "ui", "index.html"))
    r = auth.versioned_html(os.path.join(U.STATIC, "ui", "index.html")); r.headers["Cache-Control"] = "no-store"
    u = getattr(request.state, "user", None)
    if not u or u.get("role") != "admin": r = HTMLResponse(strip_admin(r.body.decode()), headers={"Cache-Control": "no-store"})
    return r

def strip_admin(html):
    """Round 15 (part-timer r14): a reviewer's page has no admin tables, labels or settings in its code. Only empty, hidden
    placeholders with the same ids stay, so the page script can still start."""
    m = re.search(r"<!--ADMIN-BEGIN-->(.*?)<!--ADMIN-END-->", html, re.S)
    if not m: return html
    ids = re.findall(r'\bid="([^"]+)"', m.group(1))
    return html[:m.start()] + '<div hidden aria-hidden="true">' + "".join(f'<span id="{i}"></span>' for i in ids) + "</div>" + html[m.end():]
@U.router.get("/app")
def app_alias(): return RedirectResponse("/ui", 307)
@U.router.get("/")
def legacy_home(): return RedirectResponse("/ui#upload", 307)
@U.router.get("/queue")
def legacy_queue(status: str = ""): return RedirectResponse(f"/ui#queue?s={status if status in ('pending','approved','rejected') else ''}", 307)
@U.router.get("/card/{cid}")
def legacy_card(cid: U.CardId): return RedirectResponse(f"/ui#review/{cid}", 307)
@U.router.post("/card/{cid}")
def legacy_card_post(cid: U.CardId):
    return JSONResponse({"error": "This old page was retired. Review cards at /ui so validation, duplicate and audit checks apply.", "use": f"/ui#review/{cid}"}, 410)
@U.router.post("/scan")
def legacy_scan(): return JSONResponse({"error": "This old upload form was retired. Scan cards at /ui.", "use": "/ui#upload"}, 410)
@U.router.get("/sync/dry-run")
@U.router.get("/sync/dry-run/{cid}")
def legacy_sync(cid: str = ""): return JSONResponse({"error": "Retired. Use Export → MC Trade import (Excel)."}, 410)
@U.router.get("/export.csv")
def legacy_csv(status: str = "approved"): return RedirectResponse(f"/ui#export", 307)
@U.router.get("/export.vcf")
def legacy_vcf(status: str = "approved"): return RedirectResponse(f"/ui#export", 307)
@U.router.get("/export.xlsx")
def legacy_xlsx(status: str = "approved"): return RedirectResponse(f"/ui#export", 307)
@U.router.get("/help")
@U.router.get("/ui/help")
def help_page():
    """v0.4.2 #10 (part-timer: raw {"detail":"Not Found"} when signed out): the reviewer guide, signed in or not."""
    return RedirectResponse("/static/ui/help.html", 307)

@U.router.get("/privacy")
def privacy(): return FileResponse(os.path.join(U.STATIC, "ui", "privacy.html"), headers={"Cache-Control": "no-cache"})

@U.router.get("/img/{name}")
def img(name: str, w: int = 0):
    if not name or "\x00" in name or len(name) > 200 or any(ord(ch) < 32 or ord(ch) == 127 for ch in name):
        raise HTTPException(404, "No such photo")
    p = os.path.join(U.UP, os.path.basename(name))
    if not os.path.isfile(p):
        try: drop_thumbs(name)
        except OSError: raise HTTPException(404, "No such photo")
        return Response(PLACEHOLDER, media_type="image/svg+xml", headers={"Cache-Control": "no-store"})
    if w:   # small cached thumbnail for the queue list instead of the full-resolution original
        t = _thumb(p, w)
        if t: return FileResponse(t, media_type="image/webp", headers={"Cache-Control": "private, max-age=3600"})
    return FileResponse(p, headers={"Cache-Control": "private, max-age=3600"})
THUMBS = os.path.join(U.DATA, "thumbs"); os.makedirs(THUMBS, exist_ok=True)

THUMB_SIZES = (160, 320)
def _thumb(p, w):
    """Return the path of a cached WebP thumbnail (width snapped to THUMB_SIZES), building it on first use. None on failure."""
    w = min(THUMB_SIZES, key=lambda s: abs(s - w)); base = os.path.basename(p)
    t = os.path.join(THUMBS, f"{base}.{w}.webp")
    try:
        if os.path.isfile(t) and os.path.getmtime(t) >= os.path.getmtime(p): return t
        from PIL import Image, ImageOps
        Image.MAX_IMAGE_PIXELS = U.MAX_PIXELS
        with Image.open(p, formats=U.FORMATS) as im:
            im = ImageOps.exif_transpose(im); im.draft("RGB", (w * 2, w * 2)); im = im.convert("RGB"); im.thumbnail((w, w * 2))
            tmp = t + ".tmp"; im.save(tmp, "WEBP", quality=70, method=4); os.replace(tmp, t)
        return t
    except Exception:
        return None
def remove_photo(name):
    """Audit 2026-10 F08: delete an uploaded photo AND every thumbnail made from it. Safe to repeat (missing files are fine).
    Use this wherever a front or back photo is deleted (retention, permanent delete, orphan clean-up)."""
    if not name: return
    try: os.remove(os.path.join(U.UP, os.path.basename(name)))
    except FileNotFoundError: pass
    drop_thumbs(name)
def drop_thumbs(name):
    """Delete cached thumbnails of a photo (called wherever the photo itself is deleted)."""
    if not name: return
    base = os.path.basename(name)
    for s_ in THUMB_SIZES:
        try: os.remove(os.path.join(THUMBS, f"{base}.{s_}.webp"))
        except FileNotFoundError: pass
PLACEHOLDER = b"""<svg xmlns="http://www.w3.org/2000/svg" width="420" height="240" viewBox="0 0 420 240"><rect width="420" height="240" fill="#eee"/><text x="210" y="112" text-anchor="middle" font-family="Lato,sans-serif" font-size="18" fill="#555">Photo deleted</text><text x="210" y="140" text-anchor="middle" font-family="Lato,sans-serif" font-size="13" fill="#777">(retention policy)</text></svg>"""

@U.router.get("/api/me")
def me(request: Request):
    # v0.4.2 #2 (part-timer blocker: shared sign-in): minutes without a click or key before the page signs out (0 = never)
    return auth.pub(request.state.user) | {"idle_minutes": auth.idle_minutes()}
