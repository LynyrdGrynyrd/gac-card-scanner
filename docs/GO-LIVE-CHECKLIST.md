# Pre-go-live checklist (GAC Card Scanner)

Do these steps, in order, before the first real event. Tick each one off and note who did it and when.

## 1. Logins: one per person
- [ ] In **Admin → Users → Add a person**, create an account for each staff member who scans or reviews cards. Use their real name and initials, because the initials are what the audit log and exports record. Give each person a temporary password; they are asked to change it when they first sign in.
- [ ] Make only the people who manage settings, templates, contacts and backups **Admin**. Everyone else is a **Reviewer**.
- [ ] **Deactivate** every shared test login: `qa-admin`, `qa-new`, `qa-pt`, `qa-rev` and any other `qa-*` account. Use **Admin → Users → Deactivate**; the Users list flags these accounts as "shared test login". Deactivating keeps their past actions in the audit log, so nothing is deleted. It also signs out their open sessions.
- [ ] If someone forgets their password, use **Admin → Users → Reset password**. This sets a temporary password, signs them out everywhere and lifts the wrong-password lock. (A command-line reset is also available: `python -m app.admin reset-password <username>`.)
- [ ] When someone leaves, **Deactivate** their account the same day.

## 2. Remove test data
- [ ] Back up first: run `scripts/backup.sh` and keep the file.
- [ ] Use **Admin → Clear all test data** (type CLEAR) to archive every test card. Archived cards are hidden from the queue and from exports.
- [ ] Permanently purge the test cards and photos. Either delete them one at a time (Card → Delete permanently), or start from a fresh data folder: stop the scanner, move `data/` aside, start it again and create the admin account. Never use `qa/reset_demo.sh` on the live computer.
- [ ] In **Admin → Settings**, remove any test MC Trade contacts file, then upload GAC's real contacts export (Profile Selector, with Profile ID, First Name, Last Name and Email columns).
- [ ] Upload GAC's real MC Trade import template.

## 3. Network and security
- [ ] Start the scanner with `start.command` / `start.bat` (or `scripts/serve.sh`). By default it listens on **127.0.0.1 only**. Do **not** set `GAC_HOST` unless the whole app really must be reachable from the network.
- [ ] **Handover (round 13): the pilot box is currently running with `GAC_HOST=0.0.0.0`** so the QA testers can reach it on 127.0.0.2–.7. Before go-live, restart it on 127.0.0.1: stop the server, then run `VLM_URL=http://127.0.0.1:8090 PORT=8765 scripts/serve.sh` (no `GAC_HOST`), and check `curl http://127.0.0.2:8765/health` no longer answers.
- [ ] Phones use **Upload → Scan with a phone**. This opens a separate listener only for the phone page, only while a pairing is live.
- [ ] In **Admin → Settings**, decide on the update check: "Check for scanner updates" is shown there and can be switched off.
- [ ] Set `GAC_BACKUP_DIR` to another disk, such as a USB drive or network share. The server log warns when backups are on the same disk as the data.

## 4. First real import
- [ ] Turn on "Update existing MC Trade contacts" only once the update path has been tried. Update rows leave **MemberSince blank**.
- [ ] Do a 2-row test import first: one new profile and one update. Check both profiles in MC Trade.
- [ ] Use the export sign-off's **"What the updates change in MC Trade"** table to check every overwrite before importing.
