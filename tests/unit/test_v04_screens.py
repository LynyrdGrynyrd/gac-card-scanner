"""v0.4 screens (#2-#10 of the plan): export summary counts, 'changed' mark data, keyboard safety, theme, motion.
No data rule changes: blocks, confirms and exports are checked to behave as before."""
import os, re
from test_app import mk

UI = os.path.join(os.path.dirname(__file__), "..", "..", "app", "static", "ui")
def rd(*p):
    with open(os.path.join(UI, *p), encoding="utf-8") as fh: return fh.read()


def test_export_summary_counts_from_server_recheck(env):
    ui, st, rev = env["ui"], env["store"], env["rev"]
    a = mk(ui, st, first_name="Quinn", last_name="Vale", emails=["quinn@valeworks.example"], company="Vale Works"); ui.set_meta(a, batch="v04sum", batch_label="v04 sum")
    b = mk(ui, st, first_name="Rory", last_name="Pike", emails=["rory@pikeco.example"], company="Pike Co"); ui.set_meta(b, batch="v04sum", batch_label="v04 sum")
    for c in (a, b): assert rev.post(f"/api/cards/{c}", json={"status": "approved", "crm_action": "create_new"}).status_code == 200
    s = rev.get("/api/export/summary?status=approved_new&batch=v04sum").json()
    assert s["count"] == 2 and s["new"] + s["updated"] + s["left_out"] + s["to_check"] >= 2 and s["new"] == 2, s
    assert set(s) >= {"count", "new", "updated", "to_check", "left_out", "blocked"} and "Quinn" not in str(s)   # counts only
    assert rev.get("/api/export/summary?status=pending").status_code == 403   # same admin-only filter rule as the export
    # nothing was marked exported by the summary
    assert rev.get("/api/export/check?status=approved_new&batch=v04sum").json()["count"] == 2


def test_auto_fixed_marks_postfix_changes_only():
    from app import pipeline
    f = {"first_name": "Jo", "last_name": "Mars", "title": "Jo Mars, Partner", "company": "Mars Law", "emails": [], "phones": [], "website": "", "address": ""}
    out = pipeline.postfix_marked(dict(f))
    assert out["title"] == "Partner" and out["auto_fixed"] == {"title": "Jo Mars, Partner"}
    same = pipeline.postfix_marked({"first_name": "A", "title": "CEO", "company": "X", "emails": [], "phones": []})
    assert same["auto_fixed"] == {}


def test_auto_fixed_and_boxes_ignored_on_save(env):
    ui, st, rev = env["ui"], env["store"], env["rev"]
    cid = mk(ui, st, auto_fixed={"title": "x"}, boxes={"name": [0, 0, 1, 1]}); ui.set_meta(cid, batch="v04save")
    v = rev.get(f"/api/cards/{cid}").json()["version"]
    r = rev.post(f"/api/cards/{cid}", json={"fields": {"title": "CFO", "auto_fixed": {}, "boxes": {}}, "version": v}); assert r.status_code == 200, r.text
    f = st.get(cid)["fields"]; assert f["auto_fixed"] == {"title": "x"} and f["boxes"] == {"name": [0, 0, 1, 1]}


def test_enter_never_approves_in_dialog_or_with_edits():
    js = rd("views", "review.js")
    g = js[js.index("function enterOk"):js.index("document.addEventListener(\"keydown\"")]
    for need in ('dialog[open]', "S.dirty", "recomputeDirty()", "S.SAVING", "!S.CARD_READY", 'status !== "pending"', "#rErr", "BUTTON|A|TEXTAREA"):
        assert need in g, need
    assert 'if ($("#v-review").hidden || document.querySelector("dialog[open]")) return;' in js
    assert "ArrowRight" in js and "doUndo()" in js


def test_review_layout_one_primary_and_more():
    idx = rd("index.html"); rv = idx[idx.index('id="v-review"'):idx.index('id="v-export"')]
    acts = rv[rv.index('class="btns actions"'):rv.index('id="rMore"')]
    assert 'id="bApprove"' in acts and 'id="bSkip">Skip<' in acts and 'id="bReject"' not in acts and 'id="bSave"' not in acts
    more = rv[rv.index('id="rMore"'):]
    for i in ('id="bReject"', 'id="bSave"', 'id="rAI"', 'id="rHist"', 'id="rRaw"'): assert i in more, i
    assert rv.count("btn ok lg") == 1


def test_scan_screen_one_button_options_under_more():
    idx = rd("index.html"); up = idx[idx.index('id="v-upload"'):idx.index('id="phonePanel"')]
    assert 'id="bPhotos">Scan<' in up
    more = up[up.index('id="upMore"'):]
    for i in ('id="batchName"', 'id="skipAi"', 'id="bFolder"', 'id="bPhone"'): assert i in more, i


def test_export_one_button_and_sheet():
    idx = rd("index.html"); js = rd("views", "export.js")
    assert 'id="exGo"' in idx and idx.count('class="tile"') == 0 and 'name="exKind"' in idx
    assert 'title: "Ready to save"' in js and '"/api/export/summary' in js.replace("`", '"') and 'label: "Save"' in js
    assert '"New contacts"' in js and '"To check"' in js


def test_duplicate_side_by_side_same_different():
    js = rd("views", "review.js")
    assert "<b>Same person?</b>" in js and 'id="dSame"' in js and ">Same</button>" in js and 'id="dDiff">Different<' in js
    assert "fillDupGrid" in js and 'class="diff"' in js


def _lum(h):
    h = h.lstrip("#"); c = [int(h[i:i + 2], 16) / 255 for i in (0, 2, 4)]
    c = [x / 12.92 if x <= 0.03928 else ((x + 0.055) / 1.055) ** 2.4 for x in c]
    return 0.2126 * c[0] + 0.7152 * c[1] + 0.0722 * c[2]
def _cr(a, b): la, lb = sorted((_lum(a), _lum(b)), reverse=True); return (la + 0.05) / (lb + 0.05)


def test_dark_mode_tokens_and_contrast():
    css = rd("ui.css"); hdr = rd("header.js")
    assert "prefers-color-scheme:dark" in css and ":root[data-theme=dark]" in css and 'id="themeBtn"' in rd("index.html") and "gacTheme" in hdr
    dark = dict(re.findall(r"--([a-zA-Z]+):(#[0-9a-fA-F]{6})", css[css.index(":root[data-theme=dark]{"):].split("}")[0]))
    for fg, bg in (("ink", "card"), ("grey", "card"), ("ink", "bg"), ("teal-d", "card"), ("bad", "card"), ("ok", "card"), ("warnT", "warn")):
        f_ = dark.get(fg) or dark.get(fg.replace("-", "")); b_ = dark[bg] if bg in dark else None
        if fg == "teal-d": f_ = re.search(r"--teal-d:(#[0-9a-fA-F]{6})", css[css.index(":root[data-theme=dark]{"):]).group(1)
        assert f_ and b_ and _cr(f_, b_) >= 4.5, (fg, bg, f_, b_)
    for p in (("#ffe27a", "#3a3000"), ("#8ff0a4", "#0f3a1d"), ("#ffb4ab", "#4a1512"), ("#1c1c1e", "#7cc7d6"), ("#5c4700", "#fff4c2")): assert _cr(*p) >= 4.5, p


def test_motion_respects_reduced_motion():
    css = rd("ui.css")
    assert "@keyframes v04in" in css and "dialog[open]{animation:v04up" in css
    assert "@media (prefers-reduced-motion:reduce){*,*::before,*::after{animation:none!important;transition:none!important}" in css


def test_changed_mark_has_no_undo():
    js = rd("views", "review.js")
    seg = js[js.index("v0.4 #9"):js.index("Object.entries(d.confirmed")]
    assert ">changed</span>" in seg and "Undo" not in seg and "undo" not in seg.replace("no undo", "")
