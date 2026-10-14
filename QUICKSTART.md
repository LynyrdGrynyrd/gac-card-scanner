# Card Scanner: Quick start
*Greater Akron Chamber · internal pilot*

The Card Scanner turns photos of business cards into a contact list you can check and import into MC Trade. Everything runs on one office computer. Card photos and contact details are **never sent to the internet**.

---

## 1. Start the scanner (the person who looks after it)

**You need:** a Mac or Windows computer with internet for the first start, and about 15 minutes.

1. **Install Python 3** (one time) from https://www.python.org/downloads/. On Windows, tick **"Add python.exe to PATH"**.
2. **Install Tesseract**, the card-reading engine (one time):
   - **Mac:** install Homebrew (https://brew.sh), then in Terminal run `brew install tesseract`
   - **Windows:** run the installer from https://github.com/UB-Mannheim/tesseract/wiki and keep the default folder.
3. Unzip **gac-card-scanner-pilot.zip** somewhere permanent (for example *Documents*).
4. Double-click **`start.command`** (Mac) or **`start.bat`** (Windows).
   - The first start installs components and takes a few minutes. Later starts take about 10 seconds.
   - On a Mac, if it says the file "can't be opened", right-click it, choose **Open**, then **Open** again.
   - **Keep the black window open.** Closing it stops the scanner.
5. Your browser opens. The first time, it asks you to **create the admin account**.

![First-time setup](shots/00_first_time_setup.png)

6. Go to **Admin → Reviewers** and add an account for each person on the data team. Give each person their username and temporary password; they choose their own password at first sign-in.

## 2. Scan cards (anyone with an account)

1. Open **http://localhost:8765** and sign in.
2. Optional: type a **batch name**, for example "Oct 15 Business After Hours".
3. Drag photos (or a whole folder of photos) onto the dashed box, or click **Choose photos** or **Choose a folder**.
4. Watch each card being read. Cards marked **Check** need a second look; **Not added** files show the reason (blank photo, not a photo, or already scanned).
   An **already scanned** photo says who scanned it and when. If you really want a second copy, click **Scan it anyway** on that row.
   The header count, the queue and the "already scanned" check are shared by everyone on the team.

![Scanning a batch](shots/02_batch_progress.png)

## 3. Review and approve

Click **Review this batch**. Open each card, compare the fields with the photo, fix anything wrong, then **Approve** (key **A**) or **Reject** (key **R**). **J**/**K** move to the next and previous card, and **U** undoes your last action.

![Review screen](shots/07_review_duplicate.png)

- **Yellow** fields were hard to read: check them against the photo.
- **First name is required.** A blank first name, an email without "@" or a phone with fewer than 7 digits can't be approved, not even with "Approve anyway". All problems are listed together.
- The optional **AI double-check** takes about 45 seconds of AI model time per card (median of 48 measured checks; 9 in 10 within about 75 seconds), plus any wait in the AI line: cards are checked one at a time, so with others ahead it takes longer (the card shows its place in line). It checks the saved card, so save first. If it is busy the box says so, and you don't need to wait for it. It never changes what you typed: it offers suggestions you accept or keep.
- **"from QR code"** means the detail came from the card's QR code, which is very reliable.
- An **orange box** means the person may already be in MC Trade or scanned twice. Pick one of the plain-language choices.

## 4. Export for MC Trade

Go to **Export**, keep **"Approved, not yet exported"**, choose your event in **Which batch (event)?** (otherwise every batch is exported), and click **MC Trade import (Excel)**. The file name includes the batch. Your **Downloads** folder gets **the import file** `GAC-MCTrade-….xlsx` (this is the file you import in MC Trade: template columns only, one row per person), a `…-READ-ME.txt`, a `…-extra-columns.csv` (notes, second emails, rows left out; not for import) and, when some cards update existing MC Trade profiles, `GAC-MCTrade-…-UPDATES.xlsx` (a separate import). Read the READ ME first. **Check against MC Trade (dry run)** on the same page shows UPDATE / CREATE / NEEDS REVIEW per card without changing anything. The header row comes from GAC's template once an admin uploads it (Admin → Settings; saved as `data/mctrade_template.xlsx`).

![Export](shots/12_export_done.png)

## Using a phone (optional)
Phones can scan cards directly with the camera. Use **Scan cards → Scan with phone** in the scanner and scan the QR code with a phone on the same office Wi-Fi (no certificate or extra step; see docs/PHONE-MODE.md). The old `enable-phone-access` scripts are retired. Under Docker, phone mode doesn't work as shipped (see docs/PHONE-MODE.md).

## Help
- **Forgot password:** ask an admin (Admin → Reviewers → Reset password).
- **Nobody can sign in:** see "Locked out" in DATA-TEAM-GUIDE.md.
- **Something looks wrong:** take a screenshot and note the card number (#).
