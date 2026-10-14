# Open-source survey: what to borrow for the card scanner
Surveyed 2026-10-13. Stars / last push / license come from the GitHub REST API on that date (`api.github.com/repos/<owner>/<repo>`). "NOASSERTION" means GitHub could not detect a single standard license; the notes give the real terms where known.
**Fit** = how well it matches this project (CPU-only, local, Python, small office pilot). **Rec** = adopt / try / skip.
Benchmark numbers come from `bench/` (26 real cards × 10 fields, plus 48 synth2 cards). Full logs are in ITERATIONS.md, iteration 10.

**License policy (from the user, 2026-10-13):** this is an internal tool, so GPL/AGPL components are acceptable but are flagged ⛔ here and in THIRD-PARTY-NOTICES.md.
**License key:** ✅ permissive (MIT/Apache/BSD/Unlicense). ⚠️ weak copyleft (LGPL/MPL): OK as an unmodified dependency, but keep notices. ⛔ strong copyleft (GPL/AGPL), no license, or non-commercial model weights: do not bundle.

## 1. Business-card scanners / parsers (existing projects)
| Name | Link | ★ | Last push | License | Fit | Rec |
|---|---|---|---|---|---|---|
| syneo-tools Javascript-BCR-Library | github.com/syneo-tools-gmbh/Javascript-BCR-Library | 45 | 2020-02 | ✅ Apache-2.0 | Tesseract.js + regex; ours is already far ahead | skip |
| danauclair/CardScan | github.com/danauclair/CardScan | 57 | 2011-03 | ✅ MIT | old C++ Tesseract demo | skip |
| adityamehra/Business-Card-Reader-BCR- | github.com/adityamehra/Business-Card-Reader-BCR- | 78 | 2019-10 | ⛔ none | Android, name/email/phone only | skip |
| stpabhi/business-card-scanner | github.com/stpabhi/business-card-scanner | 24 | 2022-10 | ✅ Apache-2.0 | iOS Tesseract | skip |
| NanoNets ocr sample | github.com/NanoNets/nanonets-ocr-sample-python | 209 | 2022-03 | ⛔ none | needs a cloud API | skip |
| BizCardX / misc student repos (easyOCR + regex) | github.com/IamJafar/BizCardX-… | <20 | 2023 | ⛔ none | toy projects | skip |
Finding: no well-maintained, popular OSS business-card parser exists. The useful material is in the general components below.

## 2. Contact / NER extraction
| Name | Link | ★ | Last push | License | Fit | Rec |
|---|---|---|---|---|---|---|
| GLiNER (gliner_small/medium/multi-v2.1) | github.com/urchade/GLiNER | 4,091 | 2026-10-05 | ✅ Apache-2.0 (the urchade *-v2.1 weights are Apache; ⛔ `gliner_base`/v1 weights are CC-BY-NC) | zero-shot person/title/org spans; needs torch (~1 GB) | try (optional; tested, see §Results) |
| spaCy | github.com/explosion/spaCy | 33,957 | 2026-10-12 | ✅ MIT | generic NER; weak on card fragments with no sentence context | skip |
| flair | github.com/flairNLP/flair | 14,392 | 2025-10-27 | ✅ MIT (NOASSERTION on GitHub) | heavy torch models; slower than GLiNER | skip |
| NuExtract (NuMind) | github.com/numindai/nuextract | 264 | 2026-08-17 | ✅ MIT code; check each model card | small LLM for JSON extraction; overlaps the VLM we already run | skip |

## 3. Name parsing
| Name | Link | ★ | Last push | License | Fit | Rec |
|---|---|---|---|---|---|---|
| python-nameparser | github.com/derek73/python-nameparser | 718 | 2026-10-13 | ⚠️ LGPL-2.1 | title/suffix splitting | skip (not needed; LGPL) |
| probablepeople | github.com/datamade/probablepeople | 623 | 2025-05-15 | ✅ MIT | CRF name tagger | skip (tested: −1 on real set) |

## 4. Address parsing
| Name | Link | ★ | Last push | License | Fit | Rec |
|---|---|---|---|---|---|---|
| usaddress | github.com/datamade/usaddress | 1,637 | 2025-08-07 | ✅ MIT | US-only CRF tagger, light | skip for now (tested: +1 only because it drops "U.S.A.", which is a ground-truth convention) |
| libpostal / pypostal | github.com/openvenues/libpostal | 4,907 / 877 | 2026-05 / 2025-11 | ✅ MIT | best international parser, but needs a ~2 GB model and a C build | try later, if international cards matter |
| deepparse | github.com/GRAAL-Research/deepparse | 354 | 2026-10-01 | ⚠️ LGPL-3.0 | torch seq2seq address parser | skip |

## 5. Phone / email
| Name | Link | ★ | Last push | License | Fit | Rec |
|---|---|---|---|---|---|---|
| python-phonenumbers (libphonenumber port) | github.com/daviddrysdale/python-phonenumbers | 3,774 | 2026-10-08 | ✅ Apache-2.0 | already used | keep |
| google/libphonenumber | github.com/google/libphonenumber | 18,313 | 2026-10-08 | ✅ Apache-2.0 | upstream | — |
| email-validator | github.com/JoshData/python-email-validator | 1,449 | 2026-10-01 | ✅ Unlicense | syntax/IDN checks; optional DNS (off-box, so not wanted) | try (cheap; syntax checks only) |

## 6. OCR engines
| Name | Link | ★ | Last push | License | Fit | Rec |
|---|---|---|---|---|---|---|
| Tesseract | github.com/tesseract-ocr/tesseract | 76,972 | 2026-10-10 | ✅ Apache-2.0 | current recognizer | keep |
| RapidOCR (PP-OCR in ONNX) | github.com/RapidAI/RapidOCR | 8,130 | 2026-10-13 | ✅ Apache-2.0 | current detector (rapidocr-onnxruntime 1.2.3). Tested v3 with PP-OCRv4/v5 | keep 1.2.x (v5 tested worse) |
| PaddleOCR (PP-OCRv5) | github.com/PaddlePaddle/PaddleOCR | 91,035 | 2026-09-16 | ✅ Apache-2.0 | used through RapidOCR's ONNX ports instead (no paddle runtime) | via RapidOCR |
| docTR | github.com/mindee/doctr | 6,385 | 2026-10-13 | ✅ Apache-2.0 | torch; tested fast_base + crnn_vgg16_bn | skip (−4 vs same-env baseline, 2× slower; emails were better) |
| EasyOCR | github.com/JaidedAI/EasyOCR | 30,064 | 2025-12-05 | ✅ Apache-2.0 | torch, CRAFT; generally below PP-OCR on Latin text | skip |
| Surya | github.com/datalab-to/surya | 21,490 | 2026-09-11 | ✅ Apache-2.0 code; ⛔ model weights under a modified OpenRAIL-M (revenue cap for commercial use) | strong, but ~1.5 GB torch models and slow on CPU | skip (license + RAM) |
| Marker | github.com/datalab-to/marker | 40,426 | 2026-10-02 | same as Surya ⛔ weights | PDF → markdown | skip |
| OCRmyPDF | github.com/ocrmypdf/OCRmyPDF | 35,015 | 2026-10-12 | ⚠️ MPL-2.0 | PDF wrapper around Tesseract | skip |
| GOT-OCR2.0 | github.com/Ucas-HaoranWei/GOT-OCR2.0 | 8,223 | 2025-02-10 | ⛔ no license file | 580M VLM-OCR, GPU-oriented | skip |
| olmOCR | github.com/allenai/olmocr | 19,740 | 2026-03-25 | ✅ Apache-2.0 | 7B VLM, GPU | skip |
| MinerU | github.com/opendatalab/MinerU | 81,658 | 2026-10-12 | ⛔ custom license (AGPL-derived history; NOASSERTION) | PDF pipelines | skip |
| Florence-2 (HF model) | huggingface.co/microsoft/Florence-2-base | — | 2024 | ✅ MIT weights | 0.23B OCR+region model, torch, trust_remote_code | try later |

## 7. Document-understanding models
| Name | Link | ★ | Last push | License | Fit | Rec |
|---|---|---|---|---|---|---|
| Donut | github.com/clovaai/donut | 6,928 | 2024-07-11 | ✅ MIT | OCR-free; would need fine-tuning on cards | skip |
| LayoutLMv3 (microsoft/unilm) | github.com/microsoft/unilm | 22,234 | 2026-09-21 | ✅ MIT code, ⛔ LayoutLMv3 weights CC-BY-NC-SA | | skip (license) |
| Nougat | github.com/facebookresearch/nougat | 10,082 | 2025-02-21 | ✅ MIT code, ⛔ weights CC-BY-NC | academic PDFs | skip |

## 8. Small VLMs (local)
| Name | Link | ★ | Last push | License | Fit | Rec |
|---|---|---|---|---|---|---|
| Qwen2.5-VL 3B (current) / 7B; Qwen3-VL | github.com/QwenLM/Qwen3-VL | 20,071 | 2026-01-30 | ⚠️ 3B weights: Qwen Research License (non-commercial!); ✅ 7B/72B and Qwen3-VL weights are Apache-2.0 | 7B is ~2.5× slower on CPU | **caution**: see the license notes below. Try Qwen3-VL-2B/4B (Apache) as a drop-in GGUF |
| SmolVLM / SmolVLM2 | github.com/huggingface/smollm | 3,923 | 2026-10-06 | ✅ Apache-2.0 | 256M–2.2B, GGUF exists; weaker at dense OCR | try as a fast fallback |
| Moondream2 | github.com/vikhyat/moondream | 10,105 | 2026-04-20 | ✅ Apache-2.0 | 1.9B, decent OCR | try |
| MiniCPM-V | github.com/OpenBMB/MiniCPM-V | 26,672 | 2026-10-13 | ⚠️ code Apache; weights under the MiniCPM model license (free commercial use requires registration) | strong OCR, 8B | skip |
| InternVL | github.com/OpenGVLab/InternVL | 10,166 | 2025-09-22 | ✅ MIT code; weights mostly MIT/Apache (check the LLM part) | InternVL3-1B/2B GGUF | try |
| llama.cpp | github.com/ggml-org/llama.cpp | 131,069 | 2026-10-13 | ✅ MIT | current server | keep |

## 9. Structured output
| Name | Link | ★ | Last push | License | Fit | Rec |
|---|---|---|---|---|---|---|
| llama.cpp JSON-schema → GBNF grammar (`response_format: json_schema`) | github.com/ggml-org/llama.cpp | (above) | | ✅ MIT | zero new dependencies | **adopt** (tested, see §Results) |
| outlines | github.com/dottxt-ai/outlines | 15,925 | 2026-09-21 | ✅ Apache-2.0 | same idea, client-side | skip (llama.cpp does it server-side) |
| instructor | github.com/567-labs/instructor | 14,007 | 2026-10-11 | ✅ MIT | pydantic + retries | skip (not needed with a grammar) |
| guidance | github.com/guidance-ai/guidance | 21,796 | 2026-05-21 | ✅ MIT | | skip |

## 10. Image preprocessing
| Name | Link | ★ | Last push | License | Fit | Rec |
|---|---|---|---|---|---|---|
| OpenCV | github.com/opencv/opencv | 91,170 | 2026-10-13 | ✅ Apache-2.0 | already used (perspective crop, `ocr.crop_card`) | keep |
| OpenCV-Document-Scanner | github.com/andrewdcampbell/OpenCV-Document-Scanner | 644 | 2022-10 | ⛔ no license | same contour + warp approach we already have | skip |
| rembg (u2netp / isnet) | github.com/danielgatis/rembg | 25,064 | 2026-10-10 | ✅ MIT (u2net weights Apache) | mask-based card crop | skip (tested: −1 / −2) |
| docuwarp / DocUNet dewarping | — | — | — | — | cards are flat; little value | skip |
| zxing-cpp | github.com/zxing-cpp/zxing-cpp | 2,053 | 2026-10-06 | ✅ Apache-2.0 | already used for QR | keep |

## 11. Dedupe / entity resolution
| Name | Link | ★ | Last push | License | Fit | Rec |
|---|---|---|---|---|---|---|
| RapidFuzz | github.com/rapidfuzz/RapidFuzz | 4,162 | 2026-10-12 | ✅ MIT | drop-in for difflib; token_sort handles swapped names | **adopt** (tested) |
| splink | github.com/moj-analytical-services/splink | 2,477 | 2026-10-13 | ✅ MIT | probabilistic linkage at scale (DuckDB) | try when matching against a full MC Trade export |
| dedupe | github.com/dedupeio/dedupe | 4,517 | 2025-07-29 | ✅ MIT | active-learning linkage | skip |
| recordlinkage | github.com/J535D165/recordlinkage | 1,063 | 2024-02-21 | ✅ BSD-3 | lightly maintained | skip |
| thefuzz | github.com/seatgeek/thefuzz | 3,651 | 2025-03-03 | ✅ MIT | thin wrapper over RapidFuzz | skip |

## 12. Labeling tools and review-queue apps
| Name | Link | ★ | Last push | License | Fit | Rec |
|---|---|---|---|---|---|---|
| Label Studio | github.com/HumanSignal/label-studio | 28,458 | 2026-10-13 | ✅ Apache-2.0 | good for building ground truth (image + per-field text) for more benchmark cards | try (for the data team, not bundled) |
| doccano | github.com/doccano/doccano | 10,797 | 2026-04-14 | ✅ MIT | text-only labeling | skip |
| full-stack-fastapi-template | github.com/fastapi/full-stack-fastapi-template | 45,971 | 2026-10-08 | ✅ MIT | reference for auth/users if the app grows | reference only |
| paperless-ngx | github.com/paperless-ngx/paperless-ngx | 46,626 | 2026-10-13 | ⛔ GPL-3.0 | document OCR + review inbox UX; read for ideas only, do not copy code | skip (code) |
| Stirling-PDF | github.com/Stirling-Tools/Stirling-PDF | 94,130 | 2026-10-13 | ⛔ mixed (MIT core + proprietary parts) | | skip |

## 13. Public business-card datasets
| Dataset | Link | Size | License | Notes |
|---|---|---|---|---|
| EATEN business-card set | github.com/beacandler/EATEN | 200k **synthetic** Chinese cards | research | entity labels; Chinese, so not representative |
| ilovelevi/business_card_dataset | huggingface.co/datasets/ilovelevi/business_card_dataset | small, images only | not stated ⛔ | no field labels |
| Ultralytics "business-cards" | platform.ultralytics.com/development-stride/datasets/business-cards | 400 images | not stated | box-detection labels only, not fields |
| SROIE / CORD (receipts) | github.com/zzzDavid/ICDAR-2019-SROIE, github.com/clovaai/cord | 1k each | MIT / CC-BY-4.0 | receipts, not cards; useful only for OCR sanity checks |
| Wikimedia Commons "Business cards" category (current source of bench/real) | commons.wikimedia.org | ~100s | per-file CC licenses | best real source; extend `bench/fetch_commons.py` and label with Label Studio |
Finding: there is no public, field-labeled, English business-card set. The best path to more benchmark data is (a) more Commons cards and (b) the pilot's own `bench/corrections` (reviewer-approved scans).

## Results of hands-on tests (details in ITERATIONS.md, iteration 10)
Real set = 26 cards × 10 fields. Baseline in the project venv: 222/260 rules-only, 238/260 with the VLM. The OCR, crop and rembg experiments ran in a separate venv (`/workspace/ossvenv`, newer wheels) whose own unmodified baseline is **215/260**, so compare those rows with 215.
| Candidate | Result | Decision |
|---|---|---|
| RapidOCR v3, PP-OCRv5 det+rec (± no Tesseract) | 203/260 (synth2 450–452/480 vs 466) | skip |
| RapidOCR v3, PP-OCRv4 + EN rec | 212/260 | skip |
| docTR fast_base + crnn_vgg16_bn | 211/260, 7 s/card. Emails 26/26 (better), names worse | skip |
| rembg u2netp / isnet card crop | 213 / 214 | skip |
| GLiNER small/medium/multi (company spans) | medium: rules-only company 13→16 (only when it *extends* the rules value); synth2 unchanged; 0 gain once the VLM is on; needs torch | try later (optional, rules-only installs) |
| usaddress trim | +1 (only by dropping "U.S.A.", a ground-truth convention) | skip |
| probablepeople | −1 | skip |
| **llama.cpp JSON-schema grammar** | 0/26 malformed VLM outputs (was 4 broken + 1 error + 6 wrong-typed of 26); 238→240 with the website guard; median time unchanged (~23 s) | **adopted** |
| **RapidFuzz token_sort for duplicate matching** | recall 136→144/222 on a perturbed-card duplicate test (swapped first/last name); 0 new false matches; ~7× faster | **adopted** |
| Qwen3-VL-4B-Instruct Q4_K_M (Apache-2.0) vs Qwen2.5-VL-3B (research license) | **242/260 (93.1%) vs 240/260**, same speed (~24 s median), ~3 GB RAM | **recommended swap**; not done on the live server (operator change) |

## Ideas borrowed (not just libraries)
| From | What was borrowed | Where |
|---|---|---|
| llama.cpp grammars / outlines / instructor ("schema-first extraction") | the VLM output contract is a JSON Schema (enum phone types, required keys, no extra keys, max list sizes), enforced at decode time instead of repaired afterwards | `app/vlm.py` (`SCHEMA`, `VLM_SCHEMA=1` default) |
| instructor ("validate model output against evidence") | VLM website accepted only if it is a well-formed domain printed outside an email address | `app/merge.py`, website block |
| splink / dedupe (comparison levels, order-insensitive name comparison, an explainable score) | token-sorted name similarity, separate email, phone, name and org evidence with a `why` list; RapidFuzz scorers | `app/mctrade_sync.py` (`match`) |
| Label Studio / paperless-ngx review UX | already present: per-field source badges, confidence-driven "needs attention", keyboard review, undo. Next to borrow: Label Studio's *ground-truth export* of reviewer-approved cards for benchmarking, and paperless-ngx's "suggestions you can accept" pattern (the AI-suggested diff already follows it) | recommendation (`bench/corrections` is the hook) |
| splink (next step) | when a full MC Trade export is available: blocking on email domain / last-name initial, then probabilistic matching | recommendation |
