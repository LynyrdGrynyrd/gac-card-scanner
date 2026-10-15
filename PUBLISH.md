# Publishing: GitHub repo + Hugging Face Space

Status: the GitHub repository is public at https://github.com/LynyrdGrynyrd/gac-card-scanner and desktop installers are
published on its Releases page (see README "Building the installers"). The Hugging Face Space (step 2) is **not published
yet**. Run the commands from a clean clone of the repository; replace `<hf-user>` with the Hugging Face account name.

## 0. Re-check before publishing (optional, 1 minute)
```bash
gitleaks git . --no-banner                       # expect: no leaks found
git status --short                               # expect: empty (data/, models/ are git-ignored)
```

## 1. Public GitHub repository (done)
https://github.com/LynyrdGrynyrd/gac-card-scanner. `space/README.md` already links to it.
After the Space exists (step 2), replace the "Live demo" sentence near the top of README.md with its link
(`https://huggingface.co/spaces/<hf-user>/gac-card-scanner`), commit and push.

## 2. Hugging Face Space (Docker SDK, free CPU basic)
The Space needs `README.md` (with the YAML header: `sdk: docker`, `app_port: 7860`) and `Dockerfile` at its root.
`scripts/make_space.sh` builds that folder from this repo (app, VERSION, mctrade-dryrun, synthetic demo cards, the lock file, `Dockerfile.space` → `Dockerfile`, `space/README.md` → `README.md`). To try the image first: `docker build -f Dockerfile.space -t gac-space . && docker run -p 7860:7860 -e GAC_RULES_ONLY=1 gac-space`.
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
The build log should show `llama.tgz: OK` (SHA-256 check) and the llama.cpp version; the runtime log shows `PUBLIC DEMO MODE: 12 synthetic cards seeded` and, after the model download, `[ai] starting llama-server`.
Free Spaces sleep after ~48 h without visits; a restart wipes everything (that's fine for the demo).

## 3. Updating later
```bash
git push                                          # GitHub
./scripts/make_space.sh ../gac-card-scanner-space && hf upload <hf-user>/gac-card-scanner ../gac-card-scanner-space . --repo-type space
```
Never copy anything from the pilot install (data/, bench/real, qa/ reports, exports, TEST-LOGINS) into this folder.
