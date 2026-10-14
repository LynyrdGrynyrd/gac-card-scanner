# GAC Business-Card Scanner — Research Notes (pilot)
_Compiled 2026-10-13. Public sources only. OCR/VLM characterizations are from general knowledge of these projects and should be re-benchmarked on real GAC cards._

## 1. What is "MCTrade"? (corrected assumption)
**MCTrade = "MC Trade" by MemberClicks** — *not* Micronet/ChamberMaster. ChamberMaster/MemberZone is the GrowthZone (formerly Micronet) product line, a different vendor.
MC Trade is the rebranded **WebLink Connect / "Atlas"** chamber platform (developer docs still live at `developers.weblinkconnect.com`, auth server `weblinkauth.com`, and the MC Trade SSO help article links there).
- MC Trade Public API article: https://atlas.memberclicks.com/hc/en-us/articles/14750097934349-MC-Trade-Public-API
- MemberClicks MC Trade integrations page: https://memberclicks.com/integrations/mc-trade/
- SSO article pointing to WebLink docs (notes API "may incur an added charge"): https://atlas.memberclicks.com/hc/en-us/articles/14750152306701-Planning-for-Single-Sign-On-SSO-with-MC-Trade-and-another-Software
- API Authorization docs: http://developers.weblinkconnect.com/api-v1/api-authorization
- API Resources docs: http://developers.weblinkconnect.com/api-v1/api-resources
- Excel import template article: https://atlas.memberclicks.com/hc/en-us/articles/14749994164365-Prepare-Excel-Profile-Data-for-Importing
- Third-party write-up (Aurinko connector): https://www.aurinko.io/blog/member-clicks-trade-api/

## 2. MC Trade API findings
| Topic | Finding | Confidence |
|---|---|---|
| Style | JSON REST, OAuth 2.0 + OpenID Connect protected | Confirmed (docs) |
| Read/write | "pull data from MC Trade as well as post data … back in" | Confirmed (MemberClicks article) |
| Data scope | General Profile info, Related Profiles/Relationships, Affiliations & Committees, Listings, Event settings/registrations, Users | Confirmed |
| Auth flows | **Client Credentials** (server-to-server; best for this tool) and **Hybrid** (user login w/ redirect) | Confirmed |
| Token endpoint | `POST https://www.weblinkauth.com/connect/token` form body: `grant_type=client_credentials&scope=PublicWebApi&client_id=…&client_secret=…&response_type=token&acr_values=tenant:<SiteID>` | Confirmed (docs) |
| Credentials needed | Client ID, Client Secret, **Tenant (SiteID)** — issued via the customer (GAC) | Confirmed |
| Token life | Docs inconsistent: "valid twenty-four hours" vs `expires_in` "generally set to 3600 (1 hour)" | Ambiguous (see update below) |
| Permissions | Token inherits permissions of the Atlas user/group it's tied to | Confirmed |
| Data model | `Profile` = person or organization, flagged by `OrgInd`; relationships link rep ↔ org | Confirmed via Aurinko; field name not seen in official page |
| Search | GET Profiles supports keyword, profile IDs, profile types, date filters | Per Aurinko (secondary) |
| Access | Request from **apisupport@memberclicks.com**; possibly an added subscription fee | Confirmed |
| Bulk import (no API) | Admin → Import Profiles; Excel template; separate Individual vs Organization sheets; `Ind`-prefixed columns for individuals (e.g. `IndEmail`); `AffCode1..n` columns; recommended: tag imports with an Affiliation Code | Confirmed |

### Update 2026-10-13: earlier unknowns, resolved from official docs
Full notes with quotes and per-column sources: `mctrade-dryrun/DOCS-NOTES.md` (page text in `mctrade-dryrun/docs-snapshots/`). Public pages only. Nobody was contacted and no API was called.
| Earlier unknown | Now | Status |
|---|---|---|
| Create / update a person | `POST Profiles` (ProfileDto, `OrgInd=false`; returns the new ProfileId) and `PUT Profile/{id}` (PublicProfileDto) — https://api-v1.weblinkconnect.com/api-resources/Profile/POST-Profiles, .../PUT-Profile-id | Documented |
| Link a rep to an Organization | `PUT ProfileRelations` ("Create a profile relation": ProfileID, RelProfileID, RelationTypeID, MainContact…); types from `GET RelationTypes` | Documented. Whether `MainRelatedProfileId` on POST already links: unverified |
| Search by email / name (duplicate check) | `GET Profiles` with `Email`, `FirstName`, `LastName`, `OrgName`, `RestrictToIndividual`, `AffCodesAny`, paging — https://api-v1.weblinkconnect.com/api-resources/Profile/GET-Profiles | Documented. Exact vs partial email match: unverified |
| Base URL / headers | Base URI comes with the credentials; example `GET https://api-v1.weblinkconnect.com/api-v1/profiles?RestrictToMember=true` with `Authorization: Bearer` and `x-tenant` header — https://developers.weblinkconnect.com/api-v1/getting-started | Documented. `app/mctrade_sync.py` still shows the old `<tenant>/api/v1/profiles` placeholder (app code not changed here) |
| Token lifetime | Same page says "valid for twenty-four hours" and `expires_in` "generally set to 3600 (1 hour)". Trust `expires_in`. Client credentials gives no refresh token | Documented, contradictory |
| Affiliation Code tagging | Import: `AffCode1..n` columns, value must already exist. API: `POST Affiliations/AddProfilesToAffiliation?affCode=…&profileIds[0]=…` | Documented |
| Sandbox | The docs' example tenant `WEBLINKAPIINCOC` is named "Atlas API Dev Sandbox". Whether GAC gets one: ask | Exists. Availability for GAC unverified |
| Rate limits, fees | Not published anywhere public. The SSO article says API use "may incur an added charge" | Unverified (ask) |
| Swagger / OpenAPI | Not public (`/swagger` → HTTP 500). The developer-site reference pages are the "Developers Guide" | Checked |
| Import template columns | Documented: `IndEmail` (person) vs `Email` (org), `AffCode1..n`, `CustomFieldID<n>`, `MemberSince`, `Category`; updates need Profile ID + LastName/OrganizationName; orgs vs individuals and new vs updates go in separate files. `IndFirstName`, `IndLastName`, `IndTitle`, phone and address headers are inferred. The template itself is only downloadable inside MC Trade (Admin → Import Profiles) | Partly documented. Verify with GAC's template |
| Importer duplicate rules | Profile ID exact; individuals First+Last name; orgs Sort Name; address optional; overwrite replaces non-blank cells only — https://atlas.memberclicks.com/hc/en-us/articles/14750474900621-Import-Tool-Duplicate-Checker | Documented |
| Prospect / non-member records | Import screen offers Members / Prospects / Neither; ProfileDto has `Member`, `Prospect` flags | Documented. GAC to choose |
| Custom fields GAC uses | Still unknown (`CustomFieldID<n>`; ids in Admin → Manage Codes → Profile Codes → Custom Fields) | Ask GAC |

Still to ask MemberClicks: sandbox tenant for GAC, rate limits, fees, whether `PUT Profile/{id}` clears omitted fields, exact `Email` search semantics, and confirmation of the Import Profiles template headers. A dry run against a SAMPLE/FAKE export is in `mctrade-dryrun/` (see its `DAY-ONE-CHECKLIST.md`). Its upload files have one sheet and only the template column set (no README tab, no audit columns), because the Import Profiles tool refuses columns that are not in the template (H1) and the MC Trade admin tester found the scanner's own Excel not importable as-is (`qa/mctrade-r1.md`). On day one it copies GAC's real template header row via `--template`.

## 3. OCR options (all free / open source, run locally)
| Engine | License | CPU feasibility | Card accuracy (typical) | Notes |
|---|---|---|---|---|
| **Tesseract 5** | Apache-2.0 | Excellent (~0.3–1 s/card) | Good on clean/flat print; weak on stylized fonts, multi-column, curved/glare photos | apt install; tiny footprint. **Used in prototype.** |
| **PaddleOCR (PP-OCRv4/v5)** | Apache-2.0 | Good (1–3 s/card CPU) | Generally better than Tesseract on photos, rotated text, multi-column | Bigger dependency (paddlepaddle); strongest CPU upgrade candidate |
| **docTR** (Mindee) | Apache-2.0 | OK (PyTorch, 2–5 s) | Strong detection+recognition, good on documents | Heavier install |
| **EasyOCR** | Apache-2.0 | Slow-ish on CPU (3–10 s) | Decent; good multilingual | Simplest API, PyTorch |

## 4. Local vision LLMs (optional path — end-to-end "image → JSON")
| Model | Size | CPU feasibility | Notes |
|---|---|---|---|
| **Qwen2.5-VL 3B/7B** (`ollama pull qwen2.5vl:3b`) | 3–7B | 3B: ~20–60 s/card on 8-core CPU; 7B: minutes. Fast on any GPU/Apple Silicon | Best open model for document/key-value extraction; returns JSON directly. Recommended LLM path. |
| **Llama 3.2 Vision 11B** (Ollama) | 11B | Too slow on CPU for interactive use | Good quality; needs GPU/Mac |
| **Moondream 2** | ~1.9B | Feasible on CPU (~5–15 s) | Small; OK captions/VQA, weaker on dense structured text |
| **Florence-2 (base/large)** | 0.23/0.77B | Very feasible on CPU | Has an `<OCR_WITH_REGION>` task — a good OCR engine, but not a JSON extractor by itself |

Risk: LLMs can *hallucinate* plausible-looking emails/phones. Mitigation: cross-check LLM fields against OCR raw text and validate with `phonenumbers`/regex; always keep human approval.

## 5. Field parsing
- **phonenumbers** (Google libphonenumber port): robust US/intl phone detection, normalization, validation, extensions. Used.
- **Regex**: emails, URLs, social handles, ZIP/state lines. Used.
- **libpostal** (MIT): best open address parser/normalizer, but ~2 GB model data and C build — worth it in production, overkill for the pilot. `usaddress` (MIT, small, US-only CRF) is a lightweight middle ground.
- **Names/titles/company**: heuristics (title keywords, company suffixes, email-local-part ↔ name match). Optional: `probablepeople`, spaCy NER, or let the VLM do it.

## 6. vCard / QR
- Many cards carry a QR with a vCard (`BEGIN:VCARD`), MECARD, or a URL. Decode with **zxing-cpp** (Apache-2.0, pip `zxing-cpp`) or **pyzbar** (MIT, needs libzbar); parse with **vobject**. If a vCard QR is present, prefer it over OCR (near-100% accuracy). *Not yet implemented in the prototype — top next step.*
- Export: vCard 3.0 is the most interoperable (Outlook, Google, iOS). Prototype exports vCard 3.0 + CSV.

## 7. Recommended stack
**Pilot (now, CPU-only box):** FastAPI + Tesseract 5 + rule parser (regex + phonenumbers) + SQLite + human approval queue. Everything local; no member data leaves the machine.
**Phase 2:** add QR/vCard decoding (zxing-cpp) → swap/ensemble OCR with **PaddleOCR** → `usaddress`/libpostal. Optional **Qwen2.5-VL-3B via Ollama** on a modest GPU or Apple-Silicon Mac for hard cards (logo-heavy, multi-column), with OCR cross-validation.
**Tradeoffs:** Tesseract = fastest/smallest, weakest on real photos. PaddleOCR = best accuracy/CPU ratio. VLM = best layout understanding, slow on CPU, hallucination risk. Cloud OCR (Google/Azure/AWS) would be most accurate but sends member PII to third parties — avoid unless GAC accepts that.
**Privacy:** process on GAC-controlled hardware, store images only until approval (add retention purge), CRM writes only after data-team approval.
