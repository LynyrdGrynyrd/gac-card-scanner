"""Harder synthetic cards: 2-column layout, ALL-CAPS name, no company keyword, perspective+shadow 'photo', low-res, script-ish font."""
import json, os, random
from PIL import Image, ImageDraw, ImageFont, ImageFilter
D = os.path.dirname(__file__); F = "/usr/share/fonts/truetype/"; random.seed(3)
gt = json.load(open(os.path.join(D, "ground_truth.json")))
def save(im, name, g): im.save(os.path.join(D,"cards",name), quality=70); gt[name] = g
# H1: two columns, all-caps name, company without keyword
im = Image.new("RGB",(1050,600),(255,255,255)); d = ImageDraw.Draw(im)
b = ImageFont.truetype(F+"dejavu/DejaVuSans-Bold.ttf",40); r = ImageFont.truetype(F+"dejavu/DejaVuSans.ttf",24)
d.rectangle([0,0,1050,90], fill=(0,90,60)); d.text((40,22),"Northside Bakehouse",font=b,fill=(255,255,255))
d.text((40,140),"TANYA BROOKS",font=b,fill=(0,0,0)); d.text((40,200),"Head Baker",font=r,fill=(80,80,80))
for i,t in enumerate(["T 330.555.0161","tanya@northsidebakehouse.com","northsidebakehouse.com"]): d.text((560,140+i*45),t,font=r,fill=(0,0,0))
for i,t in enumerate(["21 Furnace St","Akron, OH 44304"]): d.text((40,400+i*40),t,font=r,fill=(0,0,0))
save(im,"hard1_twocol.jpg",dict(first_name="Tanya",last_name="Brooks",title="Head Baker",company="Northside Bakehouse",
 emails=["tanya@northsidebakehouse.com"],phones=[{"type":"work","number":"(330) 555-0161"}],website="northsidebakehouse.com",
 address="21 Furnace St, Akron, OH 44304",social=[]))
# H2: phone-photo simulation: perspective, shadow gradient, blur, low res
src = Image.open(os.path.join(D,"cards","card4_noisy_rot.jpg")).convert("RGB").resize((1050,600))
bg = Image.new("RGB",(1300,900),(110,95,80)); bg.paste(src,(120,140))
bg = bg.transform(bg.size, Image.PERSPECTIVE, (1.05,0.08,-40, 0.03,1.0,-20, 0.00012,0.00005), Image.BICUBIC)
sh = Image.linear_gradient("L").resize(bg.size).point(lambda v: 160+v*95//255)
bg = Image.composite(bg, Image.new("RGB",bg.size,(0,0,0)), sh).filter(ImageFilter.GaussianBlur(1.6)).resize((650,450))
save(bg,"hard2_photo.jpg",dict(gt["card4_noisy_rot.jpg"]))
# H3: tiny low-res serif italic
im = Image.new("RGB",(525,300),(245,240,230)); d = ImageDraw.Draw(im)
it = ImageFont.truetype(F+"liberation/LiberationSerif-Italic.ttf",15); bi = ImageFont.truetype(F+"liberation/LiberationSerif-BoldItalic.ttf",24)
y=20
for t,f in [("Gerald Vance, CPA",bi),("Senior Tax Advisor",it),("Vance & Kohl Accounting Group",it),("",it),("Office (330) 555-0135 | Cell (330) 555-0136",it),
            ("gvance@vancekohl.com",it),("www.vancekohl.com",it),("3800 Embassy Pkwy, Akron, OH 44333",it)]:
    d.text((25,y),t,font=f,fill=(40,30,20)); y += f.size+10
save(im,"hard3_lowres_italic.jpg",dict(first_name="Gerald",last_name="Vance",title="Senior Tax Advisor",company="Vance & Kohl Accounting Group",
 emails=["gvance@vancekohl.com"],phones=[{"type":"work","number":"(330) 555-0135"},{"type":"mobile","number":"(330) 555-0136"}],
 website="www.vancekohl.com",address="3800 Embassy Pkwy, Akron, OH 44333",social=[]))
json.dump(gt, open(os.path.join(D,"ground_truth.json"),"w"), indent=1)
