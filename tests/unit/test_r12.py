"""Round-12 regression tests (coordinator r4, newcomer r10)."""
import json
from test_app import mk
from app import parser

# real OCR output of qa/fixtures/event-stack 06 and 39 (live cards #244 / #242, Oct 14)
OCR06 = 'Farid Pemberton\n\nHead Groundskeeper\n\nT(330) 555-0165\nfpembertonasummitridgeanalytiexample com\nwwwsummitridgeanalytexamplecom\n3800 Embassy Pkwy.Akron.OH 44308'
OCR39 = 'Summit RidgeAnalytics\n\nFarid Penbeiton\n\nRegional HeadGroundskeeper\n\nT (33Q) 555-0165\nfpemberton@summitridgeanalytiexample.com\nwwwsummitridgeanalyti.example.com\n380oEmbassy Pkwy.Akron.OH 44308'
KEYS = ("first_name", "last_name", "company", "title", "emails", "phones", "website", "address")

BLANK = {"company": "", "emails": [], "phones": [], "website": "", "address": "", "title": ""}
def _parsed(t): f = parser.parse(t); return BLANK | {k: f.get(k) for k in KEYS if f.get(k) not in (None, "", [])}

def test_farid_06_39_linked_without_company(env):
    ui, store, rc = env["ui"], env["store"], env["rev"]
    f06, f39 = _parsed(OCR06), _parsed(OCR39)
    assert not f06.get("company")   # the case the coordinator hit: card 06 has no company
    a = mk(ui, store, **f06); b = mk(ui, store, **f39)
    for x, y in ((a, b), (b, a)):
        q = rc.get(f"/api/cards/{x}").json()["dupes"]["queue"]
        assert y in [d["card_id"] for d in q], (x, q)

def test_farid_linked_on_name_plus_any_field(env):
    """Name + website, name + address or name + email each link the pair, with no company and no phone."""
    ui, store, rc = env["ui"], env["store"], env["rev"]
    f06, f39 = _parsed(OCR06), _parsed(OCR39)
    for keep in ("website", "address"):
        a6 = BLANK | {k: v for k, v in f06.items() if k in ("first_name", "last_name", "title")} | {keep: f39.get(keep).replace("380o", "3800").replace("wwwsummit", "www.summit")}
        b9 = BLANK | {k: v for k, v in f39.items() if k in ("first_name", "last_name", keep)}
        a = mk(ui, store, **a6); b = mk(ui, store, **b9)
        assert b in [d["card_id"] for d in rc.get(f"/api/cards/{a}").json()["dupes"]["queue"]], keep
    a = mk(ui, store, **BLANK | dict(first_name="Farid", last_name="Pemberton", emails=["fpemberton@summitridgeanalyti.example.com"]))
    b = mk(ui, store, **BLANK | dict(first_name="Farid", last_name="Pemberton", emails=["fpemberton@summitridgeanalytiexample.com"]))
    assert b in [d["card_id"] for d in rc.get(f"/api/cards/{a}").json()["dupes"]["queue"]]

def test_different_people_same_name_not_linked(env):
    ui, store, rc = env["ui"], env["store"], env["rev"]
    a = mk(ui, store, **BLANK | dict(first_name="Farid", last_name="Pemberton", website="www.alpha-dental.example", address="12 Oak St, Kent, OH 44240"))
    b = mk(ui, store, **BLANK | dict(first_name="Farid", last_name="Pemberton", website="www.zeta-roofing.example", address="900 Main Ave, Canton, OH 44702"))
    assert b not in [d["card_id"] for d in rc.get(f"/api/cards/{a}").json()["dupes"]["queue"]]

def _merge(rc, src, tgt):
    return rc.post(f"/api/cards/{src}", json={"status": "rejected", "merge_into": tgt, "card_id": src})

def test_merge_takes_only_clean_values(env):
    """Coordinator r4 #3 (06+39): the misread email and the 'wwwsummit…' website of card 39 are not added to card 06."""
    ui, store, rc = env["ui"], env["store"], env["rev"]
    f06 = _parsed(OCR06) | {"company": "Summit Ridge Analytics", "website": "www.summitridgeanalyti.example.com"}
    f39 = _parsed(OCR39)
    a = mk(ui, store, **f06); b = mk(ui, store, **f39)
    pv = rc.post(f"/api/cards/{b}/merge-preview", json={"into": a}).json()
    assert "fpemberton@summitridgeanalytiexample.com" in [x if isinstance(x, str) else x.get("email", x) for x in pv.get("email_drop") or []] or pv.get("email_drop")
    assert _merge(rc, b, a).status_code == 200
    t = store.get(a)["fields"]
    assert t["emails"] == [] and t["website"] == "www.summitridgeanalyti.example.com", t
    assert [p["number"] for p in t["phones"]] == ["(330) 555-0165"]
    # an empty target with a garbled website: still not taken
    c_ = mk(ui, store, **(_parsed(OCR06))); d_ = mk(ui, store, **f39)
    assert _merge(rc, d_, c_).status_code == 200
    assert not store.get(c_)["fields"].get("website")
    # a clean email IS taken into an empty target
    e_ = mk(ui, store, **(_parsed(OCR06))); g_ = mk(ui, store, **(f39 | {"emails": ["fpemberton@summitridgeanalyti.example.com"], "website": "www.summitridgeanalyti.example.com"}))
    assert _merge(rc, g_, e_).status_code == 200
    assert store.get(e_)["fields"]["emails"] == ["fpemberton@summitridgeanalyti.example.com"]

def test_mctrade_merged_row_keeps_clean_org_spelling():
    """mctrade F4: the newest card's 'Hughes& Partners Law' must not beat the older card's correct spelling."""
    from app import mctrade_export as mx
    g = [{"id": 58}, [], {"OrgName": "Hughes& Partners Law", "FirstName": "Ann"}]
    why = mx._merge_into(g, {"id": 14}, {"OrgName": "Hughes & Partners Law", "FirstName": "Ann"}, "Same person as")
    assert g[2]["OrgName"] == "Hughes & Partners Law" and "NOT imported" not in why
    g = [{"id": 58}, [], {"OrgName": "Acme Ltd"}]
    assert "NOT imported" in mx._merge_into(g, {"id": 14}, {"OrgName": "Other Co"}, "x") and g[2]["OrgName"] == "Acme Ltd"
