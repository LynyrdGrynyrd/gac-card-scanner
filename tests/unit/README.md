# Unit tests: where to look

The test files are named after the pilot's review rounds (`test_r3.py` … `test_r24.py`) and the 2026-10 audit
(`test_audit_*`, `test_accuracy_*`, `test_frontend_*`, `test_packaging_*`). They were deliberately **not** renamed or
regrouped: that would rewrite every file and lose the history that ties each test to the report it came from. This
index lists, per feature, the files with the most tests for it (by test name; a file can appear under several features).

Run: `python -m pytest -q tests/unit` (all data goes to a temporary folder, see `conftest.py`).

- **Sign-in, sessions, roles, CSRF, security headers:** `test_app.py` (3), `test_audit_p0.py` (3), `test_audit_p1_backend.py` (3), `test_demo.py` (2), `test_r5.py` (2), `test_r6_features.py` (2), `test_r22.py` (1), `test_r23.py` (1)
- **Uploads, scan jobs, cancel, recovery, PDF/HEIC:** `test_r18.py` (11), `test_r20.py` (9), `test_audit_p1_backend.py` (5), `test_frontend_desktop.py` (3), `test_r21.py` (3), `test_r23.py` (3), `test_app.py` (2), `test_audit_p0.py` (2)
- **Recognition: OCR, parser, QR, AI merge:** `test_r15_realcard_rules.py` (16), `test_accuracy_parser.py` (10), `test_r7.py` (10), `test_r10.py` (8), `test_r11.py` (8), `test_r8.py` (8), `test_plausibility.py` (7), `test_r6.py` (7)
- **Review: validation, misread blocks, confirm-correct:** `test_r23.py` (6), `test_r7.py` (6), `test_r16.py` (4), `test_r21.py` (4), `test_app.py` (3), `test_r11.py` (3), `test_r15ui.py` (3), `test_r20.py` (3)
- **Duplicates and look-alikes (in queue, CRM):** `test_r15_realcard_rules.py` (11), `test_r11.py` (6), `test_r7.py` (6), `test_r10.py` (4), `test_r14.py` (4), `test_r5.py` (4), `test_r6.py` (4), `test_r13.py` (3)
- **Bulk actions, archive, undo:** `test_r14.py` (4), `test_r9.py` (3), `test_r13.py` (2), `test_r16.py` (2), `test_r5.py` (2), `test_audit_p1_backend.py` (1), `test_frontend_static.py` (1), `test_r11.py` (1)
- **Exports (CSV, vCard, MC Trade Excel), sign-off, READ-ME:** `test_r8.py` (7), `test_r16.py` (4), `test_r7.py` (4), `test_r15ui.py` (3), `test_r17.py` (3), `test_r23.py` (3), `test_r5.py` (3), `test_r6.py` (3)
- **Privacy: delete on request, retention, tombstones, thumbnails:** `test_audit_p0.py` (3), `test_audit_p1_backend.py` (3), `test_audit_merge.py` (2), `test_r5.py` (2), `test_r8.py` (2), `test_app.py` (1), `test_dm1.py` (1), `test_frontend_static.py` (1)
- **Backups and restore:** `test_audit_p1_backend.py` (4), `test_r8.py` (2), `test_audit_p0.py` (1), `test_r15_realcard_rules.py` (1), `test_r7.py` (1), `test_r9.py` (1)
- **Phone mode:** `test_r6_features.py` (4), `test_r9.py` (2), `test_audit_p1_backend.py` (1), `test_r13.py` (1), `test_r15ui.py` (1), `test_r16.py` (1), `test_r18.py` (1), `test_r6.py` (1)
- **Admin settings, users, audit log:** `test_audit_p1_backend.py` (3), `test_r15ui.py` (2), `test_audit_p0.py` (1), `test_demo.py` (1), `test_dm1.py` (1), `test_r16.py` (1), `test_r17.py` (1), `test_r22.py` (1)
- **Public demo:** `test_audit_p1_backend.py` (2), `test_demo.py` (1), `test_desktop_v021.py` (1)
- **Desktop app, launcher, packaging, CI:** `test_audit_p1_backend.py` (4), `test_packaging_files.py` (4), `test_r15ui.py` (3), `test_app.py` (2), `test_desktop_v021.py` (2), `test_r24.py` (2), `test_r5.py` (2), `test_r6.py` (2)
- **Frontend static checks:** `test_desktop_v021.py` (3), `test_frontend_static.py` (2), `test_r8.py` (1)

## Other test layers

Install the test tools once: `pip install -r requirements.lock.txt -r requirements-dev.txt` (exact pins, see the file).

- **Parser properties (Hypothesis):** `tests/unit/test_props_parser.py`, part of the unit run. Any text: the parser never
  crashes, returns the same shape, is deterministic and never invents an email or phone; generated cards: the planted
  email and phone are found. Reproducible (`derandomize=True`), no example database written.
- **API fuzzing (Schemathesis):** `python -m pytest -q tests/api` (~1.5 min). Every operation of the app's OpenAPI,
  in-process, signed in as an admin with the CSRF header; any 5xx fails. The few excluded operations and why are listed
  at the top of `tests/api/test_fuzz_api.py`; every 500 it found has a plain test in `tests/unit/test_fuzz_regressions.py`.
- **Browser end-to-end (Playwright, Chromium):** `python -m playwright install chromium` once, then
  `python -m pytest -q tests/e2e` (~1 min; needs Tesseract). Starts the real app on a free port with a temp data folder:
  first-run admin, scan a photo, review/edit/approve, CSV export; a reviewer can't open Admin; J/K/A keys; no console errors.
