"""Business-card field parser v2: normalization + candidate scoring (no hardcoded cards).
Signals: regex/phonenumbers, first-name lexicon (gender_guesser, ~40k names), email<->name and domain<->company
cross-checks, title lexicon, address grammar (US + common intl), layout meta (header band, font size, column)."""
import re, phonenumbers
from difflib import SequenceMatcher
try:   # required (requirements.txt). Without it first/last-name ordering is weaker, so say so loudly instead of silently differing.
    import gender_guesser.detector as _gg; _GD = _gg.Detector(case_sensitive=False)
    NAME_LEXICON_ERROR = None
except Exception as _e:
    _GD = None; NAME_LEXICON_ERROR = f"{type(_e).__name__}: {_e}"
    import logging as _lg, warnings as _w
    _msg = ("gender_guesser (first-name lexicon) is not installed: name parsing will be LESS accurate and differ from tested "
            f"installs. Fix: .venv/bin/pip install -r requirements.txt ({NAME_LEXICON_ERROR})")
    _lg.getLogger("gac").error(_msg); _w.warn(_msg, RuntimeWarning, stacklevel=1)

EMAIL = re.compile(r"[\w.+'-]+@[\w-]+(?:\.[\w-]+)+")
# audit 2026-10: 'tom@hillco.com.tel' -> a label word glued after a complete domain ('.tel' alone is a real ending, kept)
EMAIL_LABEL_TAIL = re.compile(r"(\.(?:com|org|net|edu|gov|biz|info|us|io|co|uk|ca|de))\.(?:tel|fax|cell|phone|ph|mob|mobile|web|www|email|mail|office|direct|main)$", re.I)
def clean_email(e): return EMAIL_LABEL_TAIL.sub(r"\1", e)
TLD = r"(?:com|org|net|edu|gov|io|co|us|biz|info|ai|app|de|uk|au|es|fr|it|kr|jp|ca|nz|ie|nl|be|ch|at|se|no|dk|vn|cn|hk|tw|in|mx|br)"
# audit 2026-10: common newer gTLDs / more ccTLDs ('raybuilds.tech' became the company). Only taken when written in lower case or after www/http.
NEW_TLDS = ("tech legal law pro dev me tv cc xyz online site store shop club live life world today agency studio design media digital solutions "
            "services consulting company group global network systems works team center care health dental clinic realty properties homes "
            "house build builders construction energy finance financial capital fund insurance money tax accountant partners management "
            "marketing events education academy school university college church art photography photos gallery cafe restaurant coffee bar "
            "farm garden auto cars repair plumbing tools supply equipment industries engineering fitness salon spa beauty coach expert email "
            "news blog press name mobi city ventures holdings enterprises international inc llc ltd eu fi pl pt ru gr tr il ae za sg my ph "
            "cz hu ro lu cl ar pe").split()
KNOWN_TLDS = set(TLD[3:-1].split("|")) | set(NEW_TLDS)   # one list for ui.SITE_TLDS to share
NEW_TLD = r"(?:" + "|".join(sorted(NEW_TLDS, key=len, reverse=True)) + ")"
URL = re.compile(rf"\b(?:https?://)?(?:www\.)?[a-z0-9-]+(?:\.[a-z0-9-]+)*\.(?:{TLD}|{NEW_TLD})(?:\.[a-z]{{2}})?(?:/[^\s]*)?(?![\w@])", re.I)
SOCIAL = re.compile(r"(?:linkedin\.com/(?:in|company)/[\w-]+|(?:twitter|x)\.com/\w+|instagram\.com/[\w.]+|facebook\.com/[\w.]+|myspace\.com/[\w.]+|(?:twitter|instagram|ig|x)\s*:\s*@\w+|(?<![\w.])@[A-Za-z_]\w{2,}(?![\w.]*\.[a-z]))", re.I)
WEBMAIL = {"gmail", "hotmail", "yahoo", "outlook", "aol", "icloud", "live", "msn", "comcast", "att", "sbcglobal", "verizon", "terra", "me", "protonmail"}
STATES = {"AL","AK","AZ","AR","CA","CO","CT","DE","FL","GA","HI","ID","IL","IN","IA","KS","KY","LA","ME","MD","MA","MI","MN","MS","MO","MT","NE","NV","NH","NJ","NM","NY","NC","ND","OH","OK","OR","PA","RI","SC","SD","TN","TX","UT","VT","VA","WA","WV","WI","WY","DC"}
STATE_NAMES = r"alabama|alaska|arizona|arkansas|california|colorado|connecticut|delaware|florida|georgia|hawaii|idaho|illinois|indiana|iowa|kansas|kentucky|louisiana|maine|maryland|massachusetts|michigan|minnesota|mississippi|missouri|montana|nebraska|nevada|new hampshire|new jersey|new mexico|new york|north carolina|north dakota|ohio|oklahoma|oregon|pennsylvania|rhode island|south carolina|south dakota|tennessee|texas|utah|vermont|virginia|washington|west virginia|wisconsin|wyoming|calif\.?|tex\.?|fla\.?|penn\.?|mass\.?"
COUNTRIES = r"usa|u\.s\.a\.?|united states|canada|spain|france|germany|deutschland|italy|korea|japan|china|australia|sri lanka|cyprus|sweden|norway|denmark|uk|united kingdom|england|ireland|mexico|brazil|india|vietnam|netherlands|belgium|switzerland|austria"
CITY_ST_ZIP = re.compile(rf"\b[A-Za-z][A-Za-z .'-]+(?:\s+\d{{1,2}})?(?:,\s*(?:{'|'.join(STATES)}|{STATE_NAMES})\.?(?:\s+\d{{5}}(?:-\d{{4}})?)?|\s+(?:{STATE_NAMES})\.?)\b(?!\w)", re.I)
US_ZIP = re.compile(rf"\b(?:{'|'.join(STATES)}|{STATE_NAMES})\.?,?\s+\d{{5}}(?:-\d{{4}})?\b", re.I)
INTL_POST = re.compile(r"(?:^|[\s,])(?:[A-Z]-?)?\d{4,5}\s+[A-Z][\w\u00C0-\u017F-]+|\b[A-Z][a-z]+,?\s+\d{4,5}\b(?!\s*-?\d)")
COUNTRY = re.compile(rf"(?:^|,\s*|\s)(?:{COUNTRIES})\.?$", re.I)
STREET_WORDS = r"st|street|str|strasse|straße|ave|av|avenue|rd|road|blvd|boulevard|dr|drive|ln|lane|way|pkwy|parkway|ct|court|pl|place|hwy|highway|sq|square|plaza|circle|cir|terrace|ter|broadway|trail|tr|pike|row|mawatha|weg|gasse|platz|ring|allee|calle|via|rue|camino|campos"
STREET = re.compile(rf"^\s*(?:no\.?\s*)?\d{{1,6}}[a-z]?(?:-\d+)?,?\s+.*\b(?:{STREET_WORDS})\b\.?|^(?:c/|calle|rue|via|avenida)\b.*\d|^[A-Z][\w\u00C0-\u017F]*(?:{STREET_WORDS})\.?\s+\d+|\b(?:p\.?\s?o\.?\s*box|postfach|box)\s+\d+|^\s*\d{{1,6}}\s+[A-Z][\w.]*(?:\s+[A-Z][\w.]*){{0,3}}\s*(?:,|$)|\b(?:suite|ste\.?|#)\s*\d+", re.I)
# audit 2026-10: a floor/building/unit line between the street and the city stays in the address ("3rd Floor")
UNIT = re.compile(r"^(?:\d{1,3}(?:st|nd|rd|th)\s+(?:floor|fl)\.?|(?:floor|fl|level|unit|apt|room|rm|bldg|building|tower)\.?\s*#?\s*[\w-]{1,5})$", re.I)
LABEL = re.compile(r"^(tel\.?|mailing|mail|postal|visitors?( and deliveries)?|deliver(?:y|ies)|shipping|physical|street|location|headquarters|hq|address|postanschrift|hausanschrift|anschrift|telephones?|phones?|references)\b[\w &]*:?$", re.I)
OTHER_ADDR_LABEL = re.compile(r"visitor|deliver|physical|location|shipping|hausanschrift", re.I)
TITLE_WORDS = r"president|ceo|cfo|coo|cto|cio|cmo|owner|owners|founder|co-founder|director|directeur|directora?|manager|vp|svp|evp|vice|officer|partner|chair|chairman|chairwoman|coordinator|specialist|engineer|consultant|analyst|associate|executive|realtor|attorney|lawyer|counsel|agent|advisor|adviser|sales|marketing|lead|head|principal|supervisor|administrator|representative|secretary|journalist|author|writer|editor|photographer|designer|artist|coach|scout|technologist|developer|programmer|architect|accountant|cpa|broker|producer|professor|dean|instructor|teacher|nurse|physician|doctor|dentist|therapist|pastor|treasurer|member|candidate|senator|congressman|mayor|commissioner|trustee|recruiter|recruitment|admissions|strategist|planner|assistant|intern|clerk|technician|mechanic|chef|baker|stylist|trainer|organizer|ambassador|attaché|attache|manager,|gm|md|principal|superintendent|controller|comptroller|auditor|underwriter|banker|lender|officer|liaison|navigator|curator|librarian|registrar|counselor"
TITLE = re.compile(rf"\b({TITLE_WORDS})\b", re.I)
COMPANY = re.compile(r"\b(inc|incorporated|llc|l\.l\.c|llp|ltd|limited|corp|corporation|co\.|company|group|bank|hospital|university|college|associates|partners|solutions|services|industries|chamber|foundation|clinic|law|consulting|systems|tire|rubber|realty|insurance|construction|labs?|gmbh|ag|s\.a\.|sa|plc|pty|enterprises|entertainment|designs?|studios?|media|trading|computer|computers|games|restaurant|cafe|center|centre|galeria|gallery|embassy|agency|institute|team|club|association|society|council|network|holdings|capital|financial|partners|technologies|technology|tech|electronics|motors|works|werke|aktiengesellschaft|foods|market|press|publishing|records|radio|realty|properties|homes|builders|dental|medical|health|healthcare|pharmacy|church|ministries|school|academy|museum|hotel|inn|resort|salon|spa|fitness|logistics|transport|manufacturing|supply|supplies|wikimedia|wikipedia)\b", re.I)
DEPT = re.compile(r"\b(school of|department|dept\.?|college of|division of|office of|center for|institute (?:of|for)|faculty of)\b|\b\w+ division$|\b\w+ department$", re.I)
DEPT_HEAD = re.compile(r"\b(school|college|department|institute|center|centre|division|faculty)$", re.I)
CRED = r"(?i:MBA|M\.B\.A\.|PhD|Ph\.D\.?|CPA|CFP|Esq\.?|Jr\.?|Sr\.?|III|II|IV|PE|P\.E\.|MD|M\.D\.|RN|SPHR|SHRM-CP|PMP|CFA|JD|J\.D\.|DDS|DO|LCSW|A\.M\.|CFP\S*)"
PTYPES = [("fax", r"\b(f|fax|facsimile|telefax)\b"), ("mobile", r"\b(c|cell|cel[li1]|cellular|m|mob|mobil|mobile|hp|handy|portable)\b"),
          ("home", r"\b(h|home|resid|residence|res)\b"), ("work", r"\b(o|off|office|p|ph|phone|t|tel|telephone|w|work|direct|d|main|toll[- ]?free)\b")]
OLD_EXCH = re.compile(r"(?:\(\d{3}\)\s*)?\b[A-Z][A-Za-z]{1,9}\s?\d-\d{4}\b")
GENERIC_PHONE = re.compile(r"(?<![\w/])\+?\(?\d[\d ()./-]{4,}\d(?![\w])")

PARTICLES = {"van", "de", "von", "der", "den", "da", "di", "la", "le", "du", "del", "della", "dos"}
def surname(s):
    """audit 2026-10: the last word plus the particles before it ('van der Meer', 'de la Cruz'), not just 'Meer'."""
    p = (s or "").split(); k = len(p) - 1
    while k > 0 and p[k-1].lower() in PARTICLES: k -= 1
    return " ".join(p[k:]) if p else ""

def _first_name(tok):
    if not _GD or len(tok) < 2: return False
    return _GD.get_gender(tok.capitalize()) != "unknown"

def _norm_line(l):
    import unicodedata
    l = unicodedata.normalize("NFKC", l)
    if sum(ord(c) < 0x250 for c in l) >= 0.6 * max(len(l), 1): l = "".join(c for c in l if ord(c) < 0x2000)
    l = re.sub(r"\s+", " ", l).strip(" |\u2022\u00b7\u2014*~")
    l = re.sub(r"\b([A-Z])\.(?=[A-Z][a-z])", r"\1. ", l)            # "A.Smith" -> "A. Smith"
    l = re.sub(r"(,\s*)0([A-Z])(?=\s*\d{5})", r"\1O\2", l)           # ",0H44106" -> ",OH44106"
    l = re.sub(r"\b([A-Z]{2})(\d{5})\b", r"\1 \2", l)               # "OH44106" -> "OH 44106"
    l = re.sub(r"^(\d{2,5})[lI](?=\s)", r"\g<1>1", l)                # "291l Cedar" -> "2911 Cedar"
    if "@" not in l and not re.search(r"www|https?:|\.[a-z]{2,3}\b", l):
        l = re.sub(r"^(\d{1,6})(?=[A-Z][a-z])", r"\1 ", l)                          # "5811Jones" -> "5811 Jones"
        l = re.sub(r"(?<=[a-z]{4})(?=[A-Z][a-z]{2,})", " ", l)                       # "CourseAve" -> "Course Ave" (keeps McX/LaX/DeX)
        l = re.sub(r"\b(Division|School|Office|Department|College|Institute|Center|Centre|Faculty)(of|for)\b", r"\1 \2", l)
    l = re.sub(r"(https?)\s*:\s*/\s*/\s*", r"\1://", l, flags=re.I)
    l = re.sub(r"\s*@\s*", "@", l)
    if "@" in l or re.search(r"\bwww\s*\.|https?:|\.\s?(com|org|net|edu)\b", l, re.I):
        l = re.sub(r"(?<=\w)\s*\.\s+(?=\w)|(?<=\w)\s+\.\s*(?=\w)", ".", l)
        l = re.sub(r"\b(e-?mail|email|web|www)\s*:\s*", lambda m: m.group(0).strip() + " ", l, flags=re.I)
    return l

ACRONYMS = {"CEO", "CFO", "COO", "CTO", "CIO", "CMO", "CRO", "CPO", "CISO", "SVP", "EVP", "AVP", "VP", "HR", "IT", "PR", "LLC", "LLP",
            "PLLC", "PC", "USA", "CPA", "MBA", "CFP", "RN", "MD", "DDS", "ESQ", "PE", "AIA", "UPS", "IBM", "GAC", "NASA", "OSU", "UA"}
def _tc(s):
    # round 22 (reviewer r21): job-title acronyms such as CFO stay in capitals ('Cfo' was a misread look)
    return " ".join(w if re.sub(r"[^A-Z]", "", w) in ACRONYMS and w.isupper() else w.capitalize() if (w.isupper() and len(w) > 2 and not re.search(r"\d", w)) or (w.isupper() and len(w) <= 2 and w.isalpha() and False) else w for w in s.split()) if s.isupper() else s

def _strip_label(l):
    return re.sub(r"^(?:e-?mail|email|web|website|url|www:)\s*:?\s*", "", l, flags=re.I)

def _phones(lines, used):
    out, seen = [], set()
    def add(i, num, start, end, ln):
        d = re.sub(r"\D", "", num)
        if len(d) < 5 or d in seen or any(d in s or s in d for s in seen if len(s) >= 7 and len(d) >= 7): return
        if re.fullmatch(r"(19|20)\d{2}", d) or re.fullmatch(r"\d{5}-\d{4}", num.strip()): return
        seen.add(d)
        prefix = ln[:start].lower()
        pre_lab = re.findall(r"[a-z/.-]+(?=\s*[:.]?\s*$)", prefix[-14:])
        t = None
        lab = prefix[-14:]
        cut = max(lab.rfind(c) for c in "0123456789") + 1
        lab = lab[cut:]
        # audit 2026-10: 'P 330… / F 330…' - after an earlier number the label is the text after the '/', not before it ('P/F' alone keeps the first)
        lab = (lab.rsplit("/", 1)[1] if cut and re.search(r"[a-z]", lab.rsplit("/", 1)[1]) else lab.split("/")[0]) if "/" in lab else lab
        for k, p in PTYPES:
            if re.search(p, lab): t = k; break
        if t is None:
            suf = ln[end:end+12].lower()
            for k, p in PTYPES:
                if re.search(p, suf): t = k; break
        out.append({"type": t or "work", "number": num.strip(), "valid": len(d) >= 10}); used.add(i)
    for i, ln in enumerate(lines):
        # property tests 2026-10: 'jsmith@acme.com  T: 330-555-0101' on one line lost the phone (the whole line was skipped).
        # The email / @handle is blanked out instead (same length, so spans and labels still line up) and the rest is read.
        if "@" in ln: ln = re.sub(r"\S*@\S*", lambda m: " " * len(m.group(0)), ln)
        is_addr = bool(STREET.search(ln) or US_ZIP.search(ln)) and not re.search(r"\b(tel|phone|fax|mobil|cell)", ln, re.I)
        spans = []
        for m in phonenumbers.PhoneNumberMatcher(ln, "US", leniency=phonenumbers.Leniency.POSSIBLE):
            if is_addr and US_ZIP.search(ln) and re.sub(r"\D","",m.raw_string) in re.sub(r"\D","",US_ZIP.search(ln).group(0)): continue
            g = next((x for x in GENERIC_PHONE.finditer(ln) if x.start() <= m.start and x.end() >= m.end and len(re.sub(r"\D","",x.group(0))) - len(re.sub(r"\D","",m.raw_string)) >= 3), None)
            if g: spans.append((g.start(), g.end())); add(i, g.group(0), g.start(), g.end(), ln); continue
            spans.append((m.start, m.end)); add(i, m.raw_string, m.start, m.end, ln)
        for m in OLD_EXCH.finditer(ln):
            if not any(a <= m.start() < b for a, b in spans) and not STREET.search(ln[m.start():m.end()]):
                if re.search(r"\b(?:ave|st|street|rd)\b", m.group(0), re.I): continue
                spans.append((m.start(), m.end())); add(i, m.group(0), m.start(), m.end(), ln)
        labeled = re.search(r"\b(tel|phone|fax|mobil\w*|cell\w*|office|resid\w*|hp|t|f|m|p|o|c)\b\s*[:.]?", ln, re.I)
        for m in GENERIC_PHONE.finditer(ln):
            if any(a <= m.start() < b or a < m.end() <= b for a, b in spans): continue
            d = re.sub(r"\D", "", m.group(0))
            if is_addr and not labeled: continue
            if len(d) >= 8 or (labeled and len(d) >= 5):
                spans.append((m.start(), m.end())); add(i, m.group(0), m.start(), m.end(), ln)
    return out

def _wordlike(s):
    return all(len(t) >= 3 and re.search(r"[aeiouy]", t, re.I) for t in re.findall(r"[A-Za-z]+", s))

def parse(text: str, meta=None) -> dict:
    raw = [_norm_line(l) for l in text.splitlines()]
    mtop = {_norm_line(m["text"]): m for m in (meta or [])}
    lines, block, info, b = [], [], [], 0
    for l in raw:
        if len(l) <= 1: b += 1; continue
        m = mtop.get(l, {})
        if m.get("top", 1) < 0.25 and not re.search(r"[\d@]", l) and l.isupper():
            l = " ".join(t for t in l.split() if re.fullmatch(r"[A-Z][A-Z&.'-]*,?|&", t) and not re.fullmatch(r"EST\.?", t)) or l
        # join wrapped emails ("JDoe@" / "ExampleFinancial.com", "name" / "@domain")
        if lines and (lines[-1].endswith("@") and re.match(r"[\w-]+\.", l) or (re.match(r"@[\w-]+\.[a-z]{2,}", l) and "@" not in lines[-1] and re.search(r"[\w.]$", lines[-1]))):
            lines[-1] = re.sub(r"\s*(\S+)$", lambda mm: " " + mm.group(1) + l, lines[-1]).strip(); continue
        lines.append(l); block.append(b); info.append(m)
    n = len(lines); used, conf = set(), {}
    f = {"first_name": "", "last_name": "", "credentials": "", "title": "", "company": "", "department": "", "emails": [], "phones": [],
         "website": "", "address": "", "other_address": "", "social": []}
    hdr = lambda i: info[i].get("top", 1) < 0.25
    relh = lambda i: info[i].get("rel_h", 1.0)
    # emails / socials / website
    for i, l in enumerate(lines):
        for e in EMAIL.findall(l):
            f["emails"].append(clean_email(e.lower().strip("."))); used.add(i)
    for i, l in enumerate(lines):
        for s_ in SOCIAL.findall(l):
            if "@" in s_ and EMAIL.search(l) and not re.search(r":\s*@", l): continue
            f["social"].append(s_.strip()); used.add(i)
    for i, l in enumerate(lines):
        lc = SOCIAL.sub("", EMAIL.sub("", l))
        m = URL.search(lc)
        host = re.sub(r"^https?://", "", m.group(0), flags=re.I).split("/")[0] if m else ""
        if m and host.rsplit(".", 1)[-1].lower() in NEW_TLDS and not re.match(r"(https?://|www\.)", m.group(0), re.I) \
                and not (host.rsplit(".", 1)[-1].islower() or host.isupper()): continue   # audit 2026-10: 'No.Kidding'-style words are not sites
        if m and not f["website"] and (re.match(r"(https?://|www\.)", m.group(0), re.I) or re.search(r"\.(com|org|net|edu|gov|io|co|us|biz|info)\b", m.group(0), re.I) or len(m.group(0).split(".")[0]) >= 4):
            f["website"] = re.sub(r"/$", "", m.group(0).lower()); used.add(i)
    conf["emails"] = 0.95 if f["emails"] else 0
    conf["website"] = 0.85 if f["website"] else 0
    f["phones"] = _phones(lines, used)
    conf["phones"] = 0.9 if f["phones"] and all(p["valid"] for p in f["phones"]) else (0.5 if f["phones"] else 0)
    # labels
    other_after = set()
    for i, l in enumerate(lines):
        if LABEL.match(l) and not re.search(r"\d", l) and len(l.split()) <= 4:
            used.add(i)
            if OTHER_ADDR_LABEL.search(l): other_after.add(i)
    # address blocks
    def addr_kind(i):
        l = lines[i]
        if re.search(r"@", l): return 0
        if US_ZIP.search(l) or CITY_ST_ZIP.fullmatch(l.strip(" ,.")) : return 2
        if INTL_POST.search(l) and not re.search(r"\b(tel|fax|phone)\b", l, re.I) and sum(c.isdigit() for c in l) <= 7: return 2
        if COUNTRY.search(l) and len(l.split()) <= 6: return 2
        if STREET.search(l): return 1
        return 0
    kinds = [addr_kind(i) if i not in used or i in [j for j in range(n) if f["phones"] and False] else 0 for i in range(n)]
    for i in range(n):  # lines used only for a phone may still hold an address ("100 Main St. Akron, OH 44308 330/555-0100")
        if kinds[i] == 0 and i in used and "@" not in lines[i] and (US_ZIP.search(lines[i]) or STREET.search(lines[i])) and not LABEL.match(lines[i]):
            kinds[i] = addr_kind(i)
    def clean_addr(l):
        for p in f["phones"]:
            if p["number"] in l: l = l[:l.index(p["number"])]
        l = re.sub(r"\b(tel|phone|fax)\b.*$", "", l, flags=re.I)
        l = re.sub(r"\b((?i:st|street|rd|road|blvd|dr|drive|ln|lane|way|pkwy|ct|pl|hwy)\.?)\s+[TFMPCO]\.?$", r"\1", l)   # audit 2026-10: '50 S Main St T' (label leak)
        z = US_ZIP.search(l)
        if z: l = l[:z.end()] + re.sub(r"^\s*(usa|u\.s\.a\.?)?.*$", lambda m: (" " + m.group(1)) if m.group(1) else "", l[z.end():])
        return l.strip(" ,;")
    for i in range(1, n - 1):
        if not kinds[i] and kinds[i-1] and kinds[i+1] and i not in used and (not re.search(r"[\d@]", lines[i]) or UNIT.match(lines[i])) and len(lines[i].split()) <= 4 \
                and block[i-1] == block[i] == block[i+1]: kinds[i] = 1
    blocks, cur = [], []
    for i in range(n):
        if kinds[i]:
            if cur and (block[i] != block[cur[-1]] and i - cur[-1] > 1 or i - cur[-1] > 2): blocks.append(cur); cur = []
            cur.append(i)
        elif cur and (not (i in used and LABEL.match(lines[i])) or i in other_after): blocks.append(cur); cur = []
    if cur: blocks.append(cur)
    blocks = [bl for bl in blocks if any(kinds[i] == 2 for i in bl) or any(STREET.search(lines[i]) and re.search(r"\d", lines[i]) for i in bl)]
    if other_after:
        oa = min(other_after)
        later = [bl for bl in blocks if bl[0] > oa]
        if later: f["other_address"] = ", ".join(clean_addr(lines[i]) for i in later[0]); used |= set(later[0]); blocks = [bl for bl in blocks if bl is not later[0]]
        else:
            j = oa + 1; parts = []
            while j < n and j not in used and len(parts) < 2 and not LABEL.match(lines[j]): parts.append(lines[j]); used.add(j); j += 1
            f["other_address"] = ", ".join(parts)
    if blocks:
        best = max(blocks, key=lambda bl: (sum(kinds[i] for i in bl) + (3 if any(US_ZIP.search(lines[i]) for i in bl) else 0), -bl[0]))
        # a street line directly before the block in the same column joins it
        order = sorted(best, key=lambda i: (0 if (STREET.search(lines[i]) and not US_ZIP.search(lines[i])) else 1, i)) if any(US_ZIP.search(lines[i]) or CITY_ST_ZIP.search(lines[i]) for i in best) else best
        f["address"] = ", ".join(dict.fromkeys(clean_addr(lines[i]) for i in order if clean_addr(lines[i])))
        used |= set(best)
    conf["address"] = 0.85 if US_ZIP.search(f["address"]) else (0.5 if f["address"] else 0)
    # department
    for i, l in enumerate(lines):
        if i in used: continue
        cand, span = l, [i]
        if DEPT_HEAD.search(l) and i + 1 < n and lines[i+1].lower().startswith(("of ", "for ")) and i + 1 not in used:
            cand, span = f"{l} {lines[i+1]}", [i, i+1]
        if DEPT.search(cand) and len(cand.split()) <= 8 and not re.search(r"\d", cand):
            f["department"] = cand; used |= set(span); break
    conf["department"] = 0.7 if f["department"] else 0
    # ---- name
    local = re.sub(r"[^a-z]", "", f["emails"][0].split("@")[0].lower()) if f["emails"] else ""
    locals_ = [re.sub(r"[^a-z]", "", e.split("@")[0]) for e in f["emails"]]
    def name_tokens(l):
        l = re.sub(rf",?\s*\b(?:{CRED})(?=\W|$)\.?\S*", "", l)
        l = re.sub(r"^(mr|mrs|ms|dr|prof|brig\.? gen|gen|col|capt|hon|rev)\.?\s+", "", l, flags=re.I)
        l = re.split(r"\s*&\s*|\s+and\s+", l)[0]
        l = re.sub(r"[^\w.'\s-]+\S*$", "", l).strip()
        l = re.sub(r"\b(Mc|Mac|O'|De|Van|Von)\s+(?=[A-Z])", r"\1", l)
        return [w for w in l.replace(",", " ").split() if w]
    def name_parts(l):
        """audit 2026-10: 'John Smith, CEO' -> name + inline title; 'Smith, John' -> 'John Smith'; 'John & Jane Smith' -> two people."""
        s = re.sub(rf",?\s*\b(?:{CRED})(?=\W|$)\.?\S*", "", l).strip(" ,")
        if s.count(",") == 1:
            a, b = [x.strip() for x in s.split(",")]
            if a and b and TITLE.search(b) and not TITLE.search(a) and not COMPANY.search(l) and len(b.split()) <= 6: return a, b, False
            if a and b and not TITLE.search(s) and not COMPANY.search(s) and re.fullmatch(r"(?:[a-z]+\s+)*[A-Z][\w'-]+", a) and \
                    re.fullmatch(r"[A-Z][\w'-]+(?:\s+[A-Z][\w.'-]*)?", b) and _first_name(b.split()[0]) and not _first_name(a.split()[-1]): return f"{b} {a}", "", False
        pp = [x.split() for x in re.split(r"\s*&\s*|\s+and\s+", s)]
        if len(pp) == 2 and all(pp) and all(_first_name(x[0]) and x[0][:1].isupper() for x in pp) and not COMPANY.search(s) and not TITLE.search(s):
            return " ".join(pp[0] + (pp[1][1:] if len(pp[0]) == 1 else [])), "", True
        return l, "", False
    cands, inline_t, multi, name_title = [], {}, set(), ""
    CREDS_RE = re.compile(r"(?<![A-Za-z])(MBA|M\.B\.A\.|Ph\.?D\.?|CPA|CFP|CFA|Esq\.?|PMP|SPHR|SHRM-CP|P\.?E\.|M\.?D\.|RN|JD|J\.D\.|DDS|LCSW|A\.M\.|Jr\.?|Sr\.?|III|II)(?![A-Za-z])", re.I)
    for i, l in enumerate(lines):
        if i in used or re.search(r"\d|@|/", l): continue
        core, it_, mu = name_parts(l)
        w = name_tokens(core)
        if it_: inline_t[i] = it_
        if mu: multi.add(i)
        single_join = False
        if len(w) == 1 and i + 1 < n and i + 1 not in used and _first_name(w[0]):
            w2 = name_tokens(lines[i+1])
            if 1 <= len(w2) <= 2 and all(x[:1].isupper() for x in w2) and not TITLE.search(lines[i+1]) and not COMPANY.search(lines[i+1]): w = w + w2; single_join = True
        # round 22 (datamanager r21): 'Elena lbarra' is Elena Ibarra (l/I misread): fill it, with a low confidence so it is flagged
        if len(w) >= 2 and w[0][:1].isupper(): w = [("I" + x[1:]) if k > 0 and re.fullmatch(r"l[a-z]{3,}", x) else x for k, x in enumerate(w)]
        prt = [0 < k < len(w) - 1 and x in PARTICLES for k, x in enumerate(w)]   # audit 2026-10: 'de la Cruz' no longer drops the name
        if not (2 <= len(w) - sum(prt) <= 4) or not all(re.fullmatch(r"[A-Za-z\u00C0-\u017F][\w\u00C0-\u017F'.-]*", x) for x in w): continue
        if any(len(x) == 1 for x in (w[0], w[-1])): continue
        s_ = 0.0
        emailhit = any(len(x) >= 3 and x.lower().strip(".") in lc for lc in locals_ for x in (w[0], w[-1]))
        if not emailhit and not all(x[0].isupper() or p_ for x, p_ in zip(w, prt, strict=True)): continue
        if emailhit: s_ += 3
        if _first_name(w[0].strip(".")): s_ += 2.5
        elif _first_name(w[-1]): s_ += 0.5
        if COMPANY.search(l): s_ -= 4
        if TITLE.search(re.sub(rf",?\s*\b(?:{CRED})(?=\W|$)\.?\S*", "", core)): s_ -= 3
        if DEPT.search(l) or LABEL.match(l): s_ -= 4
        if re.search(rf"\b({STATE_NAMES}|{COUNTRIES})\b", l, re.I): s_ -= 2
        if hdr(i) and not _first_name(w[0]): s_ -= 1
        if l.isupper() and not _first_name(w[0]): s_ -= 0.5 + 0.5 * (len(w) >= 4)
        s_ += min(max(relh(i) - 1, 0), 1.0)
        s_ -= 0.05 * i
        cands.append((s_ + (0.001 if emailhit or _first_name(w[0].strip(".")) else 0), i, w, single_join))
    if cands:
        s_, bi, best, sj = max(cands)
        if s_ > -1:
            fix = lambda x: _tc(x[:1].upper() + x[1:]) if x.isupper() or x[:1].islower() else x
            sur = surname(" ".join(best[1:])).split()
            f["first_name"], f["last_name"] = fix(best[0]), " ".join([x.lower() for x in sur[:-1]] + [fix(sur[-1].strip("."))])
            tail = lines[bi].split(",", 1)[1] if "," in lines[bi] else lines[bi]
            cr = [m.group(1) for m in CREDS_RE.finditer(tail) if not re.search(re.escape(m.group(1)), " ".join(best))]
            if cr: f["credentials"] = ", ".join(dict.fromkeys(c.upper() if len(c) <= 4 and "." not in c and c.lower() not in ("esq", "jr", "sr") else c for c in cr))
            name_line = lines[bi]
            used.add(bi)
            if sj: used.add(bi + 1)
            strong = s_ >= 2 and (_first_name(best[0].strip(".")) or any(len(x) >= 3 and x.lower().strip(".") in lc for lc in locals_ for x in (best[0], best[-1])))
            conf["name"] = 0.9 if strong else 0.6
            if f["last_name"][:1] == "I" and re.search(r"\bl" + re.escape(f["last_name"][1:]), name_line): conf["name"] = 0.5   # l/I fixed: flag it
            if bi in multi: conf["name"] = min(conf["name"], 0.5)   # audit 2026-10: two people on one card ('John & Jane Smith'): flag it
            name_i = bi + (1 if sj else 0); name_title = inline_t.get(bi, "")
        else: name_i = None; conf["name"] = 0
    else: name_i = None; conf["name"] = 0
    # ---- title: lexicon line near the name, else the line right after the name
    def title_ok(j, strict):
        if j < 0 or j >= n or j in used: return False
        l = lines[j]
        if re.search(r"[\d@]", l) or len(l.split()) > 9 or LABEL.match(l): return False
        if COMPANY.search(l) and not TITLE.search(l): return False
        return bool(TITLE.search(l)) or not strict
    ti = None
    if name_i is not None and name_title: f["title"] = _tc(name_title)   # audit 2026-10: 'John Smith, CEO'
    elif name_i is not None:
        for j in (name_i + 1, name_i - 1, name_i + 2):
            if title_ok(j, True) and (j == name_i + 1 or block[j] == block[name_i]): ti = j; break
        if ti is None and title_ok(name_i + 1, False) and block[name_i + 1] == block[name_i] and not hdr(name_i + 1) \
                and not COMPANY.search(lines[name_i + 1]) and not (relh(name_i + 1) > 1.3): ti = name_i + 1
    if ti is None and not f["title"]:
        for j in range(n):
            if title_ok(j, True) and not hdr(j) and len(lines[j].split()) <= 7: ti = j; break
    if ti is not None:
        f["title"] = lines[ti]; used.add(ti)
        j = ti + 1
        while j < n and j not in used and block[j] == block[ti] and len(lines[j].split()) <= 6 \
                and not re.search(r"[\d@]", lines[j]) and (not COMPANY.search(lines[j]) or lines[j].startswith("(")) and not DEPT.search(lines[j]) \
                and not LABEL.match(lines[j]) and (lines[j][:1].isupper() or lines[j].startswith("(")) and j - ti <= 2 and ":" not in lines[j] and "!" not in lines[j] and relh(j) <= 1.3 * relh(ti) and (TITLE.search(lines[j]) or lines[j].istitle() or lines[j].isupper() or lines[j].startswith("(")):
            f["title"] += ("" if lines[j].startswith("(") else ",") + " " + lines[j]; used.add(j); j += 1
        f["title"] = _tc(f["title"]).replace(" ,", ",")
        f["title"] = re.sub(r"\s*\((.*)\)", r" (\1)", f["title"]).strip()
    conf["title"] = 0.75 if f["title"] and TITLE.search(f["title"]) else (0.5 if f["title"] else 0)
    # ---- company: score candidates
    doms = []
    for src in ([f["website"]] if f["website"] else []) + f["emails"]:
        d = re.sub(r"^(https?://)?(www\.)?", "", src.split("@")[-1]).split("/")[0].split(".")[0].lower()
        if d and d not in WEBMAIL: doms.append(d)
    best, bs = None, 0.5
    for i in range(n):
        if i in used: continue
        l = lines[i]
        if re.search(r"@|^\+?\d|^\(", l) or len(l.split()) > 8: continue
        s_ = 0.0
        key = re.sub(r"[^a-z]", "", l.lower())
        for d in doms:
            r = SequenceMatcher(None, key, d).ratio()
            if d in key or key in d and len(key) >= 3: r = max(r, 0.9)
            s_ = max(s_, 4 * r if r > 0.5 else 0)
        if COMPANY.search(l): s_ += 2.5
        if hdr(i): s_ += 1.2
        s_ += min(relh(i), 3) - 1
        if TITLE.search(l) and not COMPANY.search(l): s_ -= 2
        if len(l.split()) > 5: s_ -= 1
        if re.search(r"^(your|the world|where|open|specializing|just|with|make)\b", l, re.I): s_ -= 2
        if s_ > bs: best, bs = i, s_
    if best is not None:
        grp = [best]
        def joinable(j):
            return 0 <= j < n and j not in used and not re.search(r"[\d@]", lines[j]) and len(lines[j].split()) <= 3 \
                and abs(relh(j) - relh(best)) < 0.35 * max(relh(best), 1) and (block[j] == block[best] or hdr(j) == hdr(best)) \
                and not TITLE.search(lines[j]) and lines[j].isupper() == lines[best].isupper()
        def kwjoin(j):
            return 0 <= j < n and j not in used and not re.search(r"[\d@]", lines[j]) and len(lines[j].split()) <= 2 and len(lines[best].split()) <= 3 \
                and abs(j - best) == 1 and (COMPANY.search(lines[j]) or lines[j].isupper() and lines[best].isupper() and (hdr(j) or hdr(best))) and not TITLE.search(lines[j])
        if kwjoin(best + 1) and not COMPANY.search(lines[best]): grp.append(best + 1)
        elif kwjoin(best - 1) and COMPANY.search(lines[best]) and len(lines[best].split()) <= 2: grp.insert(0, best - 1)
        while joinable(grp[0] - 1) and len(grp) < 3 and (COMPANY.search(lines[best]) or lines[best].isupper()): grp.insert(0, grp[0] - 1)
        while joinable(grp[-1] + 1) and len(grp) < 3 and (COMPANY.search(lines[grp[-1]+1]) or (lines[best].isupper() and len(lines[best].split()) == 1)): grp.append(grp[-1] + 1)
        f["company"] = _tc(" ".join(lines[i] for i in grp)); used |= set(grp)
    conf["company"] = min(0.9, round(0.3 + bs / 8, 2)) if f["company"] else 0
    # repair emails whose '@' was misread, using the website's domain as evidence ("marvin.maymardesowin.co" + www.sonwin.com)
    wdom = re.sub(r"^(https?://)?(www\.)?", "", f["website"].lower()).split("/")[0]
    if not f["emails"] and wdom and "." in wdom:
        for i, l in enumerate(lines):
            t = re.sub(r"\s+", "", l.lower())
            if "@" in t or t.replace("www.", "") == wdom or not re.fullmatch(r"[a-z0-9._+-]{6,}", t) or t.startswith("www"): continue
            if " " in l and t == re.sub(r"[^a-z]", "", (f["first_name"] + f["last_name"]).lower()): continue   # audit 2026-10: the name line ('Ray Builds' + raybuilds.tech) is not an email
            base = wdom.split(".")[0]
            for k in range(2, len(t) - 3):
                tail = t[k+1:]
                if SequenceMatcher(None, tail, wdom).ratio() >= 0.72 or SequenceMatcher(None, tail.split(".")[0], base).ratio() >= 0.8 and len(tail.split(".")[0]) >= 3:
                    local = t[:k].strip(".")
                    if len(local) >= 2: f["emails"] = [local + "@" + wdom]; conf["emails"] = 0.5; used.add(i)
                    break
            if f["emails"]: break
    # cross-correct name OCR with the email local part (e.g. "Rown" + cbrown@ -> "Brown")
    if f["emails"] and f["last_name"]:
        lp = re.sub(r"[^a-z]", "", f["emails"][0].split("@")[0])
        for key in ("last_name", "first_name"):
            nm = f[key].lower()
            if len(nm) < 3 or nm in lp or " " in nm: continue
            for L in (len(nm), len(nm) + 1, len(nm) - 1):
                hit = max(((SequenceMatcher(None, nm, lp[j:j+L]).ratio(), lp[j:j+L]) for j in range(0, max(1, len(lp) - L + 1))), default=(0, ""))
                if hit[0] >= 0.75 and len(hit[1]) >= 3 and (lp.startswith(hit[1]) or lp.endswith(hit[1]) or lp[1:].startswith(hit[1])):
                    f[key] = hit[1].capitalize() if not f[key][1:].islower() or True else f[key]; break
    # repair OCR'd emails whose '@' was read as a letter ("mvillaabenson.com"), using known name/domain evidence
    if not f["emails"]:
        known = [x.lower() for x in (f["first_name"], f["last_name"]) if len(x) >= 3]
        for l in lines:
            for tok in re.findall(r"[\w.+-]{4,}\.(?:com|net|org|co|edu|gov|io|us|biz|info)\b", l, re.I):
                t = tok.lower()
                if t.startswith("www."): continue
                for k in range(1, len(t) - 4):
                    if t[k] in "a@©®&" and any(nm in t[:k] or t[:k] in (nm[0] + f["last_name"].lower(), ) for nm in known) and "." in t[k+1:]:
                        f["emails"] = [t[:k] + "@" + t[k+1:]]; conf["emails"] = 0.5
                        if f["website"].lower().replace("www.", "") == t: f["website"] = ""
                        break
                if f["emails"]: break
            if f["emails"]: break
    # ---- confidence calibration (QA P1/P2/P5): absent fields -> None; penalize suspicious values
    def junk_tokens(s):
        return [t for t in re.findall(r"[A-Za-z]+", s) if (len(t) <= 2 and t.lower() not in ("of", "&", "co", "at", "de", "la", "le", "y", "e", "and", "in", "on", "ag", "sa", "st", "us", "uk", "ny", "nj", "oh") and not t.isupper()) or (t.islower() and len(t) <= 4 and t not in ("and", "the", "for", "of", "at"))]
    if f["first_name"]:
        nm = f"{f['first_name']} {f['last_name']}".lower()
        if f["company"] and (f["first_name"].lower() in f["company"].lower() or f["last_name"].lower() in f["company"].lower()) and not conf.get("name", 0) >= 0.9:
            conf["name"] = min(conf.get("name", 0.6), 0.4)
        if not _first_name(f["first_name"]) and not any(len(x) >= 3 and x in lp for lp in locals_ for x in nm.split()):
            conf["name"] = min(conf.get("name", 0.6), 0.45)
    if f["company"]:
        if junk_tokens(f["company"]): conf["company"] = min(conf["company"], 0.35)
        if not COMPANY.search(f["company"]) and not any(SequenceMatcher(None, re.sub(r"[^a-z]", "", f["company"].lower()), d).ratio() > 0.6 for d in doms):
            conf["company"] = min(conf["company"], 0.55)
        # a logo line next to an unused all-caps fragment suggests a truncated multi-line logo
        if any(i not in used and lines[i].isupper() and len(lines[i].split()) <= 2 and hdr(i) and not re.search(r"\d", lines[i])
               and not all(w.lower() in f["company"].lower() for w in lines[i].split()) and _wordlike(lines[i]) for i in range(n)):
            conf["company"] = min(conf["company"], 0.5)
    if f["title"] and junk_tokens(f["title"]): conf["title"] = min(conf.get("title", 0.5), 0.4)
    if f["address"] and junk_tokens(f["address"].split(",")[0]): conf["address"] = min(conf["address"], 0.5)
    present = {"name": bool(f["first_name"]), "title": bool(f["title"]), "company": bool(f["company"]), "department": bool(f["department"]),
               "emails": bool(f["emails"]), "phones": bool(f["phones"]), "website": bool(f["website"]), "address": bool(f["address"])}
    for k, v in present.items():
        if not v: conf[k] = None
    vals = [v for v in conf.values() if v is not None]
    f["confidence"] = conf
    f["overall_confidence"] = round(min(sum(vals) / len(vals), min(vals) + 0.25), 2) if vals else 0.0
    if not f["first_name"]: f["overall_confidence"] = min(f["overall_confidence"], 0.5)   # part-timer r1: 90 % with no name
    f["needs_review"] = [k for k, v in conf.items() if v is not None and v < 0.6] + ([] if f["first_name"] else ["name"])
    _postprocess(f)
    return f

def _postprocess(f):
    """Spacing around '&' glued by OCR ('Hughes& Partners Law' -> 'Hughes & Partners Law'); 'AT&T', 'R&D' stay as they are."""
    for k in ("company", "title", "department", "address"):
        v = f.get(k)
        if isinstance(v, str) and "&" in v:
            v = re.sub(r"(?<=[a-z])&(?=\s)", " &", v)          # 'Hughes& Partners'
            v = re.sub(r"(?<=\s)&(?=[A-Za-z]{2})", "& ", v)     # 'Hughes &Partners'
            f[k] = re.sub(r"\s{2,}", " ", v)

def _unused_old_calibration(f, conf):
    f["confidence"] = conf
    f["overall_confidence"] = round(sum(conf.values()) / len(conf), 2)
    return f

def from_vlm(d: dict) -> dict:
    f = {k: d.get(k) or ("" if k not in ("emails", "phones", "social") else []) for k in
         ["first_name", "last_name", "title", "company", "department", "emails", "phones", "website", "address", "other_address", "social"]}
    if isinstance(f["emails"], str): f["emails"] = [f["emails"]]
    f["phones"] = [p if isinstance(p, dict) else {"type": "work", "number": str(p)} for p in f["phones"]]
    f["confidence"] = {k: 0.7 for k in ["name", "title", "company", "emails", "phones", "website", "address"]}
    f["overall_confidence"] = 0.7
    return f
