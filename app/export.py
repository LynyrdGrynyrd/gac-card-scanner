import csv, io
def _ph(n):   # round 15: one phone form in every export: "330-555-0170 x4271" (extension kept in the same cell)
    from . import mctrade_export as _mx
    return _mx.phone(n)
def _csvph(n):
    """Round 16 (skeptic r15 L1): an international number written as '+442079460958' turns into 4.42E+11 in Excel (the '+'
    is lost). In the CSV it is written in the international spaced form '+44 20 7946 0958', which Excel keeps as text,
    like the US '330-555-0170' form. US/GAC-style numbers are unchanged."""
    import re
    v = _ph(n)
    if not re.fullmatch(r"\+\d{7,15}", v or ""): return v
    try:
        import phonenumbers as pn
        return pn.format_number(pn.parse(v, None), pn.PhoneNumberFormat.INTERNATIONAL)
    except Exception:
        return v[:3] + " " + v[3:]
COLS = ["id","status","first_name","last_name","title","company","email","email2","work_phone","mobile_phone","fax",
        "website","address","social","overall_confidence"]
def _flat(c):
    f = c["fields"]; ph = {p["type"]: _csvph(p["number"]) for p in reversed(f.get("phones", []))}
    em = f.get("emails", []) + ["", ""]
    return {"id": c["id"], "status": c["status"], "first_name": f["first_name"], "last_name": f["last_name"],
            "title": f["title"], "company": f["company"], "email": em[0], "email2": em[1],
            "work_phone": ph.get("work",""), "mobile_phone": ph.get("mobile",""), "fax": ph.get("fax",""),
            "website": f["website"], "address": f["address"], "social": " ".join(f.get("social", [])),
            "overall_confidence": f.get("overall_confidence","")}
def to_csv(cards):
    b = io.StringIO(); w = csv.DictWriter(b, COLS); w.writeheader()
    for c in cards: w.writerow(_flat(c))
    return b.getvalue()
def _e(s): return (s or "").replace("\\","\\\\").replace(",","\\,").replace(";","\\;").replace("\n","\\n")
def to_vcard(cards):
    out = []
    for c in cards:
        f = c["fields"]
        v = ["BEGIN:VCARD","VERSION:3.0",f"N:{_e(f['last_name'])};{_e(f['first_name'])};;;",
             f"FN:{_e((f['first_name']+' '+f['last_name']).strip() or f['company'])}"]
        if f["company"]: v.append(f"ORG:{_e(f['company'])}")
        if f["title"]: v.append(f"TITLE:{_e(f['title'])}")
        v += [f"EMAIL;TYPE=INTERNET:{e}" for e in f["emails"]]
        tm = {"work":"WORK,VOICE","mobile":"CELL","fax":"WORK,FAX"}
        v += [f"TEL;TYPE={tm.get(p['type'],'VOICE')}:{p['number']}" for p in f["phones"]]
        if f["website"]: v.append(f"URL:{f['website']}")
        if f["address"]: v.append(f"ADR;TYPE=WORK:;;{_e(f['address'])};;;;")
        v += [f"X-SOCIALPROFILE:{s}" for s in f.get("social", [])]
        v += [f"NOTE:GAC card scan #{c['id']} ({c['status']})", "END:VCARD"]
        out.append("\r\n".join(v))
    return "\r\n".join(out) + "\r\n"
