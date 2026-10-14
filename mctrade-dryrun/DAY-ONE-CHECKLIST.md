# Day one: when GAC has a real MC Trade export (and, later, an API key)
*Greater Akron Chamber · Card Scanner pilot. Tick each box. Nothing here needs a developer until Part C.*

## Part A: first real import with Excel (no API needed)
**Before you start**
- [ ] Pick one person to own the import (an MC Trade admin) and one to double-check.
- [ ] In MC Trade, **Admin → Manage Codes**: create the Affiliation Code **`CardScan-Pilot`** (exact spelling). Files that use a code MC Trade doesn't have are rejected. *(H1)*
- [ ] Decide with the membership lead: should event contacts come in as **Prospects** or **Neither**? *(H2: the Import screen asks Members / Prospects / Neither)*

**Get the real template and export**
- [ ] **Admin → Import Profiles → Download Template Here**. Save it as `GAC-MCTrade-import-template.xlsx` in the scanner folder. *(H1)*
- [ ] Run the dry run with `--template "GAC-MCTrade-import-template.xlsx"`. The upload files then copy that template's header row exactly. Open `out/<run>/READ-ME_not-for-upload.md`: if it lists "Mapped fields NOT written" that you need (e.g. the template says `Profile ID` or `FirstName`), fix the names under `individual` / `organization` in `column_map.json` and re-run. Write the date and your initials in `_README`.
- [ ] Never upload the scanner's own "MC Trade import (Excel)" file: it has a READ ME FIRST tab and audit columns that MC Trade rejects (qa/mctrade-r1.md). Upload only `out/<run>/upload/*.xlsx`, and do not add tabs or notes to them.
- [ ] **Profile Selector**: search all **active Individuals** → **Actions → Export All System Columns** (allow pop-ups for app.atlasams.com). *(H5)* Save the CSV on the scanner computer only.
- [ ] Do the same for **Organizations**, or one export with both if Org Indication is included.
- [ ] Run `python3 mctrade-dryrun/dryrun.py --export <scanner Excel> --crm "<MC Trade export.csv>"`. If it stops with "could not find columns", add the real header names to `ALIASES` in `dryrun.py` (one line each).
- [ ] Also copy the export into the scanner's duplicate check: save `profile_id, first_name, last_name, organization, email, phone` columns as `data/existing_contacts.csv` (or ask a developer to point it at the full export).

**Rehearse**
- [ ] Open `out/<run>/match_report.xlsx`. Fix every **FIX FIRST** row in the scanner (blank name, bad email or phone, odd characters) and merge cards that are the same person twice; re-export and re-run. Then work through every other **NEEDS REVIEW** row in MC Trade first (search the name/email, decide, fix the card in the scanner or merge in MC Trade).
- [ ] Check 5 **UPDATE** rows by hand: is it really the same person? Are the "old → new" changes right? (MC Trade overwrites every filled cell. Blank cells don't erase anything.) *(H3)*
- [ ] Check 5 **CREATE** rows by searching MC Trade by last name and email.
- [ ] **Test with 2 rows** first: keep two rows in a copy of each file, import, check the profiles, then delete those 2 test profiles by hand if needed. *(H1, H2: imports cannot be undone)*

**Import, in this order** (separate imports, as MC Trade requires *(H1)*)
- [ ] `upload/A_New_organizations…xlsx` → Organizations, new profiles.
- [ ] `upload/B_New_individuals…xlsx` → Individuals, new profiles; relationship **Employer-Employee**; decide on "Main Contact as primary" (usually **no** for event contacts). In the duplicate checker, keep **Create new** only when you're sure it's a different person; otherwise **Ignore** the row and investigate. *(H2, H3)*
- [ ] `upload/C_Updates_existing…xlsx` → Individuals, **updates**: rows match on Profile ID, so **Overwrite** is pre-selected. Check it. *(H3)*
- [ ] Wait for MC Trade's results email. Spot-check 10 profiles. **Profile Selector → Affiliation Code = CardScan-Pilot** lists everything imported. *(H1)*
- [ ] Delete the export and import files from Downloads and the desktop. Keep only the match report in the pilot folder.

## Part B: write down what you learned (10 minutes)
- [ ] Which template headers differed from ours (send them to the developer: they belong in `column_map.json` and the scanner's export).
- [ ] What the real export headers are (for `ALIASES`).
- [ ] How many NEEDS REVIEW rows were real duplicates vs false alarms.

## Part C: when MemberClicks sends API credentials
*Developer work. Still: no writes until a person approves.*
- [ ] Request (GAC sends it, PILOT-PLAN.md has the draft): Client ID, Secret, **Tenant**, **API Base URI**, a **sandbox tenant**, rate limits, any fee. *(D1)*
- [ ] Create a dedicated, least-privilege MC Trade **user/group** for the integration; the token gets its permissions. *(D3)*
- [ ] Store the secret outside the code (environment / OS keychain). Never in the zip, the repo, or an email.
- [ ] Token: `POST https://www.weblinkauth.com/connect/token` (client_credentials, `scope=PublicWebApi`, `acr_values=tenant:<Tenant>`). Renew before `expires_in` (docs say 3600 s in one place and 24 h in another). *(D1, D2)*
- [ ] **Read-only first**: replace the CSV duplicate check with `GET Profiles?Email=…&RestrictToIndividual=true` and `GET Profiles?FirstName=…&LastName=…`, headers `Authorization: Bearer …` and `x-tenant`. Compare its answers with this dry run on 20 cards. *(D1, D4)*
- [ ] Find out on the **sandbox**: is `Email` search exact? Does `PUT Profile/{id}` clear omitted fields? Does `POST Profiles` with `MainRelatedProfileId` create the employer link, or is `PUT ProfileRelations` needed? Which `RelationTypeID` is Employer-Employee (`GET RelationTypes`)? *(D5–D7)*
- [ ] Writes only for approved cards, after a second "Send to MC Trade" click: `POST Profiles` (new) / `PUT Profile/{id}` (update) → `PUT ProfileRelations` → `POST Affiliations/AddProfilesToAffiliation?affCode=CardScan-Pilot`. Log every request and response in the audit log. *(D5–D8)*
- [ ] Optional: `POST Contacts` to record "met at <event>" on the profile. *(D3)*
- [ ] Undo plan: profiles tagged `CardScan-Pilot` can be listed with `GET Profiles?AffCodesAny=CardScan-Pilot`. Deleting is manual in MC Trade. *(D4, H2)*

Sources (H1–H8, D1–D9): see DOCS-NOTES.md §1.
