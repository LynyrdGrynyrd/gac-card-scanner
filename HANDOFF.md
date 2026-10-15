# Card Scanner: developer handoff
For a developer picking this up later. User-facing docs: QUICKSTART.md, DATA-TEAM-GUIDE.md (and PILOT-PLAN.md, not in the public repo). Research: RESEARCH.md. Accuracy history: ITERATIONS.md (not in the public repo). Code audit and its follow-up: docs/AUDIT-2026-10-15.md, CHANGELOG.md.
> **Public repository note:** internal pilot material referenced below is **not in this repository** because it contains real or internal data: `PILOT-PLAN.md`, `ITERATIONS.md`, the browser end-to-end suite and its helpers (`qa/e2e_ui.py`, `qa/e2e_r2.py`, `qa/reset_demo.sh`), qa/ reports and screenshots (`shots/`), `audits/*.md` (only `audits/scripts/` is public), `qa/ROUND2-FIXES.md`, pilot.pdf, training/, bench/real and MC Trade docs snapshots. What is here: all application code, `tests/unit` (pytest), the synthetic accuracy sets (`tests/eval.py`, `bench/eval_bench.py` + `tests/synth2`), `qa/fixtures`, `qa/seed_demo.py`, `qa/fake_vlm.py` and `audits/scripts/`.

## What it is
A local, CPU-only FastAPI app: card photo → QR/vCard decode + OCR → rule parser → **human review** (/ui) → CSV / vCard / MC Trade-style Excel. A **dry-run** MC Trade sync stub exists (`app/mctrade_sync.py`); there is no live API code. Single SQLite DB, single process.

## Architecture
```mermaid
flowchart LR
  B[Browser /ui SPA<br>app/static/ui] -->|cookie session| M[auth middleware<br>app/auth.py]
  M --> UI[app/ui.py routes]
  UI -->|POST /api/jobs| P[ThreadPool<br>SCAN_WORKERS]
  P --> PL[app/pipeline.py<br>qr.py → ocr.py → parser.py → (vlm/merge)]
  PL --> S[(SQLite data/cards.db<br>store.py: cards)]
  UI --> X[(extra tables: card_meta, card_history,<br>actions, exports, users, sessions, settings, auth_log)]
  UI --> E[exports → data/exports + download]
  R[retention thread hourly] --> S
```
| File | Purpose | Owner notes |
|---|---|---|
| `app/main.py` | FastAPI app, legacy server-rendered pages (now shadowed by redirects), `/api/scan` (JSON contract, OCR in threadpool) | registers `auth.router`, `ui.router` **before** legacy routes, and the auth middleware |
| `app/auth.py` | users (PBKDF2-SHA256, 310k iterations), sessions (random token, SHA-256 stored, 12 h sliding), roles, settings, auth_log, first-run setup | setup allowed only from loopback unless `GAC_ALLOW_REMOTE_SETUP=1` |
| `app/admin.py` | CLI: `python -m app.admin create-admin|reset-password|list` | for lockouts / Docker |
| `app/ui.py` | all /ui JSON APIs: async scan jobs, cards, validation, `attention()`, duplicates (CRM sample + in-queue + photo hash), bulk, archive, **undo** (row snapshots in `actions`), exports + history, retention purge, audit | single source of truth for "needs attention" |
| `app/static/ui/` | `index.html`, `ui.js` (no framework, no build step), `ui.css`, `login.html`, `privacy.html` | |
| `app/pipeline.py`, `ocr.py`, `parser.py`, `qr.py`, `vlm.py`, `merge.py` | recognition pipeline | owned by the accuracy work; UI only calls `pipeline.scan()` and `qr.decode/parse_vcard` (for per-field source) |
| `app/store.py`, `export.py`, `mctrade_sync.py` | card table, CSV/vCard, duplicate scoring + dry-run plan | `mctrade_sync.match()` is reused for in-queue duplicates |
| `app/make_cert.py` | self-signed HTTPS cert with LAN IP SANs | |

### Data model (SQLite, `data/cards.db`)
- `cards` (store.py): id, created, status pending/approved/rejected, engine, raw_text, fields JSON, image filename ('' after retention), reviewer (initials), note, decided.
- `card_meta`: batch, batch_label, filename, sha256, archived, dup_resolution (`keep_both` / `merged_into:N`), crm_action (`update_existing`/`create_new`), exported (first export ts), field_sources JSON (`qr`/`ocr`/`edited:XX`), image_deleted.
- `card_history`: per-card audit (scanned, edited with from/to, decision with override reason, merged_from, mc_trade_choice, duplicate_kept_both, archived, exported, undo, photo_deleted).
- `actions`: undo stack: full row snapshots of `cards` + `card_meta` before each change; undo restores them (24 h, own actions only).
- `exports`: who/when/kind/filter/count/filename/card_ids + stored copy in `data/exports/`.
- `users`, `sessions`, `settings` (image_retention_days, export_retention_days, retention_enabled), `auth_log`.

### Key rules (server-enforced; the UI only mirrors them)
- Every request except `/login`, `/setup`, `/static/*`, `/api/auth/*`, `/health`, `/privacy` needs a session. `/api/scan` is open **from loopback only** (scripts/benchmarks on the same machine).
- Reviewer identity = signed-in user's initials (client-supplied reviewer is ignored).
- Approve requires `validate()` to pass or an `override_reason`; re-deciding needs `confirm_redecide`; approve is refused if an approved card is the same person (unless keep_both) or a CRM match has no `crm_action`.
- Exports return 409 while the export set contains unresolved in-set duplicates.
- Legacy URLs: `/`, `/queue`, `/card/{id}`, `/export.*` redirect to `/ui`; `POST /card/{id}` returns 410; `POST /scan` → /ui.

## Run
```bash
# dev (Linux/Mac)
python3 -m venv .venv && .venv/bin/pip install -r requirements.lock.txt   # + system tesseract-ocr; Python 3.12 (CI/release) or 3.13
.venv/bin/uvicorn app.main:app --host 127.0.0.1 --port 8765 --reload
# Round 9: bind 127.0.0.1 (the default in start.command / start.bat). Phones use phone mode, which opens its own
# LAN listener (PHONE_PORT, default 8766) only while a pairing is live. Open the WHOLE app to the LAN only on purpose:
GAC_HOST=0.0.0.0 ./start.command      # or: .venv/bin/uvicorn app.main:app --host "${GAC_HOST:-127.0.0.1}" --port 8765
# Docker
docker compose up -d --build     # http://localhost:8765, data in volume gac-data
docker compose exec scanner python -m app.admin create-admin admin "Admin Name"
```
Env (main ones): `SCAN_WORKERS` (default 1; OCR is CPU-heavy), `OCR_ENGINE` (hybrid default), `USE_VLM=1` (optional local VLM), `GAC_ALLOW_REMOTE_SETUP=1` (Docker first-run only), `CARD_CROP`, plus:
- `GAC_ALLOWED_HOSTS`: comma-separated extra host names to trust. First-admin setup and the open `/api/scan` API trust loopback clients only when the request's Host is an IP address, `localhost` or this computer's name (DNS-rebinding guard, audit P0-11); add the name here when you reach the scanner through a reverse proxy or a fixed office name.
- `GAC_DB_BUSY_MS` (default 30000): how long SQLite waits for another writer before failing ("database is locked").
- `GAC_DATA_DIR` (default `data/`; the desktop app sets it to `%LOCALAPPDATA%\GAC Card Scanner` / `~/Library/Application Support/GAC Card Scanner`).
- `GAC_BACKUP_DIR`, `BACKUP_KEEP` (default 7): nightly backups. Default location: desktop app `<data folder> Backups` (a sibling of the data folder, e.g. `%LOCALAPPDATA%\GAC Card Scanner Backups`, so an upgrade never touches it); Docker `/srv/gac/backups` = the `gac-backups` volume (docker-compose.yml); source install `backups/` in the checkout. Restore: `scripts/restore_backup.sh <file>` (scanner stopped).
- `VLM_URL` (default `http://127.0.0.1:8090`), `VLM_API_KEY` (Bearer key for a llama-server started with `--api-key`/`--api-key-file`; the desktop AI helper's own per-start key is read from `<data>/ai-helper/api-key` automatically), `GAC_AI_PORT` (desktop helper port, 8090), `VLM_TIMEOUT`.

## Tests
```bash
.venv/bin/pip install pytest httpx
.venv/bin/python -m pytest -q tests/unit                                    # ~5 min; all data goes to a temp folder
.venv/bin/python tests/gen_cards.py && .venv/bin/python tests/eval.py       # parser accuracy (synthetic)
.venv/bin/python bench/eval_bench.py tests/synth2_gt.json tests/synth2      # full pipeline on synth2 (~4 min)
# not in the public repo (pilot only):
qa/reset_demo.sh                       # WIPES data/cards.db, uploads, exports; restarts server on 8765
.venv/bin/python qa/e2e_ui.py          # playwright, ~2 min, 47 checks; writes shots/*.png
.venv/bin/python bench/eval_bench.py bench/real_gt.json bench/real   # real-card benchmark (see ITERATIONS.md)
```
CI (`.github/workflows/ci.yml`) runs the unit tests on Ubuntu, Windows and macOS, ruff, pip-audit on `requirements.lock.txt` and the two synthetic accuracy gates.
The (pilot-only) e2e covers: first-run setup, weak password, roles, sign-in/out, temp-password change, legacy redirects, keyboard reachability, upload of 13 cards (incl. a QR vCard card) + 4 bad files, responsiveness during OCR, batch persistence, filters/search/refresh, QR per-field badges, edit badge, undo (key + button), validation block, MC Trade choice, re-decide warning, merge, bulk skip report, not-yet-exported, export history + re-download, CSV reviewer column, audit log, retention delete, privacy page, phone layout, archive + undo, no JS errors.
Playwright needs `pip install playwright && python -m playwright install chromium` (dev only, not in requirements.txt).

## Packaging
Staff get the desktop installers from GitHub Releases (`.github/workflows/release.yml`, see README "Building the installers" and docs/SIGNING.md). `python scripts/build_zip.py` builds `../gac-card-scanner-pilot.zip` for a source install (excludes .venv, DB, photos, exports, certs, QA backups, caches). `requirements.lock.txt` pins every package (transitive ones too) for Python 3.12-3.13 on Linux, Windows and macOS; regenerate it from `requirements.txt` with the `uv pip compile` command in its header. CI, the release builds, Docker, the Space and start.command / start.bat all install it.

## Known limits / next steps
1. **Not hardened for the internet.** Intended for one office computer / office Wi-Fi. No rate limiting beyond login lockout (CSP, Origin check + CSRF token and body limits exist; see the audit round below and docs/AUDIT-2026-10-15.md). Put it behind proper HTTPS + SSO before wider use.
2. **Single process.** Uploads waiting to be read persist in `data/inbox/` and are re-queued after a restart, but the job list itself is in memory. SQLite (WAL mode) is fine for a few users; move to Postgres for more.
3. **Duplicate check vs MC Trade uses a sample CSV.** Replace `data/existing_contacts.csv` with an MC Trade export, or implement the read-only API search (RESEARCH.md §2, `mctrade_sync.py`).
4. **Excel column names are unverified** against GAC's Import Profiles template. Save the real template as `data/mctrade_template.xlsx` and its header row is used exactly. Non-template data goes to the companion `…-extra-columns.csv`.
5. **Accuracy:** ~85% field accuracy rules-only on 26 real cards, ~93% with the AI double-check (Qwen3-VL-4B, Apache-2.0: 241–242/260 = 92.7–93.1%; see ITERATIONS.md iteration 10 and OSS-SURVEY.md) (synthetic cards 97–100%) (ITERATIONS.md). Human review stays mandatory.
6. Undo covers card changes only (not exports, user admin, or retention deletions); 24 h window; per user.
7. Retention deletes photos and export copies, not the typed contact data (by design; archive handles that). For a removal request an admin uses **Delete permanently** on the card (`POST /api/admin/cards/{id}/delete`; audited, see the audit round below).
8. The Windows and macOS desktop apps are built and smoke-tested (bundle, installer/DMG) by the release workflow, and CI runs the unit tests and a from-source launcher smoke test on Windows and macOS. The Docker images, `start.bat` and `start.command` are **not** exercised by CI: try them by hand after changing them.
9. iOS Safari has no folder picker; phones need the HTTPS mode for camera capture on the LAN.
10. Browser support tested: Chromium (desktop + mobile emulation). Spot-check Safari/Edge before the pilot.

## AI double-check (vision model): Qwen3-VL-4B (Apache-2.0) by default since iteration 10
- Scans now go through `app/pipeline.scan` (QR → hybrid ppocr+tesseract → crop pass → rules), for both the UI and `/api/scan`; the JSON is unchanged (`engine` now reads e.g. `ppocr+tesseract`).
- When a card comes out low-confidence and a vision server answers on `127.0.0.1:8090`, it is queued for a background **AI double-check** (1 worker, `ui.AI_POOL`). The queue and review screen show "AI checking…" / "AI-checked". It never blocks scanning. It skips cards that were already edited or approved, and QR cards are never sent. Field sources become `ai`, and the action is logged as `ai_checked` in the audit log.
- Toggle: Admin → Settings → "AI double-check" (`ai_check_enabled`). Status: `GET /api/ai/status`. Manual: `POST /api/cards/{id}/ai-check`.
- Start the model (optional; scanning works without it): run `./start-ai-checker.command`, or from `/workspace/models`:
  `./start-ai-checker.command` → `llama-server -m Qwen3VL-4B-Instruct-Q4_K_M.gguf --mmproj mmproj-Qwen3VL-4B-Instruct-Q8_0.gguf -c 2048 -np 1 --cache-ram 0 --no-slots -t 8 --host 127.0.0.1 --port 8090 --image-max-tokens 768` (`--cache-ram 0` matters: without it llama.cpp keeps up to 8 GB of prompt cache and was OOM-killed on a 16 GB machine) (Qwen3-VL-4B-Instruct, Apache-2.0, ~3 GB RAM, ~24 s/card; output constrained by the JSON schema in app/vlm.py). Fallback only: `GAC_VLM=qwen25-3b ./start-ai-checker.command` (Qwen2.5-VL-3B, Qwen Research License = non-commercial).
  The model files (~3 GB) are NOT in the pilot zip. Copy them into a `models/` folder next to the app. Expect about 20–60 s per card on CPU.
- Desktop app: Admin → Settings → AI helper downloads a pinned llama.cpp build and the model (pinned Hugging Face revision, SHA-256 checked) and runs `llama-server ... -c 4096 -np 1 --cache-ram 0 --no-slots --api-key-file <data>/ai-helper/api-key` (`app/ai_helper.py`). The key is random and new on every start; `app/vlm.py` sends it as `Authorization: Bearer`. A server started by hand without a key needs nothing (no header is sent unless `VLM_API_KEY` is set or the helper's key file exists).

## Audit round (2026-10-13): what changed
Reports: `audits/*.md` (SECURITY, ACCESSIBILITY, PRIVACY, CODE-QUALITY, ACCURACY-PHASE6) and `qa/ROUND2-FIXES.md` are not in the public repo; see `PRIVACY-NOTE.md` and `audits/scripts/`.
- Security: CSP and security headers, Origin-based CSRF check, 26 MB body limit, decompression-bomb and format-spoof guards, safe `?next=`, other sessions revoked on password change, `/docs` off.
- Reliability: uploads persist in `data/inbox/` and are re-queued after a crash or restart; job results in `data/jobs_done/` (24 h); AI checks in flight are re-queued.
- Privacy: admin "Delete permanently" (`POST /api/admin/cards/{id}/delete`, secure_delete + VACUUM); undo snapshots cleared after 2 days; orphan photos purged.
- New modules and endpoints: `app/consistency.py`; `/api/validate`, `/api/cards/{id}/ai-decide`, `/api/cards/{id}/back`; settings `corrections_enabled`; env `VLM_TIMEOUT` (now 240 s), `CORRECTIONS_DIR`, `CONSISTENCY`.
- Tests: `tests/unit/` (pytest; all data goes to a temporary folder, see conftest.py), `audits/scripts/*` (security probe, axe, load/crash, retention), and the pilot-only `qa/e2e_r2.py` / `qa/e2e_ui.py` (not public; `qa/e2e_ui.py` honours `GAC_BASE`).
