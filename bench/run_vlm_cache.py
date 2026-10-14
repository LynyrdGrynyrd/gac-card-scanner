"""Precompute VLM outputs for benchmark images (slow on CPU) so merge logic can be iterated quickly."""
import json, os, sys, time
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
from app import vlm, ocr
gt = json.load(open(sys.argv[1])); d = sys.argv[2]; cdir = os.getenv("VLM_CACHE_DIR") or os.path.join(os.path.dirname(os.path.abspath(__file__)), "vlm_cache"); os.makedirs(cdir, exist_ok=True)
for fn in gt:
    p = os.path.join(cdir, fn + ".json")
    if os.path.exists(p): continue
    data = open(os.path.join(d, fn), "rb").read(); t = time.time()
    try: out = vlm.extract(data, ocr.run_ocr(data)["text"])
    except Exception as e: out = {"_error": str(e)}
    out["_secs"] = round(time.time() - t, 1); json.dump(out, open(p, "w")); print(fn, out["_secs"], flush=True)
