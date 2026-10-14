#!/bin/bash
# Optional: starts the local "AI double-check" vision model on 127.0.0.1:8090.
# Default: Qwen3-VL-4B-Instruct (Apache-2.0). Needs a models/ folder (or GAC_MODELS=/path) with llama-server and:
#   Qwen3VL-4B-Instruct-Q4_K_M.gguf + mmproj-Qwen3VL-4B-Instruct-Q8_0.gguf  (huggingface.co/Qwen/Qwen3-VL-4B-Instruct-GGUF)
# Fallback (documented only; Qwen Research License = non-commercial): GAC_VLM=qwen25-3b uses
#   Qwen2.5-VL-3B-Instruct-Q4_K_M.gguf + mmproj-Qwen2.5-VL-3B-Instruct-Q8_0.gguf
M="${GAC_MODELS:-$(cd "$(dirname "$0")" && pwd)/models}"; [ -d "$M" ] || M=/workspace/models
cd "$M" || { echo "No models folder found - AI double-check stays off (scanning still works)."; exit 0; }
SRV=$(ls -d llama-*/llama-server llama-server 2>/dev/null | head -1)
if [ "${GAC_VLM:-qwen3-4b}" = "qwen25-3b" ]; then
  MOD=Qwen2.5-VL-3B-Instruct-Q4_K_M.gguf; PROJ=mmproj-Qwen2.5-VL-3B-Instruct-Q8_0.gguf
else
  MOD=Qwen3VL-4B-Instruct-Q4_K_M.gguf; PROJ=mmproj-Qwen3VL-4B-Instruct-Q8_0.gguf
fi
[ -f "$MOD" ] || { echo "Model file $MOD not found in $M - AI double-check stays off (scanning still works)."; exit 0; }
# -np 1: the app sends one AI check at a time, so one slot. -c 2048 fits image (<=~450 tokens at 640 px) + prompt + answer.
# --cache-ram 0: llama.cpp otherwise keeps up to 8 GB of prompt cache in RAM (caused out-of-memory kills on a 16 GB machine).
# Threads: GAC_AI_THREADS (default 8; use the number of performance cores).
exec "./$SRV" -m "$MOD" --mmproj "$PROJ" -c 2048 -np 1 --cache-ram 0 -t "${GAC_AI_THREADS:-8}" --host 127.0.0.1 --port 8090 --image-max-tokens "${GAC_AI_IMAGE_TOKENS:-768}"
