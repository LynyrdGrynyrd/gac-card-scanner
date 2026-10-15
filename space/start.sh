#!/bin/sh
# Start script for the public demo (HF Space or any box). Runs the app on $PORT (default 7860) in demo mode and,
# in the background, downloads Qwen3-VL-4B-Instruct GGUF from Hugging Face and starts llama-server on 127.0.0.1:8090.
# Any failure there leaves the AI double-check off: scanning works rules-only (OCR + parser).
# GAC_RULES_ONLY=1 skips the model entirely (useful on small machines / for smoke tests).
# The model files come from a pinned repo revision and are sha256-checked: the same revision and hashes as the desktop
# AI helper (app/ai_helper.py HF_REVISION / MODEL / MMPROJ). A custom GAC_VLM_MODEL/GAC_VLM_MMPROJ is only checked when
# GAC_VLM_MODEL_SHA256 / GAC_VLM_MMPROJ_SHA256 are given.
set -u
PORT="${PORT:-7860}"; MODELS="${MODELS:-$(pwd)/models}"; LLAMA_DIR="${LLAMA_DIR:-/opt/llama}"; T="${LLAMA_THREADS:-2}"
REPO="${GAC_VLM_REPO:-Qwen/Qwen3-VL-4B-Instruct-GGUF}"
REV="${GAC_VLM_REVISION:-1cd86afb9a95c410a6038ab3b40d8b578c892266}"
DEF_MOD=Qwen3VL-4B-Instruct-Q4_K_M.gguf;      DEF_MOD_SHA=66358cb18bb6b3b1b6675aa412c7a88ef01d228f481184d13668e5201c730a0a
DEF_PROJ=mmproj-Qwen3VL-4B-Instruct-Q8_0.gguf; DEF_PROJ_SHA=30ba2c7dd3127a4561b6cba9d13d0f711c91bdb38742e2f56d73c8cb596bd06d
MOD="${GAC_VLM_MODEL:-$DEF_MOD}"; PROJ="${GAC_VLM_MMPROJ:-$DEF_PROJ}"
MOD_SHA="${GAC_VLM_MODEL_SHA256:-}"; [ -z "$MOD_SHA" ] && [ "$MOD" = "$DEF_MOD" ] && [ "$REPO" = "Qwen/Qwen3-VL-4B-Instruct-GGUF" ] && MOD_SHA="$DEF_MOD_SHA"
PROJ_SHA="${GAC_VLM_MMPROJ_SHA256:-}"; [ -z "$PROJ_SHA" ] && [ "$PROJ" = "$DEF_PROJ" ] && [ "$REPO" = "Qwen/Qwen3-VL-4B-Instruct-GGUF" ] && PROJ_SHA="$DEF_PROJ_SHA"
export GAC_DEMO="${GAC_DEMO:-1}"

# llama-server only answers requests carrying this random key (new on every start); the app reads VLM_API_KEY
mkdir -p "$MODELS" 2>/dev/null
KEYF="$MODELS/.llama-api-key"
if (umask 077; od -An -tx1 -N32 /dev/urandom | tr -d ' \n' > "$KEYF") 2>/dev/null && [ -s "$KEYF" ]; then
  VLM_API_KEY="$(cat "$KEYF")"; export VLM_API_KEY
else KEYF=""; fi

fetch() {   # fetch FILE SHA256: download into $MODELS, check the hash, keep a .ok marker (no re-hash on the next start)
  f="$1"; sha="$2"; dst="$MODELS/$f"
  if [ -s "$dst" ] && [ -n "$sha" ] && [ "$(cat "$dst.ok" 2>/dev/null)" = "$sha" ]; then return 0; fi
  if [ ! -s "$dst" ]; then
    echo "[ai] downloading $REPO/$f (revision $REV) ..."
    curl -fL --retry 3 -sS -o "$dst.part" "https://huggingface.co/$REPO/resolve/$REV/$f" \
      || { echo "[ai] download of $f failed: rules-only."; rm -f "$dst.part"; return 1; }
    mv "$dst.part" "$dst"
  fi
  if [ -z "$sha" ]; then echo "[ai] WARNING: no sha256 given for $f (custom model): not verified."; return 0; fi
  if echo "$sha  $dst" | sha256sum -c - >/dev/null 2>&1; then echo "$sha" > "$dst.ok"; return 0; fi
  echo "[ai] $f: sha256 does not match the pinned value: deleted, rules-only."; rm -f "$dst" "$dst.ok"; return 1
}

start_ai() {
  [ "${GAC_RULES_ONLY:-0}" = "1" ] && { echo "[ai] GAC_RULES_ONLY=1: AI double-check off (rules-only)."; return; }
  [ -x "$LLAMA_DIR/llama-server" ] || { echo "[ai] llama-server not found in $LLAMA_DIR: rules-only."; return; }
  [ -n "$KEYF" ] || { echo "[ai] could not create the llama-server API key: rules-only."; return; }
  fetch "$PROJ" "$PROJ_SHA" || return
  fetch "$MOD" "$MOD_SHA" || return
  echo "[ai] starting llama-server ($T threads) on 127.0.0.1:8090"
  # -np 1: one AI check at a time; --cache-ram 0: no multi-GB prompt cache in RAM; --no-slots: no /slots endpoint
  LD_LIBRARY_PATH="$LLAMA_DIR:${LD_LIBRARY_PATH:-}" "$LLAMA_DIR/llama-server" -m "$MODELS/$MOD" --mmproj "$MODELS/$PROJ" \
    -c 4096 -t "$T" -tb "$T" -np 1 --cache-ram 0 --no-slots --api-key-file "$KEYF" \
    --host 127.0.0.1 --port 8090 --image-max-tokens 768 \
    || echo "[ai] llama-server exited: rules-only from now on."
}
start_ai &
exec python -m uvicorn app.main:app --host "${GAC_HOST:-0.0.0.0}" --port "$PORT" --workers 1
