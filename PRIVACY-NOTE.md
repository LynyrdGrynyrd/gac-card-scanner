# Card Scanner: privacy note for the Greater Akron Chamber
*Plain-English summary for the pilot. It describes how the software works, not a legal policy. Please review it with GAC leadership before using the scanner more widely.*

## What it collects
When staff scan a business card, the scanner keeps:
- a **photo of the card**, and
- the **details printed on it**: name, job title, company, email, phone, website, address, plus any note a reviewer adds.

It also records which staff member scanned, edited, approved or exported each card, and when (the audit log). It records staff sign-ins, including the computer's network address.

## Where it lives
Everything stays **on the one office computer that runs the scanner**, in its `data` folder. Nothing goes to the internet: no cloud service, no outside AI company, and nothing is sent to MC Trade automatically. The optional "AI double-check" runs on the same computer.

## Who can see it
Only Chamber staff with their own scanner login:
- **Reviewers** scan, check and approve cards, and export approved cards. They can see every card in the review queue (all batches, archived ones too), because they review each other's batches.
- **Admins** can also manage logins, change the privacy settings, archive batches, export unreviewed cards, read the audit log, and permanently delete a card.

Each person should use their own login and their own browser (or browser profile). The scanner warns you if your browser was signed in as someone else.

## How long it is kept
| What | How long |
|---|---|
| Card photos (and small cached thumbnails of them in `data/thumbs`, used by the review queue) | Deleted automatically after **30 days** (admins can change this); thumbnails are deleted together with the photo |
| Copies of exported files kept for re-download | Deleted after **30 days** |
| "Undo" copies of card details | Cleared after **2 days** |
| Typed contact details | Kept, because they become part of the Chamber's contact records. Old batches can be archived (hidden), or a card can be **deleted permanently** |
| Audit log and sign-in records | Kept for accountability. After a removal request the card's audit rows stay (who, what action, when, card number) but the personal details in them are removed |
| Test examples (`bench/corrections`) | **Off by default.** If an admin turns on "Keep corrected cards as test examples", a copy of the photo and approved details of each card a person corrected is saved there to measure accuracy. Those photos follow the card-photo period (30 days), and are deleted with the card on a removal request. |

## Exports
Exported spreadsheets go to the staff member's **Downloads** folder. Treat them like any member list: don't email them outside the Chamber, and **delete them once they are imported into MC Trade**. Rows that were "approved anyway" are marked so they can be checked first.

## If someone asks to be removed
1. An admin finds the card in the scanner (search by name) and chooses **Delete permanently**. This erases the photo, the details, any test-example copy and any stored export copies. The card's audit rows are kept for accountability (who scanned, approved or exported it and when) with the personal details (names, contact details, file names, notes) removed.
2. Also remove the person from **MC Trade**, and delete any exported spreadsheets that contain them.
3. Note the request in your usual records.

## Backups
If the scanner's `data` folder is backed up, the backup contains card photos and details too. Keep backups for no longer than the photo retention period (30 days), and store them as securely as the office computer.

## Good practice
- Turn on disk encryption on the scanner computer (BitLocker on Windows, FileVault on Mac).
- Use the phone-access (HTTPS) mode only on the office Wi-Fi, not on public networks.
- Remove logins for staff who leave (Admin → Reviewers → Deactivate).
