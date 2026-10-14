"""Richer synthetic benchmark: 48 cards with realistic fonts, layouts and photo effects. Fictional data (Faker, 555 numbers).
Categories: left/center/right/two-column/vertical/footer-row/logo-band, dark/colored bg, all-caps, script name,
credentials, extensions, PO boxes, suites, multi phone/email, toll-free, QR vCard, phone-photo (perspective, shadow, glare, blur)."""
import json, os, random, math
from PIL import Image, ImageDraw, ImageFont, ImageFilter, ImageEnhance
import numpy as np, qrcode
from faker import Faker
D = os.path.dirname(os.path.abspath(__file__)); OUT = os.path.join(D, "synth2"); os.makedirs(OUT, exist_ok=True)
FD = os.path.join(D, "fonts"); fk = Faker("en_US"); Faker.seed(11); random.seed(11); np.random.seed(11)
SANS = ["Lato-Regular", "Montserrat", "OpenSans", "Raleway", "SourceSans3", "Oswald"]; SERIF = ["PlayfairDisplay", "Cinzel"]; SCRIPT = ["GreatVibes-Regular", "DancingScript"]
def font(name, size):
    p = os.path.join(FD, name + ".ttf")
    f = ImageFont.truetype(p, size)
    try:
        names = [n.decode() if isinstance(n, bytes) else n for n in f.get_variation_names()]
        f.set_variation_by_name("Regular" if "Regular" in names else names[min(3, len(names)-1)])
    except Exception: pass
    return f
TITLES = ["Vice President, Commercial Lending", "Director of Marketing", "Owner", "Sales Manager", "Founder & CEO", "Managing Partner",
          "Senior Account Executive", "Office Manager", "Chief Financial Officer", "Business Development Manager", "Realtor", "Attorney at Law",
          "Project Engineer", "HR Director", "Executive Director", "Branch Manager", "Insurance Agent", "Financial Advisor", "Principal", "Operations Manager"]
SUFFIX = ["LLC", "Inc.", "Group", "& Associates", "Consulting", "Construction", "Insurance Agency", "Bank", "Law Firm", "Realty", "Dental", "Manufacturing Co."]
DEPTS = ["Department of Engineering", "Office of Admissions", "School of Business", "Division of Research"]
CITIES = [("Akron", "OH", "443"), ("Cuyahoga Falls", "OH", "442"), ("Stow", "OH", "442"), ("Hudson", "OH", "442"), ("Fairlawn", "OH", "443"),
          ("Canton", "OH", "447"), ("Cleveland", "OH", "441"), ("Kent", "OH", "442"), ("Barberton", "OH", "442"), ("Medina", "OH", "442")]
def phone(fmt):
    a, b = random.choice(["330", "234", "216", "440"]), f"01{random.randint(0, 99):02d}"
    return {0: f"({a}) 555-{b}", 1: f"{a}.555.{b}", 2: f"{a}-555-{b}", 3: f"+1 {a} 555 {b}"}[fmt]
def make(i):
    first, last = fk.first_name(), fk.last_name()
    base = fk.last_name() if random.random() < 0.5 else fk.word().capitalize() + " " + fk.word().capitalize()
    company = f"{base} {random.choice(SUFFIX)}"
    dom = "".join(ch for ch in base.lower() if ch.isalnum())[:14] + random.choice([".com", ".com", ".net", ".org", ".co"])
    city, st, zp = random.choice(CITIES)
    street = f"{random.randint(10, 9999)} {fk.street_name()} {random.choice(['St', 'Ave', 'Rd', 'Blvd', 'Dr', 'Pkwy'])}"
    if random.random() < 0.3: street += f", Suite {random.randint(100, 950)}"
    if random.random() < 0.12: street = f"P.O. Box {random.randint(100, 9999)}"
    zipc = zp + f"{random.randint(0, 99):02d}"
    fmt = random.randint(0, 3)
    phones = [{"type": "work", "number": phone(fmt)}]
    if random.random() < 0.15: phones[0]["number"] += f" ext. {random.randint(10, 999)}"
    for t_, pr in (("mobile", 0.55), ("fax", 0.25)):
        if random.random() < pr:
            n_ = phone(fmt)
            while any(n_[-4:] == q["number"][-4:] for q in phones): n_ = phone(fmt)
            phones.append({"type": t_, "number": n_})
    if random.random() < 0.1: phones.append({"type": "work", "number": f"1-800-555-{random.randint(100, 199):04d}"})
    emails = [f"{first[0].lower()}{last.lower()}@{dom}" if random.random() < .5 else f"{first.lower()}.{last.lower()}@{dom}"]
    if random.random() < 0.15: emails.append(f"info@{dom}")
    cred = random.choice(["", "", "", "", ", MBA", ", CPA", ", PhD", ", Esq."])
    c = dict(first_name=first, last_name=last, title=random.choice(TITLES), company=company,
             department=random.choice(DEPTS) if random.random() < 0.1 else "", emails=emails, phones=phones,
             website=("www." if random.random() < .7 else "") + dom, address=f"{street}, {city}, {st} {zipc}", cred=cred)
    return c
LAB = {"work": ["O: ", "Office ", "T ", "P: ", "Tel ", "Direct: ", ""], "mobile": ["C: ", "Cell ", "M ", "Mobile: "], "fax": ["F: ", "Fax "]}
def contact_lines(c):
    L = []
    for p in c["phones"]:
        lab = random.choice(LAB[p["type"]]) if p["type"] != "work" or "800" not in p["number"] else "Toll Free "
        L.append(lab + p["number"])
    L += c["emails"]; L.append(c["website"]); return L
def addr_lines(c):
    a = c["address"].split(", "); return [", ".join(a[:-2]), ", ".join(a[-2:])]
def render(i, c, layout, theme):
    W, H = (600, 1050) if layout == "vertical" else (1050, 600)
    bg, fg, acc = {"light": ((250, 249, 245), (25, 25, 35), (0, 90, 140)), "dark": ((28, 32, 48), (238, 238, 238), (239, 103, 40)),
                   "color": ((56, 138, 156), (255, 255, 255), (255, 230, 150)), "cream": ((245, 238, 220), (60, 40, 30), (140, 30, 30))}[theme]
    im = Image.new("RGB", (W, H), bg); d = ImageDraw.Draw(im)
    sans = random.choice(SANS); serif = random.choice(SERIF + SANS)
    caps = random.random() < 0.25; script = random.random() < 0.12
    name = f"{c['first_name']} {c['last_name']}" + c["cred"]
    name_t = name.upper() if caps else name
    fN = font(random.choice(SCRIPT) if script else serif, 54 if script else 40); fC = font(serif, 44); fT = font(sans, 26); fS = font(sans, 25)
    # logo: shape + company
    lx, ly = 50, 40
    shape = random.choice(["circle", "square", "tri", "none"])
    if shape != "none":
        box = [lx, ly, lx + 70, ly + 70]
        {"circle": d.ellipse, "square": d.rectangle}.get(shape, lambda b, fill: d.polygon([(lx, ly + 70), (lx + 35, ly), (lx + 70, ly + 70)], fill=fill))(box, fill=acc)
        lx += 90
    comp = c["company"].upper() if random.random() < 0.4 else c["company"]
    def text(x, y, t, f, fill=fg, anchor="la"): d.text((x, y), t, font=f, fill=fill, anchor=anchor); return y + f.size + 10
    cl = contact_lines(c); al = addr_lines(c)
    if c["department"]: dl = [c["department"]]
    else: dl = []
    if layout in ("left", "logo-band"):
        if layout == "logo-band": d.rectangle([0, 0, W, 130], fill=acc); text(lx, 45, comp, fC, fill=bg)
        else: text(lx, 50, comp, fC, fill=acc)
        y = 170; y = text(50, y, name_t, fN); y = text(50, y, c["title"], fT)
        for t in dl: y = text(50, y, t, fT)
        y += 10
        for t in cl + al: y = text(50, y, t, fS)
    elif layout == "center":
        y = 40; y = text(W // 2, y, comp, fC, fill=acc, anchor="ma") + 25
        y = text(W // 2, y, name_t, fN, anchor="ma"); y = text(W // 2, y, c["title"], fT, anchor="ma")
        for t in dl: y = text(W // 2, y, t, fT, anchor="ma")
        y += 15
        for t in cl + al: y = text(W // 2, y, t, fS, anchor="ma")
    elif layout == "right":
        text(lx, 50, comp, fC, fill=acc); y = 180
        y = text(W - 50, y, name_t, fN, anchor="ra"); y = text(W - 50, y, c["title"], fT, anchor="ra")
        for t in dl: y = text(W - 50, y, t, fT, anchor="ra")
        y += 10
        for t in cl + al: y = text(W - 50, y, t, fS, anchor="ra")
    elif layout == "two-column":
        text(lx, 50, comp, fC, fill=acc); y = 190; y = text(50, y, name_t, fN); y = text(50, y, c["title"], fT)
        for t in dl: y = text(50, y, t, fT)
        y += 10
        for t in al: y = text(50, y, t, fS)
        y = 190
        for t in cl: y = text(560, y, t, fS)
    elif layout == "footer-row":
        y = 50; y = text(W // 2, y, comp, fC, fill=acc, anchor="ma") + 30; y = text(W // 2, y, name_t, fN, anchor="ma"); y = text(W // 2, y, c["title"], fT, anchor="ma")
        cols = [cl[: (len(cl) + 1) // 2], cl[(len(cl) + 1) // 2:], al]
        for k, col in enumerate(cols):
            yy = 420 - 10 * max(0, len(col) - 3)
            for t in col: yy = text(40 + k * 340, yy, t, font(sans, 20))
    elif layout == "vertical":
        y = 60; y = text(W // 2, y, comp, font(serif, 38), fill=acc, anchor="ma") + 60
        y = text(W // 2, y, name_t, font(serif if not script else SCRIPT[0], 40), anchor="ma"); y = text(W // 2, y, c["title"], fT, anchor="ma")
        for t in dl: y = text(W // 2, y, t, fT, anchor="ma")
        y += 40
        for t in cl + al: y = text(W // 2, y, t, fS, anchor="ma")
    qr = random.random() < 0.35 and layout in ("left", "logo-band", "center")
    if qr:
        v = f"BEGIN:VCARD\nVERSION:3.0\nN:{c['last_name']};{c['first_name']}\nFN:{c['first_name']} {c['last_name']}\nORG:{c['company']}\nTITLE:{c['title']}\n" + \
            "".join(f"TEL;TYPE={ {'work':'WORK','mobile':'CELL','fax':'FAX'}[p['type']]}:{p['number']}\n" for p in c["phones"]) + \
            "".join(f"EMAIL:{e}\n" for e in c["emails"]) + f"URL:{c['website']}\nADR;TYPE=WORK:;;{c['address'].rsplit(', ', 2)[0]};{c['address'].rsplit(', ', 2)[1]};{c['address'].split()[-2]};{c['address'].split()[-1]};\nEND:VCARD"
        q = qrcode.make(v).convert("RGB").resize((210, 210), Image.NEAREST)
        if layout == "center": im = im.resize((W, H)); new = Image.new("RGB", (W + 240, H), bg); new.paste(im, (0, 0)); im = new; W += 240
        im.paste(q, (W - 230, H - 230))
    return im, dict(caps=caps, script=script, qr=qr)
def photo(im, strength):
    W, H = im.size; bgc = tuple(int(x) for x in np.random.randint(60, 160, 3))
    noise = (np.random.rand(H + 400, W + 400, 1) * 40 - 20)
    bg = np.clip(np.array(Image.new("RGB", (W + 400, H + 400), bgc), dtype=float) + noise, 0, 255).astype("uint8")
    bg = Image.fromarray(bg).filter(ImageFilter.GaussianBlur(2)); bg.paste(im, (200, 200))
    s = 0.06 * strength
    coeffs = (1 + random.uniform(-s, s), random.uniform(-s, s), random.uniform(-15, 15), random.uniform(-s, s), 1 + random.uniform(-s, s),
              random.uniform(-15, 15), random.uniform(-2e-4, 2e-4) * strength, random.uniform(-2e-4, 2e-4) * strength)
    bg = bg.transform(bg.size, Image.PERSPECTIVE, coeffs, Image.BICUBIC)
    bg = bg.rotate(random.uniform(-6, 6) * strength, resample=Image.BICUBIC, fillcolor=bgc, expand=True)
    a = np.array(bg, dtype=float); yy, xx = np.mgrid[0:a.shape[0], 0:a.shape[1]]
    sh = 0.65 + 0.35 * (xx / a.shape[1] if random.random() < .5 else yy / a.shape[0]); a *= sh[..., None]
    if random.random() < 0.4:
        cx, cy = random.randint(0, a.shape[1]), random.randint(0, a.shape[0]); g = np.exp(-(((xx - cx) ** 2 + (yy - cy) ** 2) / (2 * 120 ** 2)))
        a = a + 120 * g[..., None]
    bg = Image.fromarray(np.clip(a, 0, 255).astype("uint8")).filter(ImageFilter.GaussianBlur(0.6 + 0.8 * strength))
    return bg.resize((int(bg.width * 0.75), int(bg.height * 0.75)))
if __name__ == "__main__":
    layouts = ["left", "center", "right", "two-column", "footer-row", "vertical", "logo-band"]
    themes = ["light", "light", "dark", "color", "cream"]
    gt = {}
    for i in range(48):
        c = make(i); lay = layouts[i % len(layouts)]; th = themes[(i // len(layouts)) % len(themes)] if i % 3 else "light"
        im, flags = render(i, c, lay, th)
        ph = i % 2 == 1
        if ph: im = photo(im, 0.6 + 0.8 * random.random())
        fn = f"s2_{i:02d}_{lay}_{th}{'_photo' if ph else ''}.jpg"; im.save(os.path.join(OUT, fn), quality=random.randint(70, 92))
        cats = [lay, th] + (["phone-photo"] if ph else ["flat"]) + [k for k, v in flags.items() if v] + \
               (["credentials"] if c["cred"] else []) + (["extension"] if "ext" in c["phones"][0]["number"] else []) + \
               (["po-box"] if "Box" in c["address"] else []) + (["suite"] if "Suite" in c["address"] else []) + \
               (["multi-phone"] if len(c["phones"]) > 2 else []) + (["multi-email"] if len(c["emails"]) > 1 else []) + (["department"] if c["department"] else [])
        g = {k: v for k, v in c.items() if k != "cred"}; g["cat"] = cats; gt[fn] = g
    json.dump(gt, open(os.path.join(D, "synth2_gt.json"), "w"), indent=1); print(len(gt))
