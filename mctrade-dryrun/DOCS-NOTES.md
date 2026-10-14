# MC Trade / WebLink (Atlas) documentation notes for the dry run
*Read 2026-10-13 from public official sources only. Nobody was contacted and no API was called.*
Raw copies: `docs-snapshots/` (`api-*.txt`, `wl-*.txt` = page text from the Atlas developer site; `hc-excerpts-2026-10-13.txt` = verbatim help-center excerpts. The help center blocks plain downloads, so those pages were read with a web reader and quoted.)

Status labels used everywhere in this folder:
- **DOCUMENTED**: the exact text is in an official MemberClicks / Atlas page (URL given).
- **API-FIELD**: a field name in the official API reference. It is probably the same in the import template, but that is not proven.
- **UNVERIFIED**: our inference. Check it against GAC's own template or export.

## 1. Sources
| # | Page | What it gives us |
|---|---|---|
| H1 | https://atlas.memberclicks.com/hc/en-us/articles/14749994164365-Prepare-Excel-Profile-Data-for-Importing | Template rules: `Ind` prefix, `IndEmail` vs `Email`, `AffCode1..n`, `CustomFieldID<n>`, separate sheets |
| H2 | https://atlas.memberclicks.com/hc/en-us/articles/14749982935181-Import-Profiles-into-MC-Trade | Import screen options, relationships, updates need Profile ID + name, cannot undo |
| H3 | https://atlas.memberclicks.com/hc/en-us/articles/14750474900621-Import-Tool-Duplicate-Checker | How the importer finds duplicates and what overwrite does |
| H4 | https://atlas.memberclicks.com/hc/en-us/articles/14750415070477-Breakdown-of-Profile-Name-Fields | Sort Name / Report Name defaults |
| H5 | https://atlas.memberclicks.com/hc/en-us/articles/23255313831821--Using-the-Profile-Selector-Grid | The two CSV export options and their columns |
| H6 | https://atlas.memberclicks.com/hc/en-us/articles/22968261911949-Changing-the-Profile-Selector-Columns | Default grid columns, Manage Columns |
| H7 | https://atlas.memberclicks.com/hc/en-us/articles/14750193737613-Extracting-and-Exporting-Data | Profile Selector and Query Tool exports |
| H8 | https://atlas.memberclicks.com/hc/en-us/articles/14750097934349-MC-Trade-Public-API | API scope, how to request access |
| D1 | https://developers.weblinkconnect.com/api-v1/getting-started | How to request access, credentials returned, token request, first `GET /api-v1/profiles` call |
| D2 | https://developers.weblinkconnect.com/api-v1/api-authorization | Grant types, token lifetime (two different statements), sandbox tenant name |
| D3 | https://developers.weblinkconnect.com/api-v1/api-resources and https://api-v1.weblinkconnect.com/api-resources/Profile | Endpoint list |
| D4 | https://api-v1.weblinkconnect.com/api-resources/Profile/GET-Profiles | Search parameters (incl. `Email`, `FirstName`, `LastName`, `OrgName`, `AffCodesAny`), paging |
| D5 | https://api-v1.weblinkconnect.com/api-resources/Profile/POST-Profiles | Create profile (`ProfileDto`), returns the new id |
| D6 | https://api-v1.weblinkconnect.com/api-resources/Profile/PUT-Profile-id | Update profile (`PublicProfileDto`) |
| D7 | https://api-v1.weblinkconnect.com/api-resources/Profile/PUT-ProfileRelations | Create relationship (`ProfileRelationDto`) |
| D8 | https://api-v1.weblinkconnect.com/api-resources/Affiliation (AddProfilesToAffiliation) | Tag profiles with an Affiliation Code |
| D9 | https://developers.weblinkconnect.com/api-v1/help | Support route, 24 h response target |

Not found publicly: a downloadable copy of the Import Profiles template (it sits behind the MC Trade admin login, H1 step 2), a Swagger/OpenAPI file (`/swagger` returns HTTP 500, `/swagger/v1/swagger.json` 404), rate limits, pricing, and a written "Developers Guide" beyond the pages above (H8 links to the same developer site).

## 2. Import rules the dry run follows
| Rule | Source | How dryrun.py applies it |
|---|---|---|
| Individuals use `Ind`-prefixed columns; `IndEmail` is the person's email, plain `Email` is the organization's | H1 | Individual sheets use `Ind…` headers; the org sheet uses `Email` |
| Import Individuals and Organizations in **separate** spreadsheets | H1 | Separate files in `out/<run>/upload/` |
| Keep **new profiles** and **updates to existing** in separate spreadsheets and imports | H1 | Sheet/file B (new) vs C (updates) |
| Updates must include **Profile ID** and a matching name (**OrganizationName or LastName**) | H2 | Sheet C always has `ProfileID` + `IndLastName` (taken from MC Trade's spelling) |
| `AffCode1`, `AffCode2`… values must **already exist** or the whole file is invalid | H1 | Every row gets `AffCode1 = CardScan-Pilot`; checklist says to create the code first |
| Best practice: tag each import with its own Affiliation Code so it can be reported on and removed in bulk | H1, H5 | Same |
| "do not include columns of data for anything that is not listed in this article. Unused affiliation codes and custom fields can be deleted, but deleting other information could cause errors. The import will not proceed until the source file is properly formatted with these columns." | H1 (quote) | Every upload file uses **one fixed column set in template order** (§3). No audit columns, no extra columns. Unused template columns stay as **blank columns**, not deleted. With `--template` the header row is copied from GAC's real template |
| The upload is one Excel file per import ("Upload Excel File"); the MC Trade admin tester found that the scanner's Excel, with a leading **READ ME FIRST** sheet, is not importable as-is | H2 + qa/mctrade-r1.md B1 | Upload files have **exactly one sheet**, plain header row in row 1, no notes, colours or README. The instructions go in a separate `READ-ME_not-for-upload.md` and the match report |
| Test with a couple of rows first; an import **cannot be undone**; imported profiles can only be deleted one at a time | H1, H2 | READ ME + checklist |
| Importer duplicate check: Profile ID exact; first+last name for individuals; Sort Name for orgs; address if chosen; Profile Name and Email by default | H2, H3 | Name-only matches are sent to NEEDS REVIEW because MC Trade will flag them too |
| Overwrite replaces every non-blank value; **blank cells never erase** | H3 | Update rows fill only fields that differ from MC Trade |
| Relationship Org→Individual chosen on the Import screen, usually **Employer-Employee**; option to make Main Contact primary | H2 | New individuals carry `OrgName` with MC Trade's exact organization spelling; new orgs go first (sheet A) |
| Members / Prospects / Neither is chosen per import; Membership Level is not set by imports | H2 | Not set by us; the checklist asks GAC which to pick (likely **Neither** or **Prospects** for event contacts) |
| "The MemberSince date can only be imported for new Member profiles"; on updates "use the date 1/1/1900 to avoid overwriting the profile's existing MemberSince date" | H1, H2 | New rows leave `MemberSince` blank (event contacts are not new members). Update rows (file C) get `1/1/1900` |
| MC Trade checks duplicates only against **existing** profiles (Profile ID / name / email), not between rows of one file | H3 + qa/mctrade-r1.md B2 | Two cards in one export with the same email, or the same first+last name+company: the first copy goes ahead, the other is **NEEDS REVIEW** (merge it in the scanner) |
| Data that would stay wrong in MC Trade (imports cannot be undone) | qa/mctrade-r1.md H1–H3, M1–M2 | **FIX FIRST** → NEEDS REVIEW for: blank first/last name, invalid email, phone with fewer than 10 digits, HTML in a field, values that start like a formula (`=`, `+`, `@`). The scanner's `'` formula-guard prefix is removed before matching (in a text cell it would be stored as a real apostrophe). US phones are normalised to `(330) 555-0177 ext. 990` (MC Trade's preferred format is **not published**). Addresses are split into Address1/Address2/City/State/Zip; ZIP kept as text |

## 3. Columns: the template column set
MemberClicks does **not** publish the Import Profiles header row. The template is only downloadable inside MC Trade (**Admin → Import Profiles → Download Template Here**, H1 step 2). What is documented as header text: `IndEmail` vs `Email`, `AffCode1..n`, `CustomFieldID<n>`, `MemberSince`, `Category` (H1); "Profile ID" and "OrganizationName or LastName" appear in prose (H2). H1 also implies **one template for both kinds of profile**: individual columns carry the `Ind` prefix, organization columns don't.

So `dryrun.py` writes the **same** column set, in the same order, to all three upload files (orgs fill the org columns, people fill the `Ind…` columns plus `OrgName` as employer, the rest stay blank):

`ProfileID, OrgName, Address1, Address2, City, State, Zip, WorkPhone, Fax, Email, Website, IndPrefix, IndFirstName, IndLastName, IndTitle, IndAddress1, IndAddress2, IndCity, IndState, IndZip, IndWorkPhone, IndCellPhone, IndFax, IndEmail, MemberSince, Category, AffCode1`

| Status | Headers |
|---|---|
| **DOCUMENTED** header text (H1) | `Email`, `IndEmail`, `MemberSince`, `Category`, `AffCode1` |
| **API-FIELD** (D5 ProfileDto name, not proven as a header) | `OrgName`, `Address1`, `Address2`, `City`, `State`, `Zip`, `WorkPhone`, `Fax`, `Website` |
| **UNVERIFIED** (`Ind` prefix rule + API name) | `ProfileID` (spelling), `IndPrefix`, `IndFirstName`, `IndLastName`, `IndTitle`, `IndAddress1/2`, `IndCity`, `IndState`, `IndZip`, `IndWorkPhone`, `IndCellPhone`, `IndFax` |
| Left out (unused, H1 allows deleting) | `CustomFieldID<n>`, `AffCode2..n` |
| **Removed** compared with the scanner's own Excel (not template columns; qa/mctrade-r1.md B1) | `IndEmail2`, `IndPhone`→`IndWorkPhone`, `WebAddress`→`Website`, `Address`→split, `Credentials`, `Department`, `OtherAddress`, `AllEmails`, `AllPhones`, `Note`, `ScanCardID`, `ReviewedBy`, `DecidedAt`, `Batch`, `MCTradeAction`, `NeedsAttention`, and the READ ME FIRST sheet |

**Day one, this is the one step that makes the column set "correct":** run with `--template "<GAC template>.xlsx"`. The script then copies the template's first sheet exactly (its sheet name, headers and order), fills only the headers it recognises from `column_map.json` → `individual` / `organization`, leaves every other template column blank, and lists in `READ-ME_not-for-upload.md` any mapped field the template has no header for. If a header is spelled differently (e.g. `Profile ID`), edit the mapping in `column_map.json`. Per-column sources: `COLUMNS.md`.

## 4. API findings (resolves RESEARCH.md §2 unknowns)
| Question | Answer | Status / source |
|---|---|---|
| How to get access | The **customer** (GAC) emails apisupport@memberclicks.com with customer name, requester, 3rd-party name and email. Reply contains Client ID, Client Secret, **Tenant**, and the **API Base URI** | DOCUMENTED D1 |
| Token | `POST https://www.weblinkauth.com/connect/token`, form body `grant_type=client_credentials&scope=PublicWebApi&client_id=…&client_secret=…&response_type=token&acr_values=tenant:<Tenant>` | DOCUMENTED D1, D2 |
| Token lifetime | D2 says both "Access tokens are valid for twenty-four hours" and `expires_in` "generally set to 3600 (1 hour)". **Trust `expires_in`** and refresh before it runs out. Client credentials returns no refresh token | DOCUMENTED but contradictory |
| Calling the API | `Authorization: Bearer <token>` and header `x-tenant: <Tenant>`; example host `api-v1.weblinkconnect.com`, path `/api-v1/profiles?RestrictToMember=true`. Use the Base URI from the credentials email | DOCUMENTED D1 (the example writes `Header: x-tenant=[Tenant]`) |
| Search by email / name (duplicate check) | `GET Profiles` with `Email`, `FirstName`, `LastName`, `OrgName`, `Keyword`, `RestrictToIndividual`, `RestrictToActive`, `AffCodesAny`, `PageNumber`, `PageSize`; returns `TotalCount`, `Result[]` of `ProfileMinDto` (ProfileId, OrgInd, Email, FirstName, LastName, OrgName, MainRelatedProfileId/Name, …) | DOCUMENTED D4, D1. Whether `Email` is exact or partial match: **UNVERIFIED** |
| Create a person | `POST Profiles` with `ProfileDto` (`OrgInd=false`, `FirstName`, `LastName`, `Title`, `Email`, `WorkPhone`, `CellPhone`, `Fax`, `Address1`, `City`, `State`, `Zip`, `Prospect`, `MainRelatedProfileId`, …); response = new ProfileId (integer) | DOCUMENTED D5. Whether `MainRelatedProfileId` alone creates the employer relationship: **UNVERIFIED** |
| Update a person | `PUT Profile/{id}` with `PublicProfileDto`; no response body | DOCUMENTED D6. Whether omitted/blank fields are left alone or cleared: **UNVERIFIED** (safe path: GET the profile, change fields, PUT the full object) |
| Link person ↔ organization | `PUT ProfileRelations` with `ProfileRelationDto` (`ProfileID`, `RelProfileID`, `RelationTypeID`, `InvRelationTypeID`, `MainContact`, `Title`, …); relation types via `GET RelationTypes` | DOCUMENTED D7 (yes, PUT creates: "Create a profile relation") |
| Tag with Affiliation Code | `POST Affiliations/AddProfilesToAffiliation?affCode=…&profileIds[0]=…`; remove with the matching DELETE | DOCUMENTED D8 |
| Log the meeting | `POST Contacts` (`ContactDto`: ProfileId, ContactDate, ContactType, Subject, Message …) creates a contact record, e.g. "Met at Business After Hours" | DOCUMENTED D3 (optional idea) |
| Changed-since sync | `GET ProfilesChanged`, and `GET Profiles` with `RestrictToChanged`/`DateChangedStartDate` | DOCUMENTED D3, D4 |
| Sandbox | The docs' example user belongs to tenant `WEBLINKAPIINCOC`, org name "Atlas API Dev Sandbox". Whether GAC can get a sandbox tenant: **ask** | DOCUMENTED D2 (existence only) |
| Rate limits, fees | Not published. The MC Trade SSO article (RESEARCH.md §1) says API use "may incur an added charge" | **UNVERIFIED** |
| Permissions | Tokens carry the permissions of the Atlas user/group they are tied to | DOCUMENTED D3 |
| Support | apisupport@memberclicks.com; reply aimed within 24 h | DOCUMENTED D9 |

## 5. What the "MC Trade export" sample models
GAC's real duplicate list will come from **Profile Selector → Actions → Export All System Columns** (all system fields) or **Export to CSV** (Profile ID, Org Indication, Profile Name, Related Organization, Main Email, Membership Level, Member T/F) (H5), or a **Query Tool** export (H7). The exact header text of those CSVs is not published. The sample therefore uses the documented **API field names** (`ProfileId`, `OrgInd`, `FirstName`, `Email`, `MainRelatedProfileName`, …). `dryrun.py` accepts common alternative spellings (see `ALIASES`), and stops with a clear message if it cannot find Profile ID, last name and email.

## 6. Still unverified (ask MemberClicks or test with 2 rows)
From our reading and the MC Trade admin tester's round 1 (`qa/mctrade-r1.md`, "NOT PUBLISHED" rows):
- Exact template header text for name, title, phone, address, city, state, zip, website, Profile ID (template is behind the admin login). Fix: `--template`.
- Phone, ZIP, state and date formats; extension handling; file encoding; maximum file size / row count; `.xls` vs `.xlsx`. (MC Professional, a sister product, accepts .xls/.xlsx: https://help.memberclicks.com/hc/en-us/articles/16908823990925-Profile-import. Not proof for MC Trade.)
- Whether the importer reads only the first sheet (we write exactly one sheet either way).
- How the Employer-Employee link is made from an individual row (we fill `OrgName` with MC Trade's exact spelling and import new organizations first).
- API: exact vs partial `Email` search, whether `PUT Profile/{id}` clears omitted fields, sandbox for GAC, rate limits, fees (§4).
