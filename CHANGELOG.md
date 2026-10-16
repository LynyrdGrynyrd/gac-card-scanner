# Changelog

## v0.4.3 (2026-10-16)

### Safer undo, sign-out and duplicates (from the v0.4.2 tester reports)
- **Undo** is refused once the card was exported after that action ("Change it by hand; it is then marked for re-export"). After Undo a short "Undone: …" message shows.
- **Idle sign-out on the server:** a session ends after the idle time even when the tab was closed. Background polling doesn't count as activity. The "Still there?" question names a card with unsaved changes and keeps them as your draft.
- **Approve after Different** still asks once when the person was exported before. History now says "approved (marked different from N cards)".
- **May already be in MC Trade** is treated the same everywhere: To check on the page, a "Needs review" list in the Preview, NEEDS REVIEW in the dry run, and a note in the CSV Check column. The batch list's "ready" count matches the check on first load.
- **"…example" email domains** pass only when the card's website has the same domain (theperfectexample.com with its website passes; goodyearheightsfamexample.com is blocked).
- **Same (merge):** the fuller address, company or department wins, and you can pick which value to keep per field. A value that isn't kept goes into the note, never dropped silently.
- **Blocked cards:** any staff member may Confirm a red box with a reason, which is logged. No more "Ask an admin".
- **Smaller fixes:** no uploads into another person's batch (checked by the server); batch owners matched by user id, not initials; the duplicate headline has no counts; one "AI check not finished" message, and "Wait for the AI" really waits; "Reconnecting" only on a real disconnect; no "changed" tag when nothing changed; the READ-ME "More notes" count no longer double counts; Scan shows the stored batch name; "Not you?" says it signs you out; Same isn't offered toward your own older batches unless the match is strong; reviewers see only their own export history; the signed-out help page has no app menu.

## v0.4.2 (2026-10-16)

### Who may export, who is signed in (from the v0.4.1 tester reports)
- **Export rights are enforced by the server:** a reviewer can export only their own batch. Other people's batches and **All batches** are for admins. The guides say the same.
- **You are: NAME** shows on every screen, with **Not you?**. After 30 minutes with no clicks the app signs out (never while photos are uploading). Admins can change the time with `GAC_IDLE_MINUTES` (0 = off).
- **Approve after Different** still asks once when the person was exported before or may already be in MC Trade. "Different" now removes the "check for a double import" note from the CSV and READ-ME. The Preview marks rows that may already be in MC Trade.
- **One count everywhere:** the Export page, the batch list ("ready"), the Ready-to-save sheet and the READ-ME use the same list. The READ-ME's "Other warnings" line is now "More notes: N other cards have a note in the CSV Check column".
- **Batch names** carry the date and your initials ("After Hours · Oct 16 · RR"); no more "(2) (1)". The batch name field is on the Scan page, not under More. A saved batch from another day or another person is never reused.
- **Someone else's batch** (admins): a clear warning line on the page and a named question before export.
- **Checks:** theperfectexample.com and similar whole-word names are no longer blocked.
- **Duplicates:** shorter text ("Same person? #520 and 24 more", no exported count), MC Trade is one line in the same box, other people's look-alikes say "Looks like #N", the box turns plain once answered, "Blocked" is in the legend, and the nested More in Ready to save is gone.
- **Undo** shows on screen right after Approve.
- **Help** opens at /help even when signed out. **/health** names the public release commit. The reviewer guide cover no longer promises an AI section.
- **Merges:** replaying a merge is refused (no doubled note); cards with no scan record are not treated as "same scanner".
- **Upload:** a photo can no longer sit on "Waiting to upload" forever (send errors offer Retry, a stuck request times out, and a photo lost to a page reload says so).

## v0.4.1 (2026-10-16)

### Safer review (from the v0.4.0 tester reports)
- **Enter:** a held key no longer approves card after card. There's a short pause after the next card loads. Enter never approves while you're typing in a field ("Esc, then Enter to approve") or while "Same person?" is unanswered. "Exported before" now defaults to **Cancel**.
- **Same person?** compares the best match (same scanner and batch first, then name, email and phone). The server refuses to merge unrelated cards or another reviewer's cards.
- **Phones:** look-alike letters (O, I, l) next to digits are read as digits. Digits are never dropped without a mark, and numbers that look off are flagged. "changed" now shows for every automatic change, including website and company.
- **Counts:** "To check", "Ready to save" and the export preview now agree, and "To check" lists the card numbers.
- **Merge:** the Same preview matches the result, Different carries into the export, a merged card no longer shows a red box, and each duplicate is asked about only once.
- **Reject** asks first and keeps an unsaved note.
- **Export:** your current batch is selected by default, the screen names the batch owner, and batch names stay unique.
- **Checks:** bestexample.com is no longer blocked; the "Morg4n" warning is back; Save and Reject are back on the bar; Confirm buttons stay after Save; a company that only looks misread can be confirmed.
- **Layout:** the side-by-side panel fits at 1280 px, the wrapping and spacing bugs are fixed, the preview table is roomier, the Same box and the links have names for screen readers, and tap targets are 44 px. Zoom shows nothing for a field that has no box.
- **Docs:** the guides, in-app help and demo video were remade from this version. They now say the same thing about Enter, Same/Different and who may export.

## v0.4.0 (2026-10-16)

### Calmer, faster review (Apple-style screens)
- **Tap a field to zoom:** clicking or tabbing into a field zooms the photo to where it was read. Esc shows the whole photo. When the place isn't known, the whole photo stays.
- **Review card:** photo left, fields right, one big **Approve** and **Skip**. Save, Reject, Delete, the AI check, the text read and the history are under **More**. Approve stays in view on long cards.
- **Shaky fields** get a soft yellow highlight and a short "Check" tag instead of a banner. The rules that block approval are unchanged.
- **Keys:** Enter approves, Tab goes to the next field, ←/→ change card, Ctrl+Z / ⌘Z undoes. Enter never approves while a dialog is open, while there are unsaved edits, or while an error shows.
- **Export:** one Export button (format under Format), then a "Ready to save" sheet with New contacts / Updated / To check, counted by the same server check as the export.
- **Scan:** one big drop area and one Scan button; batch name, folder, phone and the AI option are under More.
- **Duplicates:** "Same person?" with both cards side by side, differences highlighted, and Same / Different.
- **Light and dark** follow the computer's setting; the ◐ button in the header switches. Colours checked for 4.5:1 contrast.
- **Changed mark:** fields the automatic clean-up or the AI check changed show "changed" (hover to see what was read). No undo yet.
- Gentle motion between cards and for dialogs; none when the computer asks for reduced motion.

## v0.3.2 (2026-10-15)

### Plainer screens (from the newcomer test of 0.3.1)
- **Duplicate / MC Trade box:** one line ("Matches #9 Maria Delgado and 49 others", "Maybe in MC Trade: Maria Delgado (same email, same phone)"), details behind More, and only one **Different person** button on the card. "Merge", "+49", square brackets and "Profile ID" are gone from the box.
- **Export sign-off:** Format, Cards and Batch on separate lines; "new contacts" instead of "new-profile rows"; "may already be in MC Trade (test list)".
- **Fix:** right after an export the page said "Nothing to export yet. Approve some cards first."; it now says "All cards in this batch are exported."
- The "test 2 rows first" advice shows only when there are more than 2 rows. Export history rows are short: Excel · batch, then Download · READ-ME · Extra details.
- **READ-ME:** shorter and plain. Empty and zero lines are left out, each card gets one warning line, the columns note is said once, and the phone format moved to the Admin guide.
- **Labels:** sign-in says just "Card Scanner"; "Skip AI" is now **More → Skip the AI double-check**; "Reading method" is "Scan quality"; "Read quality" is "Scan"; the queue badge says "4 waiting in your batches"; the review page shows the shortcut keys (A, R, J, K, U) without opening anything.

## v0.3.1 (2026-10-15)

### Accuracy on real cards, reading fixes, more tests
#### Reading cards
- An address line with its label in front (**"Visitors and deliveries: 47 N Main St"**, **"Mailing address: PO Box 12"**) keeps its street, and the label no longer ends up in the address. A visitors/deliveries address on a card that also has a main address goes to *Other address*; when it is the card's only address, it is the address.
- A street number with a misread letter (**"25o8 Jonathan Terrace Ave"**) no longer loses the whole street line; **"P.0. Box"** is read as "P.O. Box".
- A phone number on the same line as an email address (**"E: mary@jones.com | T: 330-555-0102"**) is no longer dropped.
- Malformed requests to the scanner's API (wrong value types, ids too large) get a clear error instead of a server error.

#### Accuracy and testing
- **`bench/extract_eval_set.py`** turns the pilot's approved cards into a labelled test set for `bench/eval_bench.py` and prints, per field, how often reviewers had to fix what the scan read and whether the confidence score warned about it. It reads the database only, keeps cards approved unchanged (otherwise the set holds only failures), tags bulk-approved cards as weaker labels, and writes to the same folder as "Keep corrected cards as test examples", so photo retention and delete-on-request also clean its copies.
- New test layers: property tests for the card reader (Hypothesis), fuzzing of every API endpoint (Schemathesis) and browser tests of scan → review → approve → export (Playwright), all run by CI. `CLAUDE.md` describes the project's rules for AI coding agents.

### Audit fixes, part 3 (structure)
From the code audit in `docs/AUDIT-2026-10-15.md` (P2 items). Mostly invisible to users; it makes the code easier and safer to change.

- **A save is all-or-nothing.** If something fails half-way through saving a card (an approve with a merge, a bulk action, an AI accept), nothing of it is kept, instead of half of it.
- **`/api/scan`** (scripts on the scanner computer) records cards like the Scan page does, so the duplicate-photo check sees them.
- Starting the app in a script or test no longer starts the AI helper or wipes the public demo; that happens only when the scanner is actually served.
- **Code layout:**
  - `app/ui.py` (3,700 lines) is split into `pages`, `privacy`, `exporting`, `audit_log` and `admin_files`. `ui.<name>` still works.
  - `ui.js` (1,500 lines) is split into ES modules under `app/static/ui/{core,ui,views}`, with no build step.
  - Dead code removed; `tests/unit/README.md` maps features to test files.

### Audit fixes, part 2 (reliability, accuracy, speed, release)
From the code audit in `docs/AUDIT-2026-10-15.md` (P1 items).

#### Reading cards
- **"John Smith, CEO"** keeps CEO as the title; **"Smith, John"** is read as John Smith; names with **van / de / la** and compound surnames ("van der Meer", "de la Cruz") stay whole.
- **"P 330… / F 330…"** on one line: the second number is the fax, not a second work phone.
- A **"3rd Floor" / "Suite" line** between the street and the city stays in the address.
- **Two people on one card** ("John & Jane Smith") are flagged for review instead of producing a confident wrong name.
- Email addresses with a label glued on ("tom@hillco.com.tel") are cleaned up; newer web endings (.tech, .legal, .law …) are recognised.
- **QR codes:** escaped commas, folded lines and the address parts of a vCard are read correctly.
- The **AI double-check** now looks at the cropped card (sharper text), its suggestions for phone types are no longer lost, and the warnings shown after it describe the AI's values.

#### Speed
- **The review list is much faster with a real MC Trade contacts file:** about 2 seconds instead of 16-19 seconds for a 200-card batch against 10,000 contacts. The results are the same.
- "All batches" in the review queue loads 200 cards at a time ("Load more").
- The upload list stays fast with hundreds of photos (small thumbnails, only changed rows redrawn).

#### Reliability
- **Undo** always undoes the right change, even when two people save at the same moment.
- **Backups:** a failed backup is retried after 10 minutes (it used to wait for the next night) and shown in Admin → Settings, with the date of the last good backup.
- **Restoring an older backup no longer brings back cards deleted on request**; they are deleted again when the scanner starts.
- Uploading a new MC Trade template or contacts file keeps the old one until the new one is fully saved.
- After a crash, an upload whose card had already been saved is shown as done (it used to be blamed on the file).
- PDF and photo reading has a memory limit on Windows and Mac too (it was Linux-only).
- Signing in: wrong passwords typed on another computer no longer lock you out. Sessions end 7 days after sign-in at the latest.
- Two people can no longer get the same initials (a later account gets a number, e.g. AB2); this kept their batches and uploads apart.

#### Scan, review and export pages
- **Session expired while uploading:** the photos wait instead of failing. Sign in again in a new tab and they continue. Failed photos get a **Retry** button.
- **Desktop app:** the export message lists what was actually saved, and which files were cancelled in the Save dialog.
- Desktop folder pick includes PDFs, skips files over 25 MB and stops at 500 files / 300 MB.
- The "Export it" button and the "reload the page" link work again (they were blocked by the security policy).
- Screen readers are no longer flooded by the AI progress line; the Undo toast stays while you're in it.
- Phone: the camera turns off when the page is hidden; "Use camera app (sharper photo)" is always offered; the phone page always loads its newest code.

#### Security
- vCard exports can't be broken by a line break hidden in a phone, email or website (a phone with a line break can't be approved).
- Public demo: no phone pairing, no cancelling other visitors' uploads, and the card cap counts uploads still being read; a wipe also clears uploads in progress.
- The local AI helper requires a key (and keeps fewer copies of what it read).

#### Install and release
- CI tests on Windows, macOS and Linux, lints, checks dependencies for known vulnerabilities, and fails when recognition accuracy drops.
- The dependency lock file pins every package; Docker and the start scripts use it.
- Releases: read-only permissions except for publishing, the tag must match `VERSION`, notes come from this changelog, signing runs when certificates are configured, and the Windows upgrade removes old program files.

### Audit fixes, part 1 (data safety)
From the code audit in `docs/AUDIT-2026-10-15.md` (P0 items).

#### Your data
- **Changes are no longer silently undone.** A background job (AI check, export, retention) could write back an old copy of a card's settings over a reviewer's change (for example the MC Trade "create new / update existing" choice). Each writer now saves only what it changed.
- **Exports never mark cards they didn't contain.** If someone edits or approves a card while an export is being built, or between the sign-off and the export, the export is refused ("check the sign-off again") instead of marking the changed card as exported without its latest details. The export number shown after an export is always that export's own.
- **Card numbers are never reused** after a card is permanently deleted.
- **Permanent delete** is now one step: the card, its history clean-up and the audit-log entry are saved together, and both sides' photos and all their thumbnails are removed.
- **The AI double-check keeps running** after a database hiccup (it used to stop until the scanner was restarted).
- The database waits for a busy moment to pass instead of failing ("database is locked") and lets reviewers read while someone saves.

#### Admin
- **A refused settings or user change saves nothing.** Before, a bad value could leave the earlier settings saved, and changing your own password together with something refused still reset the password.

#### Backups
- **Desktop app: backups are kept next to the data folder** (`GAC Card Scanner Backups`), not inside the installed program, where an upgrade deleted them. **Backups made by v0.3 or older desktop builds are inside the program folder**: copy any you want to keep before upgrading.
- Backups no longer include the 3 GB AI helper, the app window's browser profile or log files.
- Docker: backups go to their own `gac-backups` volume (they failed before: the folder wasn't writable).
- A photo deleted while a backup runs no longer makes the whole backup fail.

#### Security
- First-time setup, and the open scan API for scripts on the same computer, now refuse requests that come through another website's name (DNS rebinding). Open the scanner by address (`localhost`, an IP address or this computer's name); a reverse proxy or fixed office name goes in `GAC_ALLOWED_HOSTS`.
- Upload size limits count the bytes actually received, not the size a request claims.
- Only plain photo formats are opened inside the web server process; oversized pictures are refused before they are decoded.

#### Scan page
- Starting a new batch while photos of the previous batch are still uploading is refused with a message. Before, the waiting photos were filed under the new batch.

#### Developers
- The unit tests write only to a temporary folder (no more "run from a copy").

## v0.3.0 (2026-10-15)
Brings the desktop app up to date with the pilot's review rounds 18–24.

### New inputs
- **PDF and iPhone HEIC/HEIF photos** can be scanned (each PDF page becomes a card). The desktop builds now bundle pypdfium2 and pillow-heif.
- **Cancel** a long scan: "Stopped. N kept, M not scanned"; nothing arrives late.
- **Skip AI** per scan, for busy events.

### Review
- Clear misreads **block approval** until fixed: a digit in a name, a phone with a letter or without an area code, a garbled company, an email or website with a lost dot, a house number with a letter in it.
- A value that really is printed that way can be **confirmed with a reason** (email, website and address by an admin). One audit row per confirmation.
- Real brand names such as LinkedIn, HubSpot, QuickBooks and E*Trade are no longer blocked.
- Each warning is shown once; plainer wording throughout.

### Batches and export
- The Review queue and Export open on **your newest batch**, and stay on it after an export.
- Exporting **someone else's batch** (or all batches) asks first and names the owner.
- The READ-ME is plain: totals first, "Check" lines, no internal jargon; "1 row" for a one-row file.

### Help
- Help is split into **Reviewer Start Here** and the **Admin & MC Trade Guide** (in-app pages and printable PDFs).

## v0.2.1 (2026-10-14)
Hotfix for the desktop app (Windows, Mac).

- **Exports save again in the desktop app.** In v0.2.0 the app's security policy blocked the desktop helper script, so the Excel/CSV/READ-ME files of an export (and other downloads) never reached your computer. They now open a Save dialog, one file after another, each starting in the folder you picked last. The app also no longer drops downloads it can't route through the Save dialog.
- **If you exported with v0.2.0**, the cards were marked exported and the scanner kept its own copy: your files are in the app data folder (File → Open data folder) under `exports`, and on the Export page under past exports.
- **Help PDF links work in the desktop app.** The printable guide opens in your normal browser.
- **The version line shows the build's commit** instead of "version 0.2.0 (unknown)".
- The example phone number in the docs and tests is now the made-up `330-555-0170 x4271`.
- Public demo mode: the review page no longer reloads itself over and over.

## v0.2.0 (2026-10-14)
Brings the desktop app up to date with the pilot's review rounds 6–17. Highlights from rounds 15–17:

### Safer admin changes and exports
- **Versions are required for admin changes.** Template upload/revert/remove, contacts-file upload/remove and settings saves must send the version they were based on. A missing version gets `428 version_required`, an outdated one `409 stale_admin`; nothing is changed and the refusal is written to the audit log.
- **Export sign-off checks.** The Export page sends back the template, contacts and card versions it showed. A real CSV / Excel / vCard export without them gets `428 version_required`; if anything changed since the sign-off it gets `409 stale_review` naming what changed. Nothing is exported or marked as exported. Previews and the dry run need no versions.
- Refused attempts (stale versions, busy export, stale review) appear in the audit log as "refused …" rows.

### Review screen fixes
- Pagination: the archived filter is applied before paging (correct `X-Total`), invalid `limit` values get `422 bad_limit`, `X-Limit` reports the limit used.
- An in-batch look-alike stays visible after a bulk reject ("May be the same person as card #N (rejected, this batch)").
- Approve checks the whole form first and lists every problem; duplicate reasons are shown once.
- The approve dialog no longer closes by itself while an AI check is running; counter and Prev/Next/J/K use the batch's real pending list; toast, save and navigation fixes.
- Reviewer pages no longer contain admin-only markup; the audit log shows the reviewer's username.

### Export content
- Phone extensions are exported as `330-555-0170 x4271`.
- International phone numbers are kept in the MC Trade Excel.
- Exported rows whose website could not be confirmed carry a **CHECK WEBSITE** warning.

### Also since v0.1.0
- Real-card accuracy rules (departments, international phones, look-alike email/O↔0, postfix clean-ups).
- Phone mode (scan with a phone on the same Wi-Fi), optional in-app update check against GitHub Releases, AI queue indicator.
- MC Trade template and contacts upload in Admin → Settings, backups, help guide.
- Desktop builds now bundle `VERSION` and the MC Trade column map.

## v0.1.0 (2026-10-14)
First public release: Windows installer and macOS disk images.
