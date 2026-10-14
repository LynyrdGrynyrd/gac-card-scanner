"""Build fixtures/FIXTURE_scanner_export_approved.xlsx: a file in the exact layout of the scanner's
'MC Trade import (Excel)' export (READ ME FIRST + Individuals sheet, columns from app/ui.py XCOLS+MORE+AUDIT),
filled with the scanner's FICTIONAL synthetic test people (tests/ground_truth.json, tests/synth2_gt.json).
Used to exercise dryrun.py without real member data. Does not touch the app or its database."""
import json, os, sys
from openpyxl import Workbook
HERE = os.path.dirname(os.path.abspath(__file__)); ROOT = os.path.dirname(HERE)
sys.path.insert(0, ROOT)
from app.mctrade_sync import to_mctrade_profile   # read-only reuse of the app's own column mapping
XCOLS = ["IndFirstName", "IndLastName", "IndTitle", "OrgName", "IndEmail", "IndPhone", "IndCellPhone", "IndFax", "WebAddress", "Address", "AffCode1"]
MORE = ["Credentials", "Department", "OtherAddress", "AllEmails", "AllPhones", "Note"]
AUDIT = ["ScanCardID", "ReviewedBy", "DecidedAt", "Batch", "MCTradeAction", "NeedsAttention"]
gt = {**json.load(open(os.path.join(ROOT, "tests/ground_truth.json"))), **json.load(open(os.path.join(ROOT, "tests/synth2_gt.json")))}
PLAN = [  # (card, MCTradeAction chosen by the reviewer, NeedsAttention)
    ("card1_left.jpg", "update existing", ""), ("card2_center.jpg", "", ""), ("card3_dark.jpg", "", ""),
    ("card4_noisy_rot.jpg", "update existing", ""), ("card5_left.jpg", "", ""), ("card6_center.jpg", "update existing", ""),
    ("hard1_twocol.jpg", "", ""), ("hard3_lowres_italic.jpg", "", ""), ("s2_24_two-column_light.jpg", "", ""),
    ("s2_25_footer-row_color_photo.jpg", "", ""), ("s2_00_left_light.jpg", "create new", ""),
    ("s2_01_center_light_photo.jpg", "update existing", ""),
    ("s2_15_center_light_photo.jpg", "", "APPROVED ANYWAY by DT: mobile number smudged on card"),
    ("s2_05_vertical_light_photo.jpg", "", ""), ("s2_06_logo-band_light.jpg", "", ""), ("s2_08_center_light.jpg", "", "")]
wb = Workbook(); ws = wb.active; ws.title = "Individuals"; ws.append(XCOLS + MORE + AUDIT)
for i, (card, act, flag) in enumerate(PLAN, 101):
    f = dict(gt[card]); f.setdefault("social", [])
    p = to_mctrade_profile(f)
    more = ["", "", "", "; ".join(f["emails"]), "; ".join(f"{x['type']}: {x['number']}" for x in f["phones"]), ""]
    ws.append([p.get(k, "") for k in XCOLS] + more + [i, "DT", "2026-10-13 15:0%d" % (i % 10), "FIXTURE · synthetic test cards", act, flag])
n = wb.create_sheet("READ ME FIRST", 0)
n.append(["FIXTURE (fictional synthetic test cards) in the layout of the GAC scanner's MC Trade Excel export. Not real people."])
os.makedirs(os.path.join(HERE, "fixtures"), exist_ok=True)
out = os.path.join(HERE, "fixtures", "FIXTURE_scanner_export_approved.xlsx"); wb.save(out); print(len(PLAN), "rows ->", out)
