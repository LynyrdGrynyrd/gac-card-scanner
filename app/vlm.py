"""Optional local vision-LLM extractor (default Qwen3-VL-4B-Instruct GGUF, Apache-2.0; fallback Qwen2.5-VL-3B, research license; via llama.cpp llama-server, OpenAI-compatible API).
Runs fully local. Enable with VLM_URL (default http://127.0.0.1:8090). Never sends data off-box."""
import base64, io, json, os, re, urllib.request
from PIL import Image, ImageOps
URL = os.getenv("VLM_URL", "http://127.0.0.1:8090")
PROMPT = """You are reading a business card photo. OCR text (may contain errors) is given as a hint:
---
{ocr}
---
Return ONLY a JSON object with keys:
first_name, last_name, title, company, department, emails (list), phones (list of {{"type": "work|mobile|fax|home", "number": "..."}}), website, address.
Rules: company is the organization (often the logo text). Copy text exactly as printed on the card; use "" or [] when absent. Do not invent anything."""

_S = {"type": "string"}
SCHEMA = {"type": "object", "additionalProperties": False,
          "required": ["first_name", "last_name", "title", "company", "department", "emails", "phones", "website", "address"],
          "properties": {"first_name": _S, "last_name": _S, "title": _S, "company": _S, "department": _S,
                         "emails": {"type": "array", "items": _S, "maxItems": 4},
                         "phones": {"type": "array", "maxItems": 6, "items": {"type": "object", "additionalProperties": False, "required": ["type", "number"],
                                    "properties": {"type": {"enum": ["work", "mobile", "fax", "home"]}, "number": _S}}},
                         "website": _S, "address": _S}}
STRICT = os.getenv("VLM_SCHEMA", "1") == "1"   # llama.cpp grammar-constrained decoding: output always matches SCHEMA

def available(timeout=1.5):
    try: return json.loads(urllib.request.urlopen(URL + "/health", timeout=timeout).read()).get("status") == "ok"
    except Exception: return False

def extract(data: bytes, ocr_text: str = "", max_side=896, timeout=int(os.getenv("VLM_TIMEOUT", "90"))):
    img = ImageOps.exif_transpose(Image.open(io.BytesIO(data))).convert("RGB"); img.thumbnail((max_side, max_side))
    b = io.BytesIO(); img.save(b, "JPEG", quality=90)
    body = {"messages": [{"role": "user", "content": [
                {"type": "image_url", "image_url": {"url": "data:image/jpeg;base64," + base64.b64encode(b.getvalue()).decode()}},
                {"type": "text", "text": PROMPT.format(ocr=ocr_text[:1500])}]}],
            "temperature": 0, "max_tokens": 400, "response_format": ({"type": "json_schema", "json_schema": {"name": "card", "strict": True, "schema": SCHEMA}}
                                if STRICT else {"type": "json_object"})}
    req = urllib.request.Request(URL + "/v1/chat/completions", json.dumps(body).encode(), {"Content-Type": "application/json"})
    out = json.loads(urllib.request.urlopen(req, timeout=timeout).read())["choices"][0]["message"]["content"]
    m = re.search(r"\{.*\}", out, re.S)
    return json.loads(m.group(0)) if m else {}
