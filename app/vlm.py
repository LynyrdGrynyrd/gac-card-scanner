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
Rules: company is the organization (often the logo text). Copy text exactly as printed on the card; use "" or [] when absent. Do not invent anything.
The OCR often glues or swaps letters (e.g. "Rnbber CityRobotics" for "Rubber City Robotics", "rn" for "m"): read each word from the IMAGE,
and check company and job title as carefully as names. Keep each address line separated by ", ".
title = job role only; department/division/section lines -> department. company = full printed org name, not just the logo word.
Phone type from its label, even in another column (Cell/M -> mobile, F/fx -> fax); a postal code is not a phone.{hints}"""

_S = {"type": "string"}
SCHEMA = {"type": "object", "additionalProperties": False,
          "required": ["first_name", "last_name", "title", "company", "department", "emails", "phones", "website", "address"],
          "properties": {"first_name": _S, "last_name": _S, "title": _S, "company": _S, "department": _S,
                         "emails": {"type": "array", "items": _S, "maxItems": 4},
                         "phones": {"type": "array", "maxItems": 6, "items": {"type": "object", "additionalProperties": False, "required": ["type", "number"],
                                    "properties": {"type": {"enum": ["work", "mobile", "fax", "home"]}, "number": _S}}},
                         "website": _S, "address": _S}}
# Compact instruction (round 6 speed work): same keys/rules, ~45% fewer prompt tokens. VLM_PROMPT=long restores the old one.
PROMPT_SHORT = """Business card photo. Return JSON: first_name, last_name, title, company, department, emails, phones (type work|mobile|fax|home + number), website, address.
Copy text exactly as printed; company = organization (often the logo). Use "" or [] when absent; never invent.
OCR hint (may have errors):
{ocr}"""
PROMPT_RULES_LONG = """
title = the job role only (e.g. "Director"); lines naming a department, division, section, program or lab go in department (join several with ", ").
company = the full organization name as printed in the text (e.g. "Acme Americas, Inc."), not just the logo word, when it is printed.
phones: take the type from the printed label even when it is in a separate column (Cell/C/M/Mobile -> mobile; F/Fax/fx -> fax); a postal code is not a phone."""
STRICT = os.getenv("VLM_SCHEMA", "1") == "1"   # llama.cpp grammar-constrained decoding: output always matches SCHEMA

def available(timeout=1.5):
    try: return json.loads(urllib.request.urlopen(URL + "/health", timeout=timeout).read()).get("status") == "ok"
    except Exception: return False

MAX_SIDE = int(os.getenv("VLM_MAX_SIDE", "896"))     # longest image side sent; Qwen3-VL ~ (w/32)*(h/32) image tokens
MAX_TOKENS = int(os.getenv("VLM_MAX_TOKENS", "400"))
OCR_CHARS = int(os.getenv("VLM_OCR_CHARS", "1500"))
LAST = {}   # server timings of the last call (prompt_n, prompt_ms, predicted_n, predicted_ms) for benchmarks / ETA

def _prep(data: bytes, max_side: int, crop: bool):
    img = ImageOps.exif_transpose(Image.open(io.BytesIO(data))).convert("RGB")
    if crop:   # send only the card (perspective crop already used by the OCR pass) instead of the whole photo
        try:
            from . import ocr
            img, _ = ocr.crop_card(img)
        except Exception: pass
    img.thumbnail((max_side, max_side)); return img

ALL_KEYS = ["first_name", "last_name", "title", "company", "department", "emails", "phones", "website", "address"]
WHY_KEYS = {"name": ["first_name", "last_name"], "company": ["company"], "title": ["title"], "emails": ["emails"], "phones": ["phones"]}

def keys_for(why, fields=None):
    """Only ask the model for what needs checking (fewer output tokens = the biggest time saving on CPU):
    the uncertain fields (ai_reason) + fields the fast pass left empty. None = everything."""
    if not why or any(w not in WHY_KEYS for w in why): return None
    ks = [k for w in why for k in WHY_KEYS[w]]
    for k in ALL_KEYS:
        if fields is not None and not fields.get(k) and k not in ks: ks.append(k)
    if "first_name" in ks and "last_name" not in ks: ks.append("last_name")
    return [k for k in ALL_KEYS if k in ks]

def _schema(keys):
    return dict(SCHEMA, required=keys, properties={k: SCHEMA["properties"][k] for k in keys})

def _hint_text(hints):
    return ("\nThe scanner's checks flagged (verify these against the image): " + hints[:600]) if hints else ""

def _prompt_for(keys, ocr_text, hints=""):
    if os.getenv("VLM_PROMPT", "long") == "long": return PROMPT.format(ocr=ocr_text[:OCR_CHARS], hints=_hint_text(hints))
    if keys is None: return PROMPT_SHORT.format(ocr=ocr_text[:OCR_CHARS]) + _hint_text(hints)
    want = ", ".join("phones (type work|mobile|fax|home + number)" if k == "phones" else k for k in keys)
    return PROMPT_SHORT.replace("first_name, last_name, title, company, department, emails, phones (type work|mobile|fax|home + number), website, address", want).format(ocr=ocr_text[:OCR_CHARS]) + _hint_text(hints)

def extract(data: bytes, ocr_text: str = "", max_side=None, timeout=int(os.getenv("VLM_TIMEOUT", "240")), keys=None, hints=""):
    LAST.clear()
    img = _prep(data, max_side or MAX_SIDE, os.getenv("VLM_CROP", "0") == "1")
    b = io.BytesIO(); img.save(b, "JPEG", quality=90)
    prompt = _prompt_for(keys, ocr_text, hints); schema = SCHEMA if keys is None else _schema(keys)
    body = {"messages": [{"role": "user", "content": [
                {"type": "image_url", "image_url": {"url": "data:image/jpeg;base64," + base64.b64encode(b.getvalue()).decode()}},
                {"type": "text", "text": prompt}]}],
            "temperature": 0, "max_tokens": MAX_TOKENS, "cache_prompt": True, "response_format": ({"type": "json_schema", "json_schema": {"name": "card", "strict": True, "schema": schema}}
                                if STRICT else {"type": "json_object"})}
    req = urllib.request.Request(URL + "/v1/chat/completions", json.dumps(body).encode(), {"Content-Type": "application/json"})
    resp = json.loads(urllib.request.urlopen(req, timeout=timeout).read())
    LAST.clear(); LAST.update(resp.get("timings") or {}); LAST["img"] = img.size
    out = resp["choices"][0]["message"]["content"]
    m = re.search(r"\{.*\}", out, re.S)
    return json.loads(m.group(0)) if m else {}
