"""v0.4.7: a reviewer's look-alike in ANOTHER of their own batches is a count (no link, no id, "in another batch"), and a
value typed while Approve is being sent is saved to the card it was typed on, not carried to the next card. Made-up cards only."""
import json
import re
from playwright.sync_api import expect
from test_flows import signed_in_admin, wait_card
from test_v045 import CLEAN, _db, _open, _scan_one, _set
from test_v046 import _reviewer, _shot


def test_own_older_batch_is_a_count_not_details(new_page, server):
    adm = signed_in_admin(new_page)
    rv = _reviewer(adm, new_page, user="rhea47a", pw="temp-pass-47047")
    old = _scan_one(rv, server, "s2_20_logo-band_dark.jpg", "E2E v047 old own")
    cur = _scan_one(rv, server, "s2_22_center_color.jpg", "E2E v047 current")
    same = dict(CLEAN, first_name="Ilse", last_name="Brandt", emails=["ilse@brandt-works.com"], website="brandt-works.com",
                company="Brandt Works", phones=[{"type": "work", "number": "(330) 555-0947"}])
    _set(server, old, fields=same); _set(server, cur, fields=dict(same, title="Partner"))
    _open(rv, cur)
    box = rv.locator("#rDupQ"); expect(box).to_contain_text("in another batch"); _shot(rv, "01_own_old_batch_count")
    t = box.inner_text()
    assert f"#{old}" not in t and "someone else" not in t and not rv.locator(f'a[href="#review/{old}"]').count()
    d = rv.request.get(f"/api/cards/{cur}").json()
    for part in (json.dumps(d.get("dupes")), json.dumps(d.get("exported_elsewhere"))):
        part = re.sub(r'"hidden_\w+": \d+', "", part)   # counts are fine; no id of the other batch's card
        assert not re.search(rf"(?<!\d){old}(?!\d)", part), part
    assert rv.request.get(f"/api/cards/{old}").status == 200   # the reviewer's own card still opens from its own batch


def test_edit_typed_during_approve_stays_on_its_card(new_page, server):
    page = signed_in_admin(new_page)
    a = _scan_one(page, server, "s2_24_two-column_light.jpg", "E2E v047 inflight")
    b = _scan_one(page, server, "s2_26_vertical_color.jpg", "E2E v047 inflight b")
    c = _db(server)
    with c: bt = c.execute("SELECT batch FROM card_meta WHERE card_id=?", (a,)).fetchone()[0]; c.execute("UPDATE card_meta SET batch=? WHERE card_id=?", (bt, b))
    c.close()
    _set(server, a, fields=dict(CLEAN, first_name="Ada", last_name="Flight", emails=["ada@flight-co.com"], website="flight-co.com", company="Flight Co",
                                phones=[{"type": "work", "number": "(330) 555-0931"}]))
    _set(server, b, fields=dict(CLEAN, first_name="Bea", last_name="Ground", emails=["bea@ground-co.com"], website="ground-co.com", company="Ground Co",
                                phones=[{"type": "work", "number": "(330) 555-0932"}], title="Owner"))
    _open(page, a); expect(page.locator("#first_name")).to_have_value("Ada")
    # the Approve request waits 1.5 s in the browser, so typing lands while it is in flight
    page.evaluate("""cid => { const f0 = window.fetch; window.fetch = async (u, o) => {
        if (String(u).endsWith('/api/cards/' + cid) && o && o.method === 'POST' && String(o.body || '').includes('"approved"')) await new Promise(r => setTimeout(r, 1500));
        return f0(u, o); }; }""", a)
    page.locator("#bApprove").click(); page.wait_for_timeout(300)
    page.locator("#title").fill("Late Title")
    wait_card(page, b)
    expect(page.locator("#title")).to_have_value("Owner")
    page.wait_for_timeout(800)
    ca = page.request.get(f"/api/cards/{a}").json()["card"]; cb = page.request.get(f"/api/cards/{b}").json()["card"]
    assert ca["status"] == "approved" and ca["fields"]["title"] == "Late Title", ca["fields"].get("title")
    assert cb["fields"]["title"] == "Owner" and cb["status"] == "pending"
    assert page.evaluate("id => Object.keys(localStorage).filter(k => k.startsWith('gac-draft-') && k.endsWith('-' + id)).length", b) == 0
