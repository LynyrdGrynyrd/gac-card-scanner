# mctrade-dryrun: rehearse the MC Trade import offline
> Public repository: the example outputs (out/) and MemberClicks docs snapshots were left out; `python mctrade-dryrun/make_fixture_export.py` and `dryrun.py` regenerate examples from synthetic data.
**Everything in `sample-data/` is SAMPLE / FAKE.** It is not GAC data and not a real MC Trade export. Nothing here calls an API or contacts anyone.

| File | What it is |
|---|---|
| `sample-data/SAMPLE-FAKE_mctrade_profiles_export.csv` / `.xlsx` | 300 invented MC Trade profiles (105 organizations, 195 individuals), with realistic problems: a duplicate person, namesakes, an inactive ex-employee, a job change, blank and shared `info@` emails |
| `sample-data/SAMPLE-FAKE_existing_contacts_for_scanner.csv` | The same people in the scanner's `data/existing_contacts.csv` format |
| `gen_sample.py` | Regenerates the sample (deterministic) |
| `dryrun.py` | Approved cards from the scanner's export + an MC Trade export → import-ready upload files (one sheet, template columns only) + match report |
| `column_map.json` | The template column set (order, status, source) and which field fills which header. Replaced on day one by `--template` |
| `fixtures/FIXTURE_scanner_export_approved.xlsx`, `make_fixture_export.py` | A scanner-format export of 16 fictional test cards, to try the script |
| `out/example-fixture/` | Output of the fixture run (4 update, 5 create + 4 new orgs, 7 needs review) |
| `out/example-demo-video/` | Output for the cards exported in the demo video |
| `out/qa-r1-snapshot/` | Output for the MC Trade admin tester's offline snapshot of the live approved export (qa/mctrade-r1.md): 2 update, 5 create, 17 needs review (in-file duplicates, bad emails, HTML, formula text) |
| `DOCS-NOTES.md` | What the official MemberClicks / Atlas docs say, with URLs, and which API questions are now answered |
| `COLUMNS.md` | Where every column name comes from (DOCUMENTED / API-FIELD / UNVERIFIED) |
| `DAY-ONE-CHECKLIST.md` | Steps for when GAC has a real export, then an API key |
| `docs-snapshots/` | Text copies of the docs pages read on 2026-10-13 |

## Run it
```bash
cd gac-card-scanner
.venv/bin/python mctrade-dryrun/dryrun.py --export mctrade-dryrun/fixtures/FIXTURE_scanner_export_approved.xlsx
.venv/bin/python mctrade-dryrun/dryrun.py --export ~/Downloads/GAC-contacts-for-MC-Trade-new-approved-2026-10-15_1430.xlsx
.venv/bin/python mctrade-dryrun/dryrun.py --export <scanner.xlsx or .csv> --crm "<real MC Trade export.csv>" --template "<GAC Import Profiles template.xlsx>" --affcode CardScan-Pilot
```
Output goes to `mctrade-dryrun/out/<date_time>/`:
- `upload/A_New_organizations_<run>.xlsx`, `upload/B_New_individuals_<run>.xlsx`, `upload/C_Updates_existing_<run>.xlsx`: **the only files to upload.** One sheet each, the template column set only, template order, plain header row, every value a text cell. No READ ME tab, no audit columns, no colours or notes (MemberClicks refuses unknown columns, and the admin tester found the scanner's own Excel, with its READ ME FIRST sheet and 12 extra columns, is not importable: qa/mctrade-r1.md).
- `READ-ME_not-for-upload.md`: upload order, the column set with each header's status and source, and anything the template couldn't hold.
- `match_report.xlsx` / `.md`: one row per card: **UPDATE** (with old → new values), **CREATE** (with the organization link), or **NEEDS REVIEW** (with the reason). Review rows are left out of every import file.

## How a card is decided
- **UPDATE**: one MC Trade individual has the same email, or the same first+last name (nicknames allowed) plus the same organization or phone, and it is active, and the reviewer didn't choose "create new". Only changed fields are filled.
- **CREATE**: no individual matches. The employer is linked using MC Trade's own spelling, or added to the New organizations sheet.
- **NEEDS REVIEW**: FIX FIRST data problems (blank first/last name, invalid email, phone under 10 digits, HTML or formula-like text); the scanner flagged the card ("approved anyway"); two MC Trade profiles share the email; a name-only match (namesake or job change; MC Trade's importer would flag it too); same person but a different email; an inactive profile; the reviewer's choice contradicts the data; two cards in the file share an email or the same name + company (MC Trade does not de-duplicate inside a file); no email or phone.

**Do not upload the scanner's own "MC Trade import (Excel)" file directly.** Run it through `dryrun.py` and upload the files in `upload/`.

Needs only Python 3 + openpyxl (already in the scanner's `.venv`).
