"""Round 18: SYNTHETIC fixtures (fake people/companies) for PDF/HEIC tests. No real card images are used."""
import io, os, random
from PIL import Image, ImageDraw, ImageFont

FONT = os.path.join(os.path.dirname(__file__), "..", "fonts")
def _font(sz):
    for f in sorted(os.listdir(FONT)) if os.path.isdir(FONT) else []:
        if f.lower().endswith((".ttf", ".otf")):
            try: return ImageFont.truetype(os.path.join(FONT, f), sz)
            except Exception: pass
    return ImageFont.load_default(sz)

PEOPLE = [("Avery Testwell", "Operations Manager", "Example Widgets LLC", "avery@example.com", "330-555-0101"),
          ("Jordan Sample", "Director of Sales", "Fakeville Tooling Inc", "jordan.sample@example.org", "330-555-0102"),
          ("Riley Placeholder", "Owner", "Demo Bakery Co", "riley@demobakery.example", "234-555-0103"),
          ("Casey Mockford", "HR Coordinator", "Synthetic Systems", "cmockford@example.net", "330-555-0104"),
          ("Morgan Dummy", "CFO", "Lorem Ipsum Partners", "morgan@example.com", "330-555-0105"),
          ("Taylor Fixture", "Account Executive", "Northside Example Bank", "tfixture@example.com", "234-555-0106"),
          ("Quinn Specimen", "Engineer", "Testing Labs LLC", "quinn@example.org", "330-555-0107"),
          ("Drew Stub", "President", "Mock Roofing Inc", "drew@example.net", "330-555-0108"),
          ("Sam Notreal", "Marketing Lead", "Pretend Media", "sam@example.com", "330-555-0109"),
          ("Jamie Fakename", "Realtor", "Imaginary Homes", "jamie@example.org", "234-555-0110")]
COLORS = [(232, 240, 252), (255, 244, 225), (230, 246, 234), (250, 232, 240), (240, 236, 252), (224, 242, 245)]

def card(i, w=1050, h=600):
    p = PEOPLE[i % len(PEOPLE)]
    im = Image.new("RGB", (w, h), COLORS[i % len(COLORS)]); d = ImageDraw.Draw(im)
    d.rectangle([0, 0, w - 1, h - 1], outline=(90, 90, 110), width=4)
    d.rectangle([0, 0, w, 70], fill=(30 + 20 * (i % 5), 60, 120))
    d.text((40, 110), p[0], fill=(10, 10, 10), font=_font(64)); d.text((40, 195), p[1], fill=(40, 40, 40), font=_font(40))
    d.text((40, 265), p[2], fill=(20, 20, 60), font=_font(46))
    d.text((40, 400), p[3], fill=(0, 0, 0), font=_font(38)); d.text((40, 460), "Tel " + p[4], fill=(0, 0, 0), font=_font(38))
    return im

def sheet(idx, n=8, dpi=300, rot=True, seed=0):
    """Letter page at dpi with n cards (2 columns), small random tilt."""
    rnd = random.Random(seed); W, H = int(8.5 * dpi), int(11 * dpi)
    pg = Image.new("RGB", (W, H), (252, 252, 250))
    cw, ch = int(3.5 * dpi), int(2 * dpi)
    for k, i in enumerate(idx[:n]):
        c = card(i, cw, ch).convert("RGBA")
        if rot: c = c.rotate(rnd.uniform(-4, 4), expand=True, fillcolor=(0, 0, 0, 0))
        col, row = k % 2, k // 2
        x = int(0.45 * dpi + col * (cw + 0.5 * dpi) + rnd.uniform(-20, 20)); y = int(0.4 * dpi + row * (ch + 0.55 * dpi) + rnd.uniform(-20, 20))
        pg.paste(c, (x, y), c)
    return pg

def pdf(pages, dpi=300):
    b = io.BytesIO(); pages[0].save(b, "PDF", save_all=True, append_images=pages[1:], resolution=dpi); return b.getvalue()

def single_card_pdf():  return pdf([card(0)], 300)
def multipage_pdf():    return pdf([card(1), card(2), card(3)], 300)       # 3 pages, one card each
def multicard_pdf():    return pdf([sheet(range(0, 8), seed=1), sheet(range(2, 6), n=4, seed=2)], 300)   # 8 + 4 cards

def corrupt_pdf():
    return b"%PDF-1.7\n1 0 obj\n<< /Type /Catalog /Pages 2 0 R >>\nendobj\nthis is not really a pdf \x00\xff garbage\n%%EOF\n"

def encrypted_pdf():
    """Minimal PDF with a standard-security /Encrypt dict whose user password is not empty (O/U are random), so pdfium
    asks for a password."""
    objs = [b"<< /Type /Catalog /Pages 2 0 R >>", b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
            b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 252 144] >>",
            b"<< /Filter /Standard /V 2 /R 3 /Length 128 /P -1068 /O <" + b"11" * 32 + b"> /U <" + b"22" * 32 + b"> >>"]
    out = bytearray(b"%PDF-1.7\n"); offs = []
    for n, o in enumerate(objs, 1):
        offs.append(len(out)); out += b"%d 0 obj\n" % n + o + b"\nendobj\n"
    x = len(out); out += b"xref\n0 %d\n0000000000 65535 f \n" % (len(objs) + 1)
    for o in offs: out += b"%010d 00000 n \n" % o
    out += b"trailer\n<< /Size %d /Root 1 0 R /Encrypt 4 0 R /ID [<%s> <%s>] >>\nstartxref\n%d\n%%%%EOF\n" % (len(objs) + 1, b"ab" * 16, b"ab" * 16, x)
    return bytes(out)

def back_side(i=8, w=1050, h=600):
    im = Image.new("RGB", (w, h), COLORS[i % len(COLORS)]); d = ImageDraw.Draw(im)
    d.rectangle([0, 0, w - 1, h - 1], outline=(90, 90, 110), width=4)
    d.text((60, 220), "We build example widgets since 1999", fill=(20, 20, 60), font=_font(44))
    d.text((60, 320), "www.example-widgets.example", fill=(0, 0, 0), font=_font(40)); return im

def heic(i=4, orientation=None, im=None):
    import pillow_heif
    pillow_heif.register_heif_opener()
    im = card(i) if im is None else im
    if orientation == 6:            # stored rotated, EXIF says rotate 90 CW to display -> upright landscape card
        im = im.rotate(90, expand=True)
        ex = Image.Exif(); ex[0x0112] = 6
        b = io.BytesIO(); im.save(b, "HEIF", quality=90, exif=ex.tobytes()); return b.getvalue()
    b = io.BytesIO(); im.save(b, "HEIF", quality=90); return b.getvalue()

def flatbed_jpeg():
    b = io.BytesIO(); sheet(range(5, 9), n=4, dpi=200, seed=3).save(b, "JPEG", quality=90); return b.getvalue()

if __name__ == "__main__":
    import sys
    out = sys.argv[1] if len(sys.argv) > 1 else "/tmp/r18fx"; os.makedirs(out, exist_ok=True)
    for n, f in [("single.pdf", single_card_pdf), ("multipage.pdf", multipage_pdf), ("multicard.pdf", multicard_pdf),
                 ("corrupt.pdf", corrupt_pdf), ("encrypted.pdf", encrypted_pdf), ("card.heic", heic), ("rot6.heic", lambda: heic(5, 6)),
                 ("flatbed.jpg", flatbed_jpeg)]:
        open(os.path.join(out, n), "wb").write(f()); print(n)
