"""Generate synthetic business cards (PIL) + ground truth JSON. Fictional people; 555 numbers."""
import json, random, os
from PIL import Image, ImageDraw, ImageFont, ImageFilter
random.seed(7); D = os.path.dirname(__file__)
F = "/usr/share/fonts/truetype/"
fonts = [F+"dejavu/DejaVuSans.ttf", F+"liberation/LiberationSerif-Regular.ttf", F+"liberation/LiberationSans-Regular.ttf"]
bold = [F+"dejavu/DejaVuSans-Bold.ttf", F+"liberation/LiberationSerif-Bold.ttf", F+"liberation/LiberationSans-Bold.ttf"]
CARDS = [
 dict(first_name="Maria", last_name="Delgado", title="Vice President, Commercial Lending", company="Summit Valley Bank",
      emails=["mdelgado@summitvalleybank.com"], phones=[("work","(330) 555-0142"),("mobile","(330) 555-0199")],
      website="www.summitvalleybank.com", address="200 S Main St, Suite 400, Akron, OH 44308", social=[]),
 dict(first_name="Derek", last_name="Lawson", title="Owner", company="Lawson Brothers Construction LLC",
      emails=["derek@lawsonbuilds.com"], phones=[("mobile","(234) 555-0110")], website="lawsonbuilds.com",
      address="1450 Canton Rd, Akron, OH 44312", social=["linkedin.com/in/dereklawson"]),
 dict(first_name="Priya", last_name="Raman", title="Director of Marketing", company="Firestone Park Health Clinic",
      emails=["praman@fphealth.org"], phones=[("work","(330) 555-0123"),("fax","(330) 555-0124")],
      website="www.fphealth.org", address="777 E Market St, Akron, OH 44305", social=["@fphealthakron"]),
 dict(first_name="James", last_name="Okafor", title="Sales Manager", company="Cuyahoga Falls Tire Co.",
      emails=["jokafor@cftire.com"], phones=[("work","(330) 555-0177"),("mobile","(330) 555-0188")],
      website="www.cftire.com", address="2300 State Rd, Cuyahoga Falls, OH 44223", social=[]),
 dict(first_name="Emily", last_name="Chen", title="Founder & CEO", company="Rubber City Robotics Inc",
      emails=["emily@rcrobotics.io"], phones=[("work","(330) 555-0150")], website="https://rcrobotics.io",
      address="47 N Main St, Akron, OH 44308", social=["linkedin.com/in/emilychen"]),
 dict(first_name="Robert", last_name="Hughes", title="Managing Partner", company="Hughes & Partners Law",
      emails=["rhughes@hugheslaw.com","info@hugheslaw.com"], phones=[("work","(330) 555-0190")],
      website="www.hugheslaw.com", address="1 Cascade Plaza, Akron, OH 44308", social=[]),
]
STYLES = ["left", "center", "dark", "noisy_rot", "left", "center"]
def draw(i, c, style):
    W, H = 1050, 600
    bg, fg = ((25,40,70),(240,240,240)) if style=="dark" else ((252,250,245),(20,20,30))
    im = Image.new("RGB", (W, H), bg); d = ImageDraw.Draw(im)
    fi = i % 3; fb = ImageFont.truetype(bold[fi], 46); fn = ImageFont.truetype(fonts[fi], 28); fs = ImageFont.truetype(fonts[fi], 32)
    pre = {"work": random.choice(["O: ","Office ","T: ","P "]), "mobile": random.choice(["C: ","Cell ","M: "]), "fax": "F: "}
    lines = [(c["company"], fb), (f"{c['first_name']} {c['last_name']}", fs), (c["title"], fn), ("", fn)]
    lines += [(pre[t]+n, fn) for t, n in c["phones"]] + [(e, fn) for e in c["emails"]] + [(c["website"], fn)]
    st, cz = c["address"].rsplit(", Akron",1) if ", Akron" in c["address"] else c["address"].rsplit(", ",2)[0], None
    a = c["address"]; k = a.index(", ", a.index(", ")+1) if a.count(",")>=3 else a.index(", ")
    lines += [(a[:k], fn), (a[k+2:], fn)] + [(s, fn) for s in c["social"]]
    y = 40
    for t, f in lines:
        w = d.textlength(t, font=f); x = (W-w)/2 if style=="center" else 60
        d.text((x, y), t, font=f, fill=fg); y += f.size + 12
    if style == "noisy_rot":
        im = im.rotate(3, expand=True, fillcolor=(200,200,200)).filter(ImageFilter.GaussianBlur(1.2))
        im = im.resize((im.width*2//3, im.height*2//3))
    p = os.path.join(D, "cards", f"card{i+1}_{style}.jpg"); im.save(p, quality=80); return p
if __name__ == "__main__":
    gt = {}
    for i, c in enumerate(CARDS):
        p = draw(i, c, STYLES[i]); gt[os.path.basename(p)] = {**c, "phones": [{"type":t,"number":n} for t,n in c["phones"]]}
    json.dump(gt, open(os.path.join(D, "ground_truth.json"), "w"), indent=1); print(list(gt))
