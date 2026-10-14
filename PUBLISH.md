# Publishing: GitHub repo + Hugging Face Space

Nothing has been pushed yet. Run these from `/workspace/gac-public` (a fresh one-commit history with no real personal data).
Replace `<gh-user>` and `<hf-user>` with the account names. Neither CLI is logged in on the box yet.

## 0. Re-check before publishing (optional, 1 minute)
```bash
cd /workspace/gac-public
~/.local/bin/gitleaks git . --no-banner          # expect: no leaks found
git status --short                               # expect: empty (data/, models/ are git-ignored)
```

## 1. Public GitHub repository
```bash
gh auth login                                     # GitHub.com, HTTPS, browser login
gh repo create <gh-user>/gac-card-scanner --public --source . --remote origin --push \
  --description "Business-card scanner for a chamber of commerce: local OCR, human review, CRM import files (GPL-3.0)"
gh repo edit <gh-user>/gac-card-scanner --add-topic ocr,business-cards,fastapi,tesseract,crm,llama-cpp
```
After the Space exists (step 2), put its URL in README.md (`DEMO_LINK_PLACEHOLDER`) and the Space's README (`GITHUB_REPO_URL`):
```bash
sed -i 's#DEMO_LINK_PLACEHOLDER#https://huggingface.co/spaces/<hf-user>/gac-card-scanner#' README.md
sed -i 's#GITHUB_REPO_URL#https://github.com/<gh-user>/gac-card-scanner#' space/README.md
git commit -am "README: demo and source links" && git push
```

## 2. Hugging Face Space (Docker SDK, free CPU basic)
The Space needs `README.md` (with the YAML header: `sdk: docker`, `app_port: 7860`) and `Dockerfile` at its root.
`scripts/make_space.sh` builds that folder from this repo (app, synthetic demo cards, `Dockerfile.space` → `Dockerfile`, `space/README.md` → `README.md`).
```bash
pip install -U huggingface_hub          # provides the `hf` CLI (tested with 2.2.0)
hf auth login                                     # token with WRITE access (huggingface.co/settings/tokens)
hf repos create <hf-user>/gac-card-scanner --type space --space-sdk docker --public --flavor cpu-basic
./scripts/make_space.sh ../gac-card-scanner-space
hf upload <hf-user>/gac-card-scanner ../gac-card-scanner-space . --repo-type space --commit-message "Public demo"
```
Git alternative to the last line:
```bash
git clone https://huggingface.co/spaces/<hf-user>/gac-card-scanner ../hf-space && cp -r ../gac-card-scanner-space/. ../hf-space/
cd ../hf-space && git add -A && git commit -m "Public demo" && git push    # password = the HF write token
```
Optional Space settings (Settings → Variables): `GAC_DEMO_PASSWORD` (change the shared login), `GAC_RULES_ONLY=1` (skip the 3 GB model download; faster start),
`LLAMA_THREADS` (default 2), `GAC_DEMO_WIPE_HOURS` (6), `GAC_DEMO_MAX_CARDS` (60), `GAC_DEMO_MAX_MB` (5).
The build log should show the llama.cpp version; the runtime log shows `PUBLIC DEMO MODE: 12 synthetic cards seeded` and, after the model download, `[ai] starting llama-server`.
Free Spaces sleep after ~48 h without visits; a restart wipes everything (that's fine for the demo).

## 3. Updating later
```bash
git push                                          # GitHub
./scripts/make_space.sh ../gac-card-scanner-space && hf upload <hf-user>/gac-card-scanner ../gac-card-scanner-space . --repo-type space
```
Never copy anything from the pilot install (data/, bench/real, qa/ reports, exports, TEST-LOGINS) into this folder.
