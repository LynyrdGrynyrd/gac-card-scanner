# Card Scanner: Data team guide
*Greater Akron Chamber · internal pilot*

This guide covers everything the data team does day to day. For first-time installation see **QUICKSTART.md**.

## Contents
1. Accounts and roles
2. Scanning cards
3. The review queue
4. Reviewing a card
5. Duplicates
6. Undo and changing decisions
7. Exporting to MC Trade
8. Privacy, photo deletion and the audit log
9. Phones
10. Troubleshooting

---

## 1. Accounts and roles
| Role | Can do |
|---|---|
| **Reviewer** | Scan, review, approve/reject, export approved cards (all, or one batch/event), add the back of a card, undo their own actions |
| **Admin** | Everything a reviewer can, plus add/deactivate reviewers, reset passwords, change privacy settings, read the audit log, archive batches, export pending/all cards, **delete a card permanently** (removal requests) and "Clear all test data" |

- Everyone signs in with their **own** account. Your initials are recorded on every card you approve or reject and appear in exports.
- Passwords need at least 10 characters. After 5 wrong attempts, sign-in pauses for 5 minutes.
- You stay signed in for 12 hours of inactivity. Use **Sign out** on shared computers.
- **Admin → Reviewers:** add a person (they get a temporary password and must change it), reset a password, deactivate someone who left (their past work stays in the audit log), or change a role.

![Reviewers](shots/16_admin_reviewers.png)

## 2. Scanning cards
- **One card per photo.** Lay the card flat on a dark, plain surface, fill the frame, and avoid glare.
- Name each **batch** after the event. Batches let you review, export and archive one event at a time.
- Drag a folder or select many photos at once; cards are read one after another: about 2–5 seconds each when you're the only one scanning, longer (5–30 s) when others are scanning at the same time. The screen shows the real time per card for your batch. You can review earlier cards while later ones are being read.
- **Not added** reasons: *Not a photo*, *File is empty*, *too small*, *looks blank*, or *already scanned* (the same photo was uploaded before; there's a link to that card and a **Scan it anyway** option).
- If a card has a **QR code** with contact details, the scanner reads it automatically. Those fields show **from QR code** and are almost always correct.

## 3. The review queue
- Tabs: **Pending / Approved / Rejected / All** (with counts).
- Filters: **Batch**, **Needs attention only**, **Possible duplicates**, **Not yet exported**, and a search box (name, company, email, file name, or **#12** for card 12).
- "Needs attention" lists the reasons in words: *Name is required*, *Hard to read: Company*, *May be the same person as card #4*, *May already be in MC Trade*.
- Your filters stay when you refresh the page.
- **Bulk approve/reject:** tick cards (or the box at the top for all shown), then **Approve selected**. Cards that still need fixing or have a duplicate question are **skipped** and listed, so bulk approve never lets a problem through.

![Queue](shots/04_queue.png)

## 4. Reviewing a card
- The photo is on the left (click to enlarge), editable fields on the right.
- Field badges: **from QR code** (green), **read from text** (blue), **edited by XX** (purple).
- **Approve** checks the card first: a first name, a valid email, phone numbers with enough digits, and at least an email or a phone. If something is wrong, the field turns red and all problems are listed at once. A **blank first name**, an email without "@" and a phone with fewer than 7 digits must be fixed; for the other problems you can fix them (recommended) or click **Approve anyway** and type a reason; the reason is saved and the row is flagged red in the export.
- Editing an **approved** card (or merging another card into it) checks it again. If it no longer passes, it goes back to **pending**.
- **History** (under the photo) shows who scanned, edited, approved, exported or undid what, and when.
- Shortcuts (when not typing in a field): **A** approve · **R** reject · **J** next · **K** previous · **U** undo · **Esc** leaves a field.

![Validation](shots/06_validation_block.png)

## 5. Duplicates
Two kinds of possible duplicate, both with plain choices:
1. **Same person as another scanned card** (for example someone gave you a card at two events):
   - *Same person: add any new details to #X and drop this card*. This merges any extra email or phone into the other card and rejects this one as a duplicate.
   - *Different person from #N: keep both* (one choice per listed card). A card with the **same photo**, or the same email/phone **in the same batch**, is a duplicate scan: it can't be kept as a different person, so merge or reject one.
2. **May already be in MC Trade**:
   - *Same person: update their existing MC Trade contact*, or
   - *Different person: add as new contact*.
   The choice is written in the export's **MCTradeAction** column so whoever imports knows what to do.

Exports are **blocked** while two cards in the same export look like the same person, so a person can't be imported twice.

> Until MemberClicks API access is set up, "already in MC Trade" is checked against a **sample** list (data/existing_contacts.csv). Replace it with a real export of MC Trade contacts (same columns) for useful matches.

## 6. Undo and changing decisions
- **Undo** (button in the top bar, the *Undo* link in the confirmation message, or **U**) reverses your most recent action: an approval, rejection, edit, merge, bulk action or archive. Press it again to go further back. It works for your own actions from the last 24 hours.
- Changing an already approved/rejected card asks you to confirm and keeps the earlier decision in the history.

## 7. Exporting to MC Trade
1. **Export** page → choose **Approved, not yet exported** (recommended). The page shows how many cards will be included.
2. Pick your event in **Which batch (event)?**. With **All batches**, duplicates from *anyone's* batch block the export. Then click **MC Trade import (Excel)** → confirm. Three or four files are saved to **Downloads**, named after the batch, e.g. `GAC-MCTrade-new-Spring-Expo-2026-10-15_1430.xlsx`. The **.xlsx import file is the file you import into MC Trade**:
   - the **.xlsx import file**: exactly the columns of MC Trade's import template (one sheet, no extra tabs or columns), **one row per person**. Phones are written as `330-555-0181` and addresses are split into street, city, state and zip. Admins can change the phone style (or switch to `+13305550181`) and the **AffCode1** affiliation code (default `CardScan-Pilot`) under Admin → Settings. To match GAC's real template exactly, an admin uploads it under **Admin → Settings → Upload GAC's MC Trade template** (saved as `data/mctrade_template.xlsx`); its header row is then used as is.
   - **…-extra-columns.csv**: everything that isn't in the template (second email, credentials, department, notes, reviewer, batch, *NeedsAttention*) plus every card that was **left out** and why ("FIX FIRST", "same person as card #…").
   - **…-READ-ME.txt**: what to check before importing.
   - **GAC-MCTrade-…-UPDATES.xlsx** (only when some cards update existing MC Trade profiles): one row per Profile ID, a **separate** import. A card is never in both files; cards with an uncertain Profile ID, or a "create new" person who already exists, are left out as NEEDS REVIEW.
   - Before importing, click **Check against MC Trade (dry run)** on the Export page: a match report (UPDATE / CREATE / NEEDS REVIEW), offline, no terminal needed.
3. Import the .xlsx in MC Trade (Admin → Import Profiles), trying two rows first. Then **delete the files from Downloads**.

**Formula guard (CSV only):** a cell gets a leading `'` only when a spreadsheet would run it as a formula: it starts with `=`, `@`, a tab or a carriage return, or with `+`/`-` followed by something that is not a plain number or phone number. `+1 330-555-0181` and `-5` stay as they are; `+SUM(1)` becomes `'+SUM(1)`. The Excel file needs no prefix because every cell is stored as text. CSV files start with a UTF-8 BOM so Excel shows accents correctly.

Also available: **Spreadsheet (CSV)**, with reviewer columns, and **Contacts (vCard)** for Outlook or phones.

**Export history** (bottom of the Export page) lists every export (when, who, how many cards), and you can download a copy again while it's kept. After an export, those cards no longer appear under "not yet exported"; the queue's **Not yet exported** filter shows the same thing.

![Export history](shots/12_export_done.png)

## 8. Privacy, photo deletion and the audit log
- Read the **Privacy** note (link at the bottom of every page).
- **Admin → Privacy & retention:** card photos are deleted automatically after **30 days** by default (you can change this). Stored export copies follow their own setting. The typed contact details stay. **Delete old photos now** runs the cleanup immediately; it also runs every hour.
- **Archive** a batch (admins: Review queue → choose the batch → *Archive this batch*) to hide test or finished batches. Archived cards are hidden, not deleted; *Show archived cards* brings them back. Admins also have **Clear all test data…**.
- **Admin → Audit log:** every sign-in, failed sign-in, decision, edit, merge, export, re-download, undo, setting change (only what changed, e.g. "AI double-check: on → off"), photo deletion and permanent deletion, with who and when. Re-downloads and deletions carry the card numbers, so searching `#17` finds them. After a removal request the card's rows stay, with the personal details removed. Search it, or **Download as CSV**.
- **Keep corrected cards as test examples** is **off** by default; turning it on keeps a copy of corrected card photos in bench/corrections (see the Privacy note).

![Audit log](shots/18_admin_audit.png)

## 9. Phones
1. In the scanner, open **Scan cards → Scan with phone** and scan the QR code with a phone on the **same office Wi-Fi**.
2. Take photos on the phone; they arrive in this batch. Stop the pairing when done (the link expires after 15 minutes anyway).
- Windows may ask about the firewall: allow **Private networks** only (port 8766).
- Not available when running under Docker as shipped. The old `enable-phone-access` scripts are retired.
- iPhones can't pick a whole folder; select photos instead.
- To turn phone access off, delete the `certs` folder and restart.

## 10. Troubleshooting
| Problem | Fix |
|---|---|
| Browser says "can't connect" | The scanner window was closed. Double-click start again. |
| Every card fails to scan | Tesseract isn't installed (the start window says so). See QUICKSTART step 2. |
| Scanning is slow | Normal: about 3–15 s per card on a laptop. Leave the batch running and review finished cards. |
| "Please sign in" keeps appearing | Your session expired, or an admin reset your password. Sign in again. |
| **Locked out** (no admin can sign in) | On the scanner computer, open a terminal in the scanner folder and run `.venv/bin/python -m app.admin reset-password <username>` (Mac) or `.venv\Scripts\python -m app.admin reset-password <username>` (Windows). `create-admin <username> "Full Name"` makes a new admin. |
| Photo shows "Photo deleted" | The retention policy removed it. The contact details are still there. |
| Need to back up | Copy the `data` folder while the scanner is stopped. It contains the database (`cards.db`), photos and export copies. |

## "AI checking…" / "AI-checked"
If a card was hard to read, a local AI model may re-read it in the background. You can keep working. It never changes the card: differences show up as **suggestions** you accept or keep. A check takes about 45 seconds of AI model time per card (median of 48 measured checks; 9 in 10 within about 75 seconds), plus any wait in the AI line: cards are checked one at a time, so with others ahead it takes longer (the card shows its place in line). If the model is busy the card says **AI busy**; a background check that waits more than 30 minutes is skipped (ask again any time). The AI checks the **saved** card, so save your edits first. Rejected, approved and exported cards are skipped automatically. You never need to wait for it to approve. Nothing leaves this computer.

## Changes after tester round 2
- **First name is required** to approve. Values that clearly aren't an email or phone (e.g. `12`, `name@@`) can't be approved, not even with "Approve anyway".
- Cards that were **approved anyway** are marked in exports: a *NeedsAttention* column in the extra-columns CSV that comes with the Excel file, and a `needs_attention` column in CSV.
- **Export by batch (event)**: pick the batch on the Export page. Exports now include credentials, department, other address, all emails and phones, the note, and the MC Trade choice.
- Exports of a batch are blocked while a card **in that batch** looks like the same person as another, until you merge (or keep both when they really are different people; a same-batch or same-photo duplicate can only be merged or rejected). **All batches** is also blocked by look-alikes in other people's batches, so choose your own batch. The red box lists which batches can be exported right now, and each look-alike pair has **Different people (keep both)** and **Open to merge** buttons (keep both is not offered for same-photo/same-batch duplicates).
- Merging details into a card that was already exported marks it **"export it again"**, and it shows up under "Approved, not yet exported".
- **AI double-check**: if it finishes after you've reviewed the card, its differences appear as **suggestions** (Use AI value / Keep current). It never changes the card silently. "No changes" no longer lowers the confidence.
- **Details that don't agree** (e.g. the email domain vs the website, the email vs the name, the phone area code vs the address state) are listed on the review screen.
- **Back of card**: on the review screen, *Add back of card…* reads a second photo and fills only empty fields.
- Use **one browser (or browser profile) per person**. If someone else signs in in the same browser, open tabs show a red warning.

## Round-5 changes (Oct 13, 2026)
- **Look-alikes in other people's batches no longer block approval.** They show as a warning in the orange box. Only a duplicate in *your own batch* blocks it (a same photo in another batch only warns). If the other-batch card is already **approved** with the same email, phone or photo, Approve asks you to confirm once (so one person isn't sent to MC Trade twice). With several look-alikes, one button marks them all: **None of these are the same person** (saved on your card only).
- **Formula-like text** (starting with = + - @) and **HTML code** (also written as `&lt;…&gt;`) in a contact field can't be approved; fix the field first. Older cards with it are left out of the MC Trade file as "FIX FIRST".
- **MC Trade Excel:** cards marked "update the existing contact" go to a separate **…-UPDATES.xlsx** (with the MC Trade Profile ID), not into the new-profiles file. Two cards of the same person are combined into one row (a mobile or fax from the second card is kept). Colleagues sharing info@ stay separate, and so do people you marked as different. A person's website is in the extra-columns CSV (Website is an organisation column in MC Trade).
- **Preview the MC Trade files** (Export page) downloads the file without marking anything as exported.
- **Back of card:** if the back shows a different person's name, the scanner asks before adding anything.
- Notes are now in a card's History. File names are shorter. The batch filter has a search box.
- Admin: Reset password also lifts a sign-in lock. Photo deletion needs at least 1 day and never deletes photos of cards still pending. "Archive all test data" needs CLEAR in capitals.
