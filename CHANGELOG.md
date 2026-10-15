# Changelog

## Unreleased: accuracy on real cards
- **`bench/extract_eval_set.py`** turns the pilot's approved cards into a labelled test set for `bench/eval_bench.py` and prints, per field, how often reviewers had to fix what the scan read and whether the confidence score warned about it. It reads the database only, keeps cards approved unchanged (otherwise the set holds only failures), tags bulk-approved cards as weaker labels, and writes to the same folder as "Keep corrected cards as test examples", so photo retention and delete-on-request also clean its copies.

## Unreleased: audit fixes, part 3 (structure)
From the code audit in `docs/AUDIT-2026-10-15.md` (P2 items). Mostly invisible to users; it makes the code easier and safer to change.

- **A save is all-or-nothing.** If something fails half-way through saving a card (an approve with a merge, a bulk action, an AI accept), nothing of it is kept, instead of half of it.
- **`/api/scan`** (scripts on the scanner computer) records cards like the Scan page does, so the duplicate-photo check sees them.
- Starting the app in a script or test no longer starts the AI helper or wipes the public demo; that happens only when the scanner is actually served.
- **Code layout:**
  - `app/ui.py` (3,700 lines) is split into `pages`, `privacy`, `exporting`, `audit_log` and `admin_files`. `ui.<name>` still works.
  - `ui.js` (1,500 lines) is split into ES modules under `app/static/ui/{core,ui,views}`, with no build step.
  - Dead code removed; `tests/unit/README.md` maps features to test files.

## Unreleased: audit fixes, part 2 (reliability, accuracy, speed, release)
From the code audit in `docs/AUDIT-2026-10-15.md` (P1 items).

### Reading cards
- **"John Smith, CEO"** keeps CEO as the title; **"Smith, John"** is read as John Smith; names with **van / de / la** and compound surnames ("van der Meer", "de la Cruz") stay whole.
- **"P 330… / F 330…"** on one line: the second number is the fax, not a second work phone.
- A **"3rd Floor" / "Suite" line** between the street and the city stays in the address.
- **Two people on one card** ("John & Jane Smith") are flagged for review instead of producing a confident wrong name.
- Email addresses with a label glued on ("tom@hillco.com.tel") are cleaned up; newer web endings (.tech, .legal, .law …) are recognised.
- **QR codes:** escaped commas, folded lines and the address parts of a vCard are read correctly.
- The **AI double-check** now looks at the cropped card (sharper text), its suggestions for phone types are no longer lost, and the warnings shown after it describe the AI's values.

### Speed
- **The review list is much faster with a real MC Trade contacts file:** about 2 seconds instead of 16-19 seconds for a 200-card batch against 10,000 contacts. The results are the same.
- "All batches" in the review queue loads 200 cards at a time ("Load more").
- The upload list stays fast with hundreds of photos (small thumbnails, only changed rows redrawn).

### Reliability
- **Undo** always undoes the right change, even when two people save at the same moment.
- **Backups:** a failed backup is retried after 10 minutes (it used to wait for the next night) and shown in Admin → Settings, with the date of the last good backup.
- **Restoring an older backup no longer brings back cards deleted on request**; they are deleted again when the scanner starts.
- Uploading a new MC Trade template or contacts file keeps the old one until the new one is fully saved.
- After a crash, an upload whose card had already been saved is shown as done (it used to be blamed on the file).
- PDF and photo reading has a memory limit on Windows and Mac too (it was Linux-only).
- Signing in: wrong passwords typed on another computer no longer lock you out. Sessions end 7 days after sign-in at the latest.
- Two people can no longer get the same initials (a later account gets a number, e.g. AB2); this kept their batches and uploads apart.

### Scan, review and export pages
- **Session expired while uploading:** the photos wait instead of failing. Sign in again in a new tab and they continue. Failed photos get a **Retry** button.
- **Desktop app:** the export message lists what was actually saved, and which files were cancelled in the Save dialog.
- Desktop folder pick includes PDFs, skips files over 25 MB and stops at 500 files / 300 MB.
- The "Export it" button and the "reload the page" link work again (they were blocked by the security policy).
- Screen readers are no longer flooded by the AI progress line; the Undo toast stays while you're in it.
- Phone: the camera turns off when the page is hidden; "Use camera app (sharper photo)" is always offered; the phone page always loads its newest code.

### Security
- vCard exports can't be broken by a line break hidden in a phone, email or website (a phone with a line break can't be approved).
- Public demo: no phone pairing, no cancelling other visitors' uploads, and the card cap counts uploads still being read; a wipe also clears uploads in progress.
- The local AI helper requires a key (and keeps fewer copies of what it read).

### Install and release
- CI tests on Windows, macOS and Linux, lints, checks dependencies for known vulnerabilities, and fails when recognition accuracy drops.
- The dependency lock file pins every package; Docker and the start scripts use it.
- Releases: read-only permissions except for publishing, the tag must match `VERSION`, notes come from this changelog, signing runs when certificates are configured, and the Windows upgrade removes old program files.

## Unreleased: audit fixes, part 1 (data safety)
From the code audit in `docs/AUDIT-2026-10-15.md` (P0 items).

### Your data
- **Changes are no longer silently undone.** A background job (AI check, export, retention) could write back an old copy of a card's settings over a reviewer's change (for example the MC Trade "create new / update existing" choice). Each writer now saves only what it changed.
- **Exports never mark cards they didn't contain.** If someone edits or approves a card while an export is being built, or between the sign-off and the export, the export is refused ("check the sign-off again") instead of marking the changed card as exported without its latest details. The export number shown after an export is always that export's own.
- **Card numbers are never reused** after a card is permanently deleted.
- **Permanent delete** is now one step: the card, its history clean-up and the audit-log entry are saved together, and both sides' photos and all their thumbnails are removed.
- **The AI double-check keeps running** after a database hiccup (it used to stop until the scanner was restarted).
- The database waits for a busy moment to pass instead of failing ("database is locked") and lets reviewers read while someone saves.

### Admin
- **A refused settings or user change saves nothing.** Before, a bad value could leave the earlier settings saved, and changing your own password together with something refused still reset the password.

### Backups
- **Desktop app: backups are kept next to the data folder** (`GAC Card Scanner Backups`), not inside the installed program, where an upgrade deleted them. **Backups made by v0.3 or older desktop builds are inside the program folder**: copy any you want to keep before upgrading.
- Backups no longer include the 3 GB AI helper, the app window's browser profile or log files.
- Docker: backups go to their own `gac-backups` volume (they failed before: the folder wasn't writable).
- A photo deleted while a backup runs no longer makes the whole backup fail.

### Security
- First-time setup, and the open scan API for scripts on the same computer, now refuse requests that come through another website's name (DNS rebinding). Open the scanner by address (`localhost`, an IP address or this computer's name); a reverse proxy or fixed office name goes in `GAC_ALLOWED_HOSTS`.
- Upload size limits count the bytes actually received, not the size a request claims.
- Only plain photo formats are opened inside the web server process; oversized pictures are refused before they are decoded.

### Scan page
- Starting a new batch while photos of the previous batch are still uploading is refused with a message. Before, the waiting photos were filed under the new batch.

### Developers
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
