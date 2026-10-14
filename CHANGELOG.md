# Changelog

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
