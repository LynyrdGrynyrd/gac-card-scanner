"""Generate the SAMPLE / FAKE MC Trade profile export used by the dry run.
Every person, company, email, phone and address here is invented. Phones use the fictional 555-01xx range,
generated emails use the reserved .example domain (RFC 2606), except a handful of "planted" records that
reuse the fictional domains of the scanner's own synthetic test cards so the dry run has realistic matches.

Column names: see COLUMNS.md. They follow the documented Atlas/MC Trade API profile fields
(https://api-v1.weblinkconnect.com/api-resources/Profile/PUT-Profile-id). The header row of a real
Profile Selector "Export All System Columns" CSV is NOT publicly documented -> UNVERIFIED.
Usage: python3 gen_sample.py   (deterministic; rewrites sample-data/)"""
import csv, random, os, datetime
from openpyxl import Workbook
from openpyxl.styles import Font, PatternFill

R = random.Random(20261013)
HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(HERE, "sample-data")
COLS = ["SAMPLE_FAKE", "ProfileId", "OrgInd", "ReportName", "OrgName", "Prefix", "FirstName", "LastName", "Title",
        "Email", "WorkPhone", "CellPhone", "Fax", "Website", "Address1", "Address2", "City", "State", "Zip",
        "Member", "Prospect", "Inactive", "MembershipLevelName", "MainRelatedProfileId", "MainRelatedProfileName",
        "AffCodes", "DateCreated", "DateChanged"]

PLACES = ["Summit", "Portage", "Cuyahoga", "Canal Park", "Rubber City", "Highland Square", "Firestone Park", "Goodyear Heights",
          "Ellet", "Wallhaven", "Merriman Valley", "Fairlawn", "Stow", "Hudson", "Tallmadge", "Barberton", "Copley", "Green",
          "Bath", "Peninsula", "North Hill", "Kenmore", "Middlebury", "Cascade", "Towpath", "Sand Run", "Riverbend", "Glendale",
          "Chapel Hill", "Lock Three", "Mogadore", "Munroe Falls", "Silver Lake", "Northampton", "Coventry"]
KINDS = [("Community Bank", "Banking"), ("Dental Group", "Health Care"), ("Insurance Agency", "Insurance"), ("Heating & Cooling", "Contractors"),
         ("Logistics LLC", "Transportation"), ("Law Group", "Legal"), ("Realty", "Real Estate"), ("Bakery", "Restaurants"),
         ("Brewing Co.", "Restaurants"), ("Family Medicine", "Health Care"), ("Credit Union", "Banking"), ("Print & Sign", "Printing"),
         ("Staffing Partners", "Employment"), ("IT Services Inc.", "Technology"), ("Landscaping", "Contractors"),
         ("Accounting Group", "Accounting"), ("Marketing Studio", "Marketing"), ("Construction Co.", "Contractors"),
         ("Auto Service", "Automotive"), ("Animal Hospital", "Veterinary"), ("Coffee Roasters", "Restaurants"),
         ("Engineering Inc.", "Engineering"), ("Physical Therapy", "Health Care"), ("Florist", "Retail"), ("Catering", "Restaurants"),
         ("Wealth Advisors", "Financial Services"), ("Plumbing", "Contractors"), ("Event Center", "Hospitality")]
FIRST = ["Aaron", "Abigail", "Alicia", "Andre", "Angela", "Anthony", "Ashley", "Benjamin", "Brandon", "Brianna", "Carla", "Carlos",
         "Catherine", "Chris", "Dana", "Daniel", "Deborah", "Denise", "Diane", "Dominic", "Elena", "Elijah", "Eric", "Erin", "Gabriel",
         "Grace", "Gregory", "Hannah", "Heather", "Isaac", "Jacob", "Jasmine", "Jennifer", "Jerome", "Joan", "Jonathan", "Julia",
         "Karen", "Keisha", "Kevin", "Kim", "Kyle", "Laura", "Lauren", "Leon", "Lisa", "Lucas", "Malik", "Marcus", "Megan",
         "Michael", "Monica", "Nathan", "Nicole", "Olivia", "Omar", "Patricia", "Paul", "Rachel", "Raymond", "Rebecca", "Ricardo",
         "Samantha", "Scott", "Sean", "Shannon", "Stephanie", "Steven", "Tamara", "Terrence", "Thomas", "Tiffany", "Todd",
         "Valerie", "Vanessa", "Victor", "Wendy", "William", "Yolanda", "Zachary"]
LAST = ["Adams", "Alvarez", "Baker", "Bell", "Bennett", "Brooks", "Bryant", "Campbell", "Carter", "Coleman", "Collins", "Cooper",
        "Diaz", "Dixon", "Edwards", "Evans", "Foster", "Freeman", "Garcia", "Gibson", "Graham", "Gray", "Greene", "Hamilton",
        "Harris", "Hayes", "Henderson", "Howard", "Jackson", "James", "Jenkins", "Kelly", "Kowalski", "Kim", "Lambert", "Long",
        "Marshall", "Mason", "McDonald", "Mitchell", "Moore", "Murphy", "Nguyen", "O'Neil", "Ortiz", "Palmer", "Patel", "Perry",
        "Phillips", "Porter", "Price", "Reed", "Reyes", "Richardson", "Rivera", "Roberts", "Russell", "Sanders", "Schultz",
        "Simmons", "Smith-Jones", "Stewart", "Sullivan", "Thompson", "Tucker", "Turner", "Wagner", "Walker", "Ward", "Watson",
        "Webb", "West", "Wilson", "Wright", "Young", "Zielinski"]
TITLES = ["Owner", "President", "Vice President", "Office Manager", "Marketing Director", "Sales Manager", "Account Executive",
          "Operations Manager", "Chief Financial Officer", "Branch Manager", "Human Resources Manager", "Executive Director",
          "Partner", "Practice Manager", "Business Development Manager", "Controller", "Project Manager", "Community Relations Manager"]
STREETS = ["S Main St", "N Main St", "W Market St", "E Market St", "Exchange St", "Copley Rd", "Kenmore Blvd", "Canton Rd",
           "State Rd", "Front St", "Portage Trail", "Cleveland-Massillon Rd", "Darrow Rd", "Graham Rd", "Wooster Rd", "Arlington St",
           "Merriman Rd", "Tallmadge Ave", "Brown St", "Mill St"]
CITIES = [("Akron", "44308"), ("Akron", "44311"), ("Akron", "44313"), ("Akron", "44320"), ("Akron", "44305"), ("Cuyahoga Falls", "44221"),
          ("Cuyahoga Falls", "44223"), ("Fairlawn", "44333"), ("Stow", "44224"), ("Hudson", "44236"), ("Tallmadge", "44278"),
          ("Barberton", "44203"), ("Green", "44232"), ("Copley", "44321")]
LEVELS = ["Small Business", "Small Business", "Small Business", "Growth", "Growth", "Leadership", "Nonprofit", "Corporate Partner"]

phones = [f"({a}) 555-01{n:02d}" for a in ("330", "234", "216", "440") for n in range(100)]
RESERVED = {"(330) 555-0142", "(330) 555-0177", "(330) 555-0109", "(330) 555-0190", "(234) 555-0133", "(330) 555-0123",
            "(330) 555-0124", "(330) 555-0161", "(234) 555-0110", "(330) 555-0150", "(330) 555-0157", "(234) 555-0104",
            "(216) 555-0198"}
phones = [p for p in phones if p not in RESERVED]; R.shuffle(phones)
def phone(): return phones.pop()
def slug(s): return "".join(ch for ch in s.lower() if ch.isalnum())
def d(y0=2012):
    t = datetime.date(y0, 1, 1) + datetime.timedelta(days=R.randrange(0, (datetime.date(2026, 9, 30) - datetime.date(y0, 1, 1)).days))
    return t.isoformat()

rows, pid = [], 1006
def add(**k):
    r = {c: "" for c in COLS}; r.update(SAMPLE_FAKE="SAMPLE-FAKE"); r.update(k); rows.append(r); return r
def org(name, domain=None, level=None, member=True, aff="", pid_=None, **k):
    global pid
    if pid_ is None: pid_ = pid; pid += 1
    domain = domain or slug(name)[:24] + ".example"
    city, z = R.choice(CITIES); created = d()
    return add(ProfileId=pid_, OrgInd="TRUE", ReportName=name, OrgName=name, Email=f"info@{domain}", WorkPhone=phone(),
               Website=f"www.{domain}", Address1=f"{R.randrange(10, 3999)} {R.choice(STREETS)}", City=city, State="OH", Zip=z,
               Member="TRUE" if member else "FALSE", Prospect="FALSE" if member else "TRUE", Inactive="FALSE",
               MembershipLevelName=(level or R.choice(LEVELS)) if member else "", AffCodes=aff, DateCreated=created,
               DateChanged=max(created, d(2023)), **k)
def ind(first, last, o, title=None, email=None, pid_=None, cell=True, inactive=False, aff="", **k):
    global pid
    if pid_ is None: pid_ = pid; pid += 1
    dom = o["Website"].replace("www.", "")
    email = email if email is not None else f"{first[0].lower()}{slug(last)}@{dom}"
    created = d(2015); k.setdefault("WorkPhone", o["WorkPhone"])
    for f_ in ("Address1", "City", "Zip"): k.setdefault(f_, o[f_])
    return add(ProfileId=pid_, OrgInd="FALSE", ReportName=f"{first} {last}", FirstName=first, LastName=last,
               Title=title or R.choice(TITLES), Email=email, CellPhone=phone() if cell else "",
               State="OH", Member=o["Member"], Prospect=o["Prospect"],
               Inactive="TRUE" if inactive else "FALSE", MainRelatedProfileId=o["ProfileId"], MainRelatedProfileName=o["OrgName"],
               AffCodes=aff, DateCreated=created, DateChanged=max(created, d(2023)), **k)

# ---- planted records (the scanner's fictional test people), so the dry run shows every outcome ----
svb = org("Summit Valley Bank", "summitvalleybank.com", "Corporate Partner", pid_=2001, aff="Ambassadors")
cft = org("Cuyahoga Falls Tire Co.", "cftire.com", "Growth", pid_=2002)
arr = org("Akron Riverfront Realty LLC", "akronriverfront.com", pid_=2003)
hpl = org("Hughes & Partners Law", "hugheslaw.com", "Leadership", pid_=2004)
plc = org("Portage Lakes Consulting Group", "plcg.net", pid_=2005)
fph = org("Firestone Park Health Clinic", "fphealth.org", "Nonprofit")
nsb = org("Northside Bakehouse", "northsidebakehouse.com", "Small Business")
ahb = org("Akron Home Builders", "akronhomebuilders.example", "Growth")
mtd = org("Martinez Dental", "martinez.com", "Small Business")
lwb = org("Lewis Bank", "lewis.com", "Corporate Partner")
glf = org("Glass Law Firm", "glass.org", "Small Business")
ind("Maria", "Delgado", svb, "Vice President", "mdelgado@summitvalleybank.com", pid_=1001, cell=False, WorkPhone="(330) 555-0142",
    Address1="200 S Main St, Suite 400", City="Akron", Zip="44308")
ind("James", "Okafor", cft, "Sales Manager", "jokafor@cftire.com", pid_=1002, WorkPhone="(330) 555-0177")
ind("Linda", "Park", arr, "Broker", "linda@akronriverfront.com", pid_=1003, WorkPhone="(330) 555-0109")
ind("Robert", "Hughes", hpl, "Partner", "rhughes@hugheslaw.com", pid_=1004, WorkPhone="(330) 555-0190", Address1="1 Cascade Plaza", City="Akron", Zip="44308")
ind("Sarah", "Whitman", plc, "Principal", "sarah.whitman@plcg.net", pid_=1005, WorkPhone="(234) 555-0133")
ind("Priya", "Raman", fph, "Marketing Coordinator", "priya.raman@fphealth.org")          # same person, older email -> review
ind("Derek", "Lawson", ahb, "Site Supervisor", "dlawson@akronhomebuilders.example")     # changed jobs? -> review
ind("Sarah", "Rowland", mtd, "Office Manager", "srowland@martinez.com")                 # email exact -> update
ind("Christina", "Jones", lwb, "Branch Manager", "christina.jones@lewis.com")           # CRM has her twice ->
ind("Christina", "Jones", lwb, "Branch Manager", "christina.jones@lewis.com", cell=False)  # ... review
ind("Shaun", "Castro", glf, "Attorney", "shaun.castro@glass.org")                       # reviewer said "create new" -> review
o1 = org(f"{R.choice(PLACES)} {R.choice(KINDS)[0]}"); o2 = org(f"{R.choice(PLACES)} {R.choice(KINDS)[0]}")
ind("Emily", "Chen", o1); ind("Emily", "Chen", o2)                                      # namesakes -> review
ind("Paul", "Dixon", cft, "Former Sales Rep", inactive=True)

# ---- background: invented organizations and their people, to 300 profiles ----
used = {r["OrgName"] for r in rows}
orgs = [r for r in rows if r["OrgInd"] == "TRUE"]
while len(orgs) < 105:
    k = R.choice(KINDS)[0]; n = f"{R.choice(PLACES)} {k}"
    if n in used: continue
    used.add(n); orgs.append(org(n, member=R.random() > 0.15, aff=R.choice(["", "", "", "Newsletter", "Young Professionals", "Ambassadors"])))
names = set((r["FirstName"], r["LastName"]) for r in rows)
while len(rows) < 300:
    f, l = R.choice(FIRST), R.choice(LAST)
    if (f, l) in names: continue
    names.add((f, l)); o = R.choice(orgs)
    r = ind(f, l, o, inactive=R.random() < 0.05, aff=R.choice(["", "", "Newsletter", "Leadership Akron"]))
    if R.random() < 0.06: r["Email"] = ""                       # realistic gaps
    if R.random() < 0.04: r["Email"] = o["Email"]               # shared info@ address

rows.sort(key=lambda r: int(r["ProfileId"]))
os.makedirs(OUT, exist_ok=True)
fn = os.path.join(OUT, "SAMPLE-FAKE_mctrade_profiles_export.csv")
with open(fn, "w", newline="") as fh:
    w = csv.DictWriter(fh, COLS); w.writeheader(); w.writerows(rows)
# same data in the scanner's existing_contacts.csv shape (profile_id,first_name,last_name,organization,email,phone)
with open(os.path.join(OUT, "SAMPLE-FAKE_existing_contacts_for_scanner.csv"), "w", newline="") as fh:
    w = csv.writer(fh); w.writerow(["profile_id", "first_name", "last_name", "organization", "email", "phone"])
    for r in rows:
        if r["OrgInd"] == "FALSE" and r["Inactive"] == "FALSE":
            w.writerow([r["ProfileId"], r["FirstName"], r["LastName"], r["MainRelatedProfileName"], r["Email"], r["WorkPhone"]])
wb = Workbook(); ws = wb.active; ws.title = "SAMPLE-FAKE profiles"; ws.append(COLS)
for r in rows: ws.append([r[c] for c in COLS])
for c in ws[1]: c.font = Font(bold=True); c.fill = PatternFill("solid", fgColor="FFF3CD")
ws.freeze_panes = "B2"
n = wb.create_sheet("READ ME", 0)
for line in ["SAMPLE / FAKE DATA: NOT a real MC Trade export. Every person, company, email and phone is invented.",
             "Built for the GAC card-scanner dry run from public MC Trade / WebLink (Atlas) documentation.",
             "Column names follow the documented API profile fields; the real 'Export All System Columns' header row is UNVERIFIED.",
             "See mctrade-dryrun/COLUMNS.md and DOCS-NOTES.md for sources.",
             f"{sum(r['OrgInd']=='TRUE' for r in rows)} organization profiles, {sum(r['OrgInd']=='FALSE' for r in rows)} individual profiles."]:
    n.append([line])
n["A1"].font = Font(bold=True, color="B3261E", size=14); n.column_dimensions["A"].width = 120
wb.save(os.path.join(OUT, "SAMPLE-FAKE_mctrade_profiles_export.xlsx"))
print(len(rows), "profiles:", sum(r["OrgInd"] == "TRUE" for r in rows), "orgs,", sum(r["OrgInd"] == "FALSE" for r in rows), "individuals ->", fn)
