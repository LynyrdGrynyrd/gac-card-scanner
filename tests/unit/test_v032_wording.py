"""v0.3.2 screen wording (newcomer v0.3.1 pass): short labels, one 'Different person' button, and the export page
no longer says 'Nothing to export yet' right after a successful export."""
import os
UI = os.path.join(os.path.dirname(__file__), "..", "..", "app", "static", "ui")
def rd(*p): return open(os.path.join(UI, *p), encoding="utf-8").read()

def test_export_page_after_export_says_all_exported():
    js = rd("views", "export.js")
    assert 'id="exWhy"' in js and "new-profile row" not in js and "match test contacts" not in js
    assert "Read the READ-ME and try 2 rows first" not in js and "ready.text" in js   # v0.4.6 #7: the server's 'Ready to import … Test 2 rows first.' line

def test_dup_box_one_different_person_button_and_plain_words():
    js = rd("views", "review.js")
    assert js.count('id="dDiff">Different<') == 2 and "Different person: add as new contact</button>" not in js   # v0.4 #7: Same / Different
    assert "(merge into #" not in js and "SAMPLE data:</b>" not in js and "Updating existing contacts is off" not in js
    assert "+${q.length - 1}" not in js

def test_labels():
    idx = rd("index.html")
    assert ">Read quality<" not in idx and "Reading method" not in idx and "> Skip AI</label>" not in idx
    assert '<kbd>↵</kbd> Approve' in idx and '<kbd>←</kbd><kbd>→</kbd> Card' in idx   # v0.4 #4: visible key hints
    assert "internal pilot" not in rd("login.html")
    assert "pending from everyone" not in rd("header.js")
