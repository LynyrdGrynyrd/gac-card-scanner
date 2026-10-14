# Column provenance
Legend: **DOCUMENTED** = exact header in an official MemberClicks page · **API-FIELD** = official API field name, not proven as an import/export header · **UNVERIFIED** = our inference. Source keys (H1, D5 …) are listed in DOCS-NOTES.md §1.

## A. Upload files written by dryrun.py
All three upload files (`A_New_organizations`, `B_New_individuals`, `C_Updates_existing`) use **one** column set, in this order, with one sheet and nothing else (MC Trade refuses columns that are not in its template, H1; the admin tester also found that a leading READ ME sheet breaks the import, qa/mctrade-r1.md B1). Defined in `column_map.json` → `template_columns`. With `--template` the real template's header row replaces this list.

| # | Header | Filled for | Status | Source |
|---|---|---|---|---|
| 1 | `ProfileID` | updates (C) | UNVERIFIED spelling. H2: "Include Profile ID and a corresponding name (OrganizationName or LastName)" | H2 |
| 2 | `OrgName` | orgs; people (employer, MC Trade's own spelling) | API-FIELD. H2 prose says "OrganizationName" | D5, H2 |
| 3–7 | `Address1`, `Address2`, `City`, `State`, `Zip` | orgs | API-FIELD | D5 |
| 8–9 | `WorkPhone`, `Fax` | orgs | API-FIELD | D5 |
| 10 | `Email` | orgs (blank: a rep's email is not the org's) | **DOCUMENTED** "the regular Email column would be for an organization" | H1 |
| 11 | `Website` | orgs | API-FIELD (the scanner says `WebAddress`) | D5 |
| 12 | `IndPrefix` | (blank) | UNVERIFIED | H1 Ind rule, D5 |
| 13–15 | `IndFirstName`, `IndLastName`, `IndTitle` | people (C: LastName always, from MC Trade) | UNVERIFIED (H2 says updates need "LastName") | H1, H2, D5 |
| 16–20 | `IndAddress1`, `IndAddress2`, `IndCity`, `IndState`, `IndZip` | people | UNVERIFIED (scanner exports one `Address`; split here, ZIP as text) | H1, D5 |
| 21–23 | `IndWorkPhone`, `IndCellPhone`, `IndFax` | people | UNVERIFIED (scanner says `IndPhone`); US numbers normalised, format UNVERIFIED | H1, D5 |
| 24 | `IndEmail` | people | **DOCUMENTED** "use the IndEmail column" | H1 |
| 25 | `MemberSince` | C only: `1/1/1900` | **DOCUMENTED** | H1, H2 |
| 26 | `Category` | (blank) | **DOCUMENTED** "must be an exact match" | H1 |
| 27 | `AffCode1` | every row: `CardScan-Pilot` (or `--affcode`) | **DOCUMENTED**; the code must already exist | H1 |
| – | `CustomFieldID<n>`, `AffCode2..n` | not written | DOCUMENTED; unused ones may be deleted | H1 |

## B. SAMPLE/FAKE MC Trade export (`sample-data/SAMPLE-FAKE_mctrade_profiles_export.csv`)
All headers are **API-FIELD** names from `PublicProfileDto` / `ProfileMinDto` (D1, D4, D6). Whether a real "Export All System Columns" CSV uses the same text is **UNVERIFIED**.
| Column | Notes |
|---|---|
| `SAMPLE_FAKE` | Our marker, always `SAMPLE-FAKE`. Not an MC Trade column |
| `ProfileId`, `OrgInd`, `ReportName`, `OrgName`, `Prefix`, `FirstName`, `LastName`, `Title`, `Email`, `WorkPhone`, `CellPhone`, `Fax`, `Website`, `Address1`, `Address2`, `City`, `State`, `Zip`, `Member`, `Prospect`, `Inactive`, `MembershipLevelName`, `DateCreated`, `DateChanged` | API-FIELD (D6) |
| `MainRelatedProfileId`, `MainRelatedProfileName` | API-FIELD in ProfileMinDto (D1 sample response). For individuals = employer org |
| `AffCodes` | UNVERIFIED layout (semicolon list). In the API, affiliations are a collection (D3 `GET Profile/{id}/Affiliations`); in the Profile Selector they are added as columns (H6) |
| Individuals' `OrgName` left blank | UNVERIFIED assumption; the employer is in `MainRelatedProfileName` |

`SAMPLE-FAKE_existing_contacts_for_scanner.csv` holds the same active individuals in the scanner's `data/existing_contacts.csv` shape (`profile_id, first_name, last_name, organization, email, phone`), for trying the scanner's own "already in MC Trade" check.
