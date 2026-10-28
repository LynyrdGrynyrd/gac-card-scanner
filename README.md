# GAC Card Scanner

Photograph a pile of business cards after an event, check each one in a clean review screen, and export a contact list ready to import into a CRM. Built for the **Greater Akron Chamber** (GAC) data team as a pilot; it produces import files in the layout of **MC Trade** (MemberClicks), the Chamber's member database.

- **Local and CPU-only.** OCR (Tesseract 5 + RapidOCR/PP-OCR), QR/vCard decoding (zxing-cpp) and a rules parser (phonenumbers, name lexicon) run on one ordinary computer. No cloud calls; card photos and contacts stay on the box.
- **Human review first.** Every card lands in a review queue with per-field confidence, look-alike/duplicate warnings against the existing CRM and within the batch, plausibility hints and an audit history. Nothing is exported until a reviewer approves it.
- **Exports:** CSV, vCard, and an MC Trade import Excel (new profiles, separate updates file, one row per person). A *dry-run* sync shows what would be created or updated; there is no live CRM write.
- **Optional AI double-check:** a local vision model (Qwen3-VL-4B-Instruct GGUF via llama.cpp) re-reads low-confidence cards; scanning works without it.
- Sign-in with named reviewers and admin roles, CSRF protection, photo/export retention, delete-on-request.

**Current version: 0.4.9.** One set of counts on every export screen and file, a separate "Sent to MC Trade" record (a contacts CSV never counts as an MC Trade import), better same-person matching, shorter help. See [CHANGELOG.md](CHANGELOG.md). **[2-minute demo video](https://github.com/LynyrdGrynyrd/gac-card-scanner/releases/latest/download/GAC-Card-Scanner-demo.mp4)**.

**Live demo:** a public demo on Hugging Face Spaces (synthetic cards only) is planned; its link will be added here when it is published. Until then you can run the same demo mode locally (see [Public demo](#public-demo)).

| Scan a batch | Review a card |
|---|---|
| ![Scan](docs/screenshots/scan.png) | ![Review](docs/screenshots/review.png) |
| **Review queue** | **Export** |
| ![Queue](docs/screenshots/queue.png) | ![Export](docs/screenshots/export.png) |

*Screenshots are from the public demo mode with synthetic cards (fictional people, 555 phone numbers).*

## Download (no terminal needed)

**[⬇ Download the latest version](https://github.com/LynyrdGrynyrd/gac-card-scanner/releases/latest)** — pick the file for your computer:

| Your computer | File to download |
|---|---|
| Windows 10 / 11 (64-bit) | `GAC-Card-Scanner-Setup-x.y.z.exe` |
| Mac with Apple silicon (M1/M2/M3/M4) | `GAC-Card-Scanner-x.y.z-macos-arm64.dmg` |
| Mac with an Intel processor | `GAC-Card-Scanner-x.y.z-macos-x86_64.dmg` |

The app opens in its own window (no browser needed), runs only on your computer, and includes the card-reading engine (Tesseract). Nothing else to install.

### Windows
1. Double-click `GAC-Card-Scanner-Setup-x.y.z.exe`.
2. If a blue **"Windows protected your PC"** box appears, click **More info → Run anyway**. (The installer isn't code-signed yet; this is expected.)
3. Click through the installer (no administrator rights needed). It adds a Start-menu entry and, if you tick the box, a desktop shortcut. On older Windows 10 it also installs Microsoft's WebView2 component if missing.
4. Open **GAC Card Scanner**. The first time, create the admin account.

To uninstall: Settings → Apps → GAC Card Scanner → Uninstall. Your cards stay in `%LOCALAPPDATA%\GAC Card Scanner` (delete that folder to remove them too).

### macOS
1. Double-click the `.dmg`, then drag **GAC Card Scanner** onto **Applications**.
2. The first time only: in Applications, **right-click (Control-click) the app → Open → Open**. (The app isn't notarized by Apple yet.) If macOS only offers *Move to Trash*, go to **System Settings → Privacy & Security**, scroll down and click **Open Anyway**.
3. The scanner opens in its own window. The first time, create the admin account.

Your data lives in `~/Library/Application Support/GAC Card Scanner`. Requires macOS 14 (Sonoma) or newer.

### Optional: AI double-check
In the app: **Admin → Settings → Download AI helper (3 GB)**. It downloads llama.cpp and the Qwen3-VL-4B model (Apache-2.0) from GitHub/Hugging Face, checks their SHA-256 checksums, and runs them locally next to the app (127.0.0.1:8090). Scanning works fine without it; the AI helper re-reads uncertain cards in the background. A computer with 8 GB+ RAM is recommended.

### Desktop-app menu
**File → Open in browser** opens the same scanner in your normal browser (useful for printing or if the window misbehaves); **File → Open data folder** shows where your data is kept.

## Developer install

### Run locally (from source)
```bash
sudo apt-get install -y tesseract-ocr        # macOS: brew install tesseract
git clone <this repo> gac-card-scanner && cd gac-card-scanner
python3 -m venv .venv && .venv/bin/pip install -r requirements.lock.txt   # exact tested versions (Python 3.12/3.13); ranges: requirements.txt
.venv/bin/uvicorn app.main:app --host 127.0.0.1 --port 8765
# open http://localhost:8765 and create the first admin (first-run setup only works from this computer)
```
`start.command` (macOS) / `start.bat` (Windows) do the same with a double-click. Staff docs: [QUICKSTART.md](QUICKSTART.md), [DATA-TEAM-GUIDE.md](DATA-TEAM-GUIDE.md); developers: [HANDOFF.md](HANDOFF.md).

Try the demo mode locally (synthetic cards, shared login, nothing kept):
```bash
GAC_DEMO=1 .venv/bin/uvicorn app.main:app --host 127.0.0.1 --port 8765   # login: demo / try-the-demo-2026
```
Demo mode uses the normal `data/` folder and **wipes it** (cards, photos, exports) at start: use a separate checkout, never your real install.

## Run with Docker
```bash
docker compose up -d            # http://localhost:8765 (published on 127.0.0.1 only); data in a named volume
# or
docker build -t gac-card-scanner . && docker run -p 127.0.0.1:8765:8765 -e GAC_ALLOW_REMOTE_SETUP=1 -v gac-data:/srv/gac/data gac-card-scanner
```
HTTPS: mount a certificate at `/srv/gac/certs/cert.pem` + `key.pem` (see HANDOFF.md). The demo image for Hugging Face is `Dockerfile.space` (below; it builds from the repo root too: `docker build -f Dockerfile.space .`).

### Backups and settings
- **Nightly backups** (one `.tgz` per night, 7 kept): Docker writes them to the `gac-backups` volume (`/srv/gac/backups`, set by `GAC_BACKUP_DIR`; better, bind-mount a folder on another disk, see `docker-compose.yml`). The desktop app keeps them in a folder next to its data folder, named `<data folder> Backups` (for example `%LOCALAPPDATA%\GAC Card Scanner Backups` or `~/Library/Application Support/GAC Card Scanner Backups`), never inside the installed program. A source install uses `backups/` in the checkout unless `GAC_BACKUP_DIR` is set. Restore (source install, scanner stopped): `scripts/restore_backup.sh <file>`; the desktop app has no restore button yet.
- **`GAC_ALLOWED_HOSTS`** (comma-separated host names): first-admin setup and the open `/api/scan` API trust only requests addressed to an IP address, `localhost` or this computer's name (protection against DNS rebinding). If you reach the scanner under another name (a reverse proxy, a fixed office name), list it here.
- **`GAC_DB_BUSY_MS`** (default 30000): how long a database write waits for another writer before failing.
- All environment variables: [HANDOFF.md](HANDOFF.md#run).

## Public demo
`GAC_DEMO=1` turns the app into a shared public demo (used by the Hugging Face Space):
- red banner on every page: **"Public demo — don't upload real cards"**; one shared demo login is printed on the sign-in page (`GAC_DEMO_USER` / `GAC_DEMO_PASSWORD`)
- synthetic sample cards are seeded (from `tests/synth2`); setup, password changes and all admin calls are refused
- every export is a **preview** (MC Trade Excel = dry-run file); nothing is stored or marked exported
- uploads are capped (`GAC_DEMO_MAX_MB`, default 5 MB per photo; `GAC_DEMO_MAX_CARDS`, default 60) and **everything is wiped every `GAC_DEMO_WIPE_HOURS` (default 6) hours**, then re-seeded
- no audit of visitors: no IP addresses in sessions or the sign-in log; the corrections dataset is off

The Space image (`Dockerfile.space`, `space/start.sh`, `space/README.md`) runs on the free CPU tier, downloads Qwen3-VL-4B-Instruct GGUF (Apache-2.0) from Hugging Face at start and runs `llama-server` with 2 threads; if the download or the server fails, the demo runs rules-only. `GAC_RULES_ONLY=1` skips the model. How to publish: [PUBLISH.md](PUBLISH.md).

## Privacy
Business cards carry personal data. In a real install everything stays on the computer running the scanner: no telemetry, no cloud OCR, no CRM writes. Photos and stored exports are purged after a retention period (admin setting), a card can be deleted on request, and the review history keeps no personal data after deletion. See [PRIVACY-NOTE.md](PRIVACY-NOTE.md).

**This repository contains no real personal data.** All test, demo and screenshot cards are generated (`tests/gen_cards.py`, `tests/gen_hard.py`, `tests/gen_synth2.py`) with fictional people and 555 numbers; `data/existing_contacts.csv` is a fake CRM sample. The pilot's real-card benchmark, QA screenshots, logins, database and exports were left out. **Don't upload real cards to the public demo.**

## Tests
```bash
.venv/bin/pip install pytest httpx
.venv/bin/python -m pytest tests/unit          # unit + API tests, incl. tests/unit/test_demo.py (demo mode)
.venv/bin/python tests/eval.py                 # synthetic accuracy (CI also runs bench/eval_bench.py on tests/synth2)
.venv/bin/python tests/gen_cards.py && .venv/bin/python tests/gen_hard.py && .venv/bin/python tests/eval.py   # synthetic accuracy
```
Synthetic cards are far easier than real ones; budget for human review on every card.

### Accuracy on your own cards
Every approved card is a labelled example: what a reviewer approved is the right answer. `bench/extract_eval_set.py` reads the
scanner's database (read-only) and turns approved cards whose photo is still kept into a test set for `bench/eval_bench.py`,
including cards approved unchanged, and prints how often reviewers had to fix each field:
```bash
.venv/bin/python bench/extract_eval_set.py --data-dir "<data folder>" --dry-run   # the per-field report only
.venv/bin/python bench/extract_eval_set.py --data-dir "<data folder>"             # + photos and gt.json in <data folder>/corrections
.venv/bin/python bench/eval_bench.py "<data folder>/corrections/gt.json" "<data folder>/corrections" --show
```
The copies are real people's cards: they go to the same folder as "Keep corrected cards as test examples", so photo retention
and delete-on-request clean them too. Never commit them (the script refuses a folder git would track).

## Developer reference
### Endpoints
> Since the /ui release, `/`, `/queue`, `/card/{id}` and `/export.*` redirect to `/ui` and require sign-in. See HANDOFF.md.

| Path | Purpose |
|---|---|
| `/ui` | Data-team web app (scan, review queue, review card, export, admin) |
| `/login`, `/setup`, `/privacy` | Sign-in, first-run admin setup, privacy note |
| `/api/...` | JSON API used by /ui (sign-in required; see app/ui.py, app/auth.py) |
| `/img/{name}` (`?w=160` for a cached thumbnail) | Card photo (sign-in required) |
| `POST /api/scan` | JSON API for scanning one image (capped by `SCAN_WORKERS`) |
| `/health` | Liveness check |

Retired (redirect to /ui or 410): `/`, `/card/{id}`, `/queue`, `/export.*`, `/sync/dry-run*`.

### Architecture
```mermaid
flowchart LR
  A[Phone camera / upload] --> B[FastAPI /scan]
  B --> C{Engine}
  C -->|default| D[Preprocess + Tesseract 5]
  C -->|optional| E[llama.cpp llama-server: Qwen3-VL-4B GGUF]
  E -.fallback.-> D
  D --> F[Parser: regex + phonenumbers + heuristics]
  E --> G[VLM JSON]
  F --> H[(SQLite: cards, status=pending)]
  G --> H
  H --> I[Review/edit UI]
  I -->|approve/reject| H
  H --> J[CSV / vCard export]
  H --> K[mctrade_sync DRY-RUN]
  K --> L[Duplicate match vs existing_contacts.csv]
  K -.future, after approval + API key.-> M[(MC Trade API: OAuth2 client_credentials)]
```
Files: `app/ocr.py` (engines), `app/parser.py` (fields+confidence), `app/store.py` (SQLite queue), `app/export.py`, `app/mctrade_sync.py` (stub), `app/main.py` (web UI), `data/existing_contacts.csv` (fake CRM sample), `tests/` (synthetic cards, ground truth, eval).


## License
**GPL-3.0-or-later** (see [LICENSE](LICENSE)). GPL was chosen because the first-name lexicon dependency, [gender-guesser](https://github.com/lead-ratings/gender-guesser), is GPL-3.0. The Greater Akron Chamber name and logo are not covered by the license; replace them in a fork.

## Credits
Built on open source; full list with licenses in [THIRD-PARTY-NOTICES.md](THIRD-PARTY-NOTICES.md):
[Tesseract OCR](https://github.com/tesseract-ocr/tesseract), [RapidOCR](https://github.com/RapidAI/RapidOCR) + [PaddleOCR](https://github.com/PaddlePaddle/PaddleOCR) models, [ONNX Runtime](https://github.com/microsoft/onnxruntime), [OpenCV](https://github.com/opencv/opencv), [zxing-cpp](https://github.com/zxing-cpp/zxing-cpp), [python-phonenumbers](https://github.com/daviddrysdale/python-phonenumbers) (Google libphonenumber), [gender-guesser](https://github.com/lead-ratings/gender-guesser), [RapidFuzz](https://github.com/rapidfuzz/RapidFuzz), [FastAPI](https://github.com/fastapi/fastapi), [Uvicorn](https://github.com/encode/uvicorn), [Pillow](https://github.com/python-pillow/Pillow), [openpyxl](https://foss.heptapod.net/openpyxl/openpyxl), [NumPy](https://github.com/numpy/numpy), [cryptography](https://github.com/pyca/cryptography), [llama.cpp](https://github.com/ggml-org/llama.cpp), [Qwen3-VL](https://huggingface.co/Qwen/Qwen3-VL-4B-Instruct-GGUF) (Apache-2.0), [Lato](https://fonts.google.com/specimen/Lato) and other OFL fonts. Research notes: [RESEARCH.md](RESEARCH.md), [OSS-SURVEY.md](OSS-SURVEY.md).

## Building the installers
`.github/workflows/release.yml` builds the Windows installer (PyInstaller onedir + bundled UB-Mannheim Tesseract + Inno Setup) and the macOS disk images (PyInstaller .app + Homebrew Tesseract with relocated dylibs, arm64 on macos-14 and x86_64 on macos-15-intel), smoke-tests each bundle (start headless, `/health`, scan `tests/cards/card1_left.jpg`), and attaches them to a GitHub Release when a `v*` tag is pushed. To release: update `VERSION` and add a `## vX.Y.Z` section to `CHANGELOG.md` (it becomes the release notes), commit, then tag `vX.Y.Z` (the workflow stops if the tag and `VERSION` differ). Installers are code-signed only when the signing secrets are configured (see [docs/SIGNING.md](docs/SIGNING.md)); every installer gets a build-provenance attestation (`gh attestation verify <file> --repo LynyrdGrynyrd/gac-card-scanner`) and is listed in `SHA256SUMS.txt`. Entry point: `packaging/launcher.py` (pywebview window; `--headless` for CI). Run from source the same way: `pip install pywebview && python packaging/launcher.py`.
