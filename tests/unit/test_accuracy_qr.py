"""Audit 2026-10: QR vCard parsing (values get 0.99 confidence and skip the AI check, so they have to be right)."""
from app import qr


def _v(*lines, nl="\r\n"): return qr.parse_vcard(nl.join(("BEGIN:VCARD", "VERSION:3.0") + lines + ("END:VCARD",)))


def test_unescapes_commas_semicolons_and_backslashes():
    f = _v("N:Smith;John;;;", "ORG:Smith\\, Jones & Co\\;Legal;Litigation", "TITLE:Partner\\, Trial Group", "NOTE:x\\\\y")
    assert (f["first_name"], f["last_name"]) == ("John", "Smith")
    assert f["company"] == "Smith, Jones & Co;Legal" and f["department"] == "Litigation"
    assert f["title"] == "Partner, Trial Group"


def test_adr_components_by_position_us():
    f = _v("N:Smith;John", "ADR;TYPE=WORK:;;200 S Main St;Akron;OH;44308;USA")
    assert f["address"] == "200 S Main St, Akron, OH 44308"


def test_adr_po_box_and_extended():
    f = _v("N:Smith;John", "ADR:PO Box 12;Suite 400;200 S Main St;Akron;OH;44308;United States")
    assert f["address"] == "200 S Main St, Suite 400, PO Box 12, Akron, OH 44308"


def test_adr_non_us_keeps_country_and_escaped_newline():
    f = _v("N:Weber;Anna", "ADR:;;Hauptstr. 5\\nHinterhaus;Berlin;;10115;Germany")
    assert f["address"] == "Hauptstr. 5, Hinterhaus, Berlin, 10115, Germany"


def test_folded_lines_are_joined():
    f = _v("N:Smith;John", "ADR;TYPE=WORK:;;200 S Main St;Akr", " on;OH;44308;USA", "EMAIL:john.smith@acme", "\texample.com")
    assert f["address"] == "200 S Main St, Akron, OH 44308"
    assert f["emails"] == ["john.smith@acmeexample.com"]
    f = _v("N:Smith;John", "TITLE:Vice", "  President", nl="\n")
    assert f["title"] == "Vice President"


def test_quoted_printable_and_charset():
    f = _v("N;CHARSET=UTF-8;ENCODING=QUOTED-PRINTABLE:M=C3=BCller;J=C3=BCrgen", "ORG;CHARSET=UTF-8;ENCODING=QUOTED-PRINTABLE:B=C3=A4ckerei =",
           "M=C3=BCller GmbH")
    assert (f["first_name"], f["last_name"]) == ("Jürgen", "Müller")
    assert f["company"] == "Bäckerei Müller GmbH"
    f = _v("N;CHARSET=ISO-8859-1;ENCODING=QUOTED-PRINTABLE:M=FCller;Anna", "TITLE;CHARSET=BOGUS:Chef")
    assert f["last_name"] == "Müller" and f["title"] == "Chef"


def test_phone_types_uri_values_groups_and_urls():
    f = _v("N:Smith;John", "TEL;TYPE=CELL:330-555-0103", "TEL;type=fax:330-555-0102", "TEL;VALUE=uri;TYPE=work:tel:+1-330-555-0101",
           "item1.EMAIL;type=INTERNET:John@Acme.com", "URL:http\\://acme.com")
    assert [(p["type"], p["number"]) for p in f["phones"]] == [("mobile", "330-555-0103"), ("fax", "330-555-0102"), ("work", "+1-330-555-0101")]
    assert f["emails"] == ["john@acme.com"] and f["website"] == "http://acme.com"


def test_fn_fallback_keeps_compound_surname():
    f = _v("FN:Pieter van der Meer", "EMAIL:p@x.nl")
    assert (f["first_name"], f["last_name"]) == ("Pieter", "van der Meer")


def test_mecard_unescape():
    f = qr.parse_vcard("MECARD:N:Smith,John;ORG:Smith\\; Sons;TEL:3305550101;EMAIL:j@s.com;;")
    assert (f["first_name"], f["last_name"]) == ("John", "Smith") and f["company"] == "Smith; Sons"
