#!/bin/sh
# Start script for the public demo (HF Space or any box). Runs the app on $PORT (default 7860) in demo mode and,
# in the background, downloads Qwen3-VL-4B-Instruct GGUF from Hugging Face and starts llama-server on 127.0.0.1:8090.
# Any failure there leaves the AI double-check off: scanning works rules-only (OCR + parser).
# GAC_RULES_ONLY=1 skips the model entirely (useful on small machines / for smoke tests).
set -u
PORT="${PORT:-7860}"; MODELS="${MODELS:-$(pwd)/models}"; LLAMA_DIR="${LLAMA_DIR:-/opt/llama}"; T="${LLAMA_THREADS:-2}"
REPO="${GAC_VLM_REPO:-Qwen/Qwen3-VL-4B-Instruct-GGUF}"
MOD="${GAC_VLM_MODEL:-Qwen3VL-4B-Instruct-Q4_K_M.gguf}"; PROJ="${GAC_VLM_MMPROJ:-mmproj-Qwen3VL-4B-Instruct-Q8_0.gguf}"
export GAC_DEMO="${GAC_DEMO:-1}"

start_ai() {
  [ "${GAC_RULES_ONLY:-0}" = "1" ] && { echo "[ai] GAC_RULES_ONLY=1: AI double-check off (rules-only)."; return; }
  [ -x "$LLAMA_DIR/llama-server" ] || { echo "[ai] llama-server not found in $LLAMA_DIR: rules-only."; return; }
  mkdir -p "$MODELS" || return
  for f in "$MOD" "$PROJ"; do
    if [ ! -s "$MODELS/$f" ]; then
      echo "[ai] downloading $REPO/$f ..."
      curl -fL --retry 3 -sS -o "$MODELS/$f.part" "https://huggingface.co/$REPO/resolve/main/$f" && mv "$MODELS/$f.part" "$MODELS/$f" \
        || { echo "[ai] download of $f failed: rules-only."; rm -f "$MODELS/$f.part"; return; }
    fi
  done
  echo "[ai] starting llama-server ($T threads) on 127.0.0.1:8090"
  LD_LIBRARY_PATH="$LLAMA_DIR:${LD_LIBRARY_PATH:-}" "$LLAMA_DIR/llama-server" -m "$MODELS/$MOD" --mmproj "$MODELS/$PROJ" \
    -c 4096 -t "$T" -tb "$T" -np 1 --host 127.0.0.1 --port 8090 --image-max-tokens 768 \
    || echo "[ai] llama-server exited: rules-only from now on."
}
start_ai &
exec python -m uvicorn app.main:app --host "${GAC_HOST:-0.0.0.0}" --port "$PORT" --workers 1
