"""Round 18: HEIC/HEIF + PDF input and the multi-card splitter. All fixtures are synthetic (tests/r18/gen_r18.py)."""
import io, os, sys, time
import pytest
from PIL import Image
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "r18"))
import gen_r18 as G
from app import formats as F

pytest.importorskip("pillow_heif"); pytest.importorskip("pypdfium2")

def _sizes(parts): return [Image.open(io.BytesIO(d)).size for d, _ in parts]

def test_heic_converts_to_upright_jpeg():
    for data, want in ((G.heic(), (1050, 600)), (G.heic(5, 6), (1050, 600))):
        assert F.is_heif(data) and not F.is_pdf(data)
        parts = F.expand(data, "IMG_0001.HEIC"); assert len(parts) == 1
        jpg, name = parts[0]; assert name == "IMG_0001.HEIC.jpg" and F.is_jpeg(jpg)
        im = Image.open(io.BytesIO(jpg)); assert im.size == want and im.getexif().get(0x0112) in (None, 1)

def test_heic_damaged_is_friendly():
    bad = G.heic()[:200]
    with pytest.raises(F.FormatError, match="HEIC"): F.expand(bad, "x.heic")

def test_pdf_pages_and_labels():
    p = F.expand(G.single_card_pdf(), "one.pdf"); assert [n for _, n in p] == ["one.pdf (page 1 of 1)"]
    w, h = _sizes(p)[0]; assert 680 <= w <= 720 and 380 <= h <= 420    # 3.5x2 in rendered at 200 dpi (round 20)
    p = F.expand(G.multipage_pdf(), "m.pdf"); assert [n for _, n in p] == [f"m.pdf (page {i} of 3)" for i in (1, 2, 3)]

def test_pdf_multi_card_pages_are_split():
    p = F.expand(G.multicard_pdf(), "sheet.pdf"); names = [n for _, n in p]
    assert len(p) == 12 and names[0] == "sheet.pdf (page 1 of 2, card 1 of 8)" and names[-1] == "sheet.pdf (page 2 of 2, card 4 of 4)"
    for w, h in _sizes(p): assert 680 <= w <= 770 and 380 <= h <= 450, (w, h)   # one card each, upright (200 dpi, round 20)

def test_pdf_errors():
    with pytest.raises(F.FormatError, match="password"): F.expand(G.encrypted_pdf(), "e.pdf")
    with pytest.raises(F.FormatError, match="damaged"): F.expand(G.corrupt_pdf(), "c.pdf")
    many = G.pdf([Image.new("RGB", (100, 60), "white")] * 5, 72)
    with pytest.raises(F.FormatError, match="limit is 3"): list(F.pdf_pages(many, max_pages=3))

def test_pdf_javascript_is_not_run():
    """A PDF with an OpenAction JavaScript still renders (pdfium without forms never runs JS)."""
    js = G.single_card_pdf().replace(b"/Type /Catalog", b"/Type /Catalog /OpenAction << /S /JavaScript /JS (app.alert\\(1\\)) >>", 1)
    assert len(F.expand(js, "js.pdf")) == 1

def test_single_cards_never_split():
    for i in range(10):
        b = io.BytesIO(); G.card(i).save(b, "JPEG"); assert F.expand(b.getvalue(), "c.jpg") is None
    # a card photographed on a desk-like busy background
    import random; rnd = random.Random(1); bg = Image.effect_noise((1600, 1200), 60).convert("RGB")
    bg.paste(G.card(3), (rnd.randint(50, 400), rnd.randint(50, 400))); b = io.BytesIO(); bg.save(b, "JPEG")
    assert F.expand(b.getvalue(), "desk.jpg") is None
    one = Image.new("RGB", (2550, 3300), (252, 252, 250)); one.paste(G.card(2), (400, 500))
    assert len(F.split_cards(one)) == 1

def test_flatbed_photo_split():
    p = F.expand(G.flatbed_jpeg(), "scan.jpg"); assert [n for _, n in p] == [f"scan (card {k} of 4).jpg" for k in (1, 2, 3, 4)]

def _wait(rc, jid):
    for _ in range(600):
        st = rc.get("/api/jobs?ids=" + jid).json()["jobs"][0]
        if st["state"] in ("done", "error", "split", "cancelled"): return st
        time.sleep(0.2)
    return st

def test_upload_pdf_heic_via_api(env):
    rc = env["rev"]
    r = rc.post("/api/jobs", data={"batch": "r18-a", "batch_label": "R18 A"}, files={"image": ("cards.pdf", G.multipage_pdf(), "application/pdf")})
    # round 20: a PDF is ONE background job that renders page by page and adds the cards as children
    assert r.status_code == 200, r.text; j = r.json(); assert j["pdf"] and j["pages"] == 3
    j = _wait(rc, j["job"]); assert j["state"] == "split" and len(j["children"]) == 3 and all(x.get("job") for x in j["children"]); j["jobs"] = j["children"]
    sts = [_wait(rc, x["job"]) for x in j["jobs"]]; assert all(s["state"] == "done" for s in sts), sts
    fn = [env["ui"].meta(s["card"]["id"])["filename"] for s in sts]; assert fn == [f"cards.pdf (page {i} of 3)" for i in (1, 2, 3)]
    assert rc.get(f"/api/cards/{sts[0]['card']['id']}").json()["filename"] == "cards.pdf (page 1 of 3)"
    # same PDF again in the same batch: every page is a duplicate
    r = rc.post("/api/jobs", data={"batch": "r18-a", "batch_label": "R18 A"}, files={"image": ("cards.pdf", G.multipage_pdf(), "application/pdf")})
    assert r.status_code == 200; j2 = _wait(rc, r.json()["job"])
    assert j2["state"] == "error" and len(j2["children"]) == 3 and all(x["status"] == 409 for x in j2["children"])
    r = rc.post("/api/jobs", data={"batch": "r18-a", "batch_label": "R18 A"}, files={"image": ("IMG_7.heic", G.heic(), "image/heic")})
    assert r.status_code == 200 and "jobs" not in r.json(); st = _wait(rc, r.json()["job"]); assert st["state"] == "done"
    assert env["ui"].meta(st["card"]["id"])["filename"] == "IMG_7.heic.jpg"
    for bad, msg in ((G.encrypted_pdf(), "password"), (G.corrupt_pdf(), "damaged")):
        r = rc.post("/api/jobs", files={"image": ("x.pdf", bad, "application/pdf")}); assert r.status_code == 422 and msg in r.json()["error"]

def test_back_of_card_heic_ok_pdf_refused(env):
    rc = env["rev"]
    b = io.BytesIO(); G.card(6).save(b, "JPEG")
    st = _wait(rc, rc.post("/api/jobs", data={"batch": "r18-b"}, files={"image": ("f.jpg", b.getvalue(), "image/jpeg")}).json()["job"]); cid = st["card"]["id"]
    r = rc.post(f"/api/cards/{cid}/back", files={"image": ("b.pdf", G.single_card_pdf(), "application/pdf")}); assert r.status_code == 422 and "not a PDF" in r.json()["error"]
    r = rc.post(f"/api/cards/{cid}/back", data={"confirm_other_person": "1"}, files={"image": ("b.heic", G.heic(7), "image/heic")}); assert r.status_code == 200, r.text
    assert env["ui"].meta(cid).get("back_image", "").endswith(".jpg")

from test_r6_features import phone, _pair, _up   # noqa: F401,E402  (phone-mode fixtures)

def test_phone_mode_pdf_and_heic_front_back(env, phone):
    j, tok, pc = _pair(env, phone); pc.get("/m?t=" + tok)
    r = _up(pc, phone, tok, data=G.multipage_pdf()); assert r.status_code == 200, r.text
    d = r.json(); assert d["pdf"] and d["pages"] == 3
    st = _wait(env["rev"], d["job"]); assert st["state"] == "split" and len(st["children"]) == 3   # round 20: read in the background
    assert {x["id"] for x in pc.get("/m/api/jobs").json()["jobs"]} >= {c["job"] for c in st["children"]} | {d["job"]}
    r = _up(pc, phone, tok, data=G.heic(8), back=G.heic(im=G.back_side(8))); assert r.status_code == 200, r.text
    st = _wait(env["rev"], r.json()["job"]); assert st["state"] == "done"
    for _ in range(50):
        if env["ui"].meta(st["card"]["id"]).get("back_image"): break
        time.sleep(0.2)
    assert env["ui"].meta(st["card"]["id"]).get("back_image")
    assert _up(pc, phone, tok, data=G.encrypted_pdf()).status_code == 422
