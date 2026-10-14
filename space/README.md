---
title: GAC Card Scanner (public demo)
emoji: 📇
colorFrom: blue
colorTo: red
sdk: docker
app_port: 7860
pinned: false
license: gpl-3.0
short_description: Business-card scanner demo, synthetic cards only
---

# GAC Card Scanner: public demo

**Public demo — don't upload real cards.** Sign in with the shared demo login shown on the sign-in page.

- Sample cards are synthetic (fictional people, 555 numbers). Everything is wiped every 6 hours.
- Uploads are capped (5 MB per photo, 60 cards in total). Exports are previews only; the MC Trade Excel is a dry-run file.
- Runs on the free CPU tier: OCR (Tesseract + RapidOCR) and a rules parser. An optional AI double-check (Qwen3-VL-4B-Instruct GGUF, Apache-2.0, via llama.cpp) is downloaded at start and runs with 2 threads; it is slow here and the demo falls back to rules-only if it's unavailable.

Source code: GITHUB_REPO_URL (GPL-3.0-or-later).
