# Third-party notices
GAC Card Scanner is licensed **GPL-3.0-or-later** (see `LICENSE`). It is built on the open-source components below; each one keeps its own license. The desktop installers and the Docker images ship this file and `LICENSE`. The license texts of the components are at the linked projects. A source install also has each Python package's license file in that package's `*.dist-info` folder in the virtual environment. The desktop installers additionally carry Tesseract's license files in the app's `tesseract` folder (see "Desktop installers" below).

**GPL components:** gender-guesser (GPL-3.0) and the x265 encoder inside the pillow-heif wheel (GPL-2.0). Both are compatible with the project's own GPL-3.0-or-later license. Anyone who redistributes the installers or images must follow GPL-3.0 (the corresponding source is this repository at the release tag). GPL/AGPL components are flagged whenever they are added (see OSS-SURVEY.md; for example paperless-ngx GPL-3.0 and MinerU AGPL-derived were reviewed for ideas only, and no code was copied).

## Python runtime dependencies (requirements.txt; versions from requirements.lock.txt)
| Component | Version tested | License | Project |
|---|---|---|---|
| FastAPI | 0.143.0 | MIT | github.com/fastapi/fastapi |
| Starlette | 1.8.0 | BSD-3-Clause | github.com/Kludex/starlette |
| Pydantic | 2.14.1 | MIT | github.com/pydantic/pydantic |
| Uvicorn | 0.54.0 | BSD-3-Clause | github.com/encode/uvicorn |
| python-multipart | 0.0.32 | Apache-2.0 | github.com/Kludex/python-multipart |
| pytesseract | 0.3.13 | Apache-2.0 | github.com/madmaze/pytesseract |
| phonenumbers (port of Google libphonenumber) | 9.0.41 | Apache-2.0 | github.com/daviddrysdale/python-phonenumbers |
| Pillow | 13.0.0 | MIT-CMU (HPND) | github.com/python-pillow/Pillow |
| openpyxl | 3.1.5 | MIT | foss.heptapod.net/openpyxl/openpyxl |
| NumPy | 2.5.4 | BSD-3-Clause (+ bundled 0BSD/MIT/Zlib/CC0 parts) | github.com/numpy/numpy |
| OpenCV (opencv-python-headless) | 5.0.0.93 | Apache-2.0; the wheel bundles third-party libraries listed in `cv2/LICENSE-3RD-PARTY.txt`, including FFmpeg (LGPL-2.1+); the headless build has no Qt | github.com/opencv/opencv-python |
| ONNX Runtime | 1.31.0 | MIT (third-party notices in `onnxruntime/ThirdPartyNotices.txt`) | github.com/microsoft/onnxruntime |
| RapidOCR (rapidocr) + bundled PP-OCRv6 small det/rec and PP-OCR mobile angle-classifier ONNX models (PaddleOCR; see `MODEL_LICENSES.md` in the wheel's `rapidocr-*.dist-info/licenses/`) | 3.10.0 | Apache-2.0 (code and models) | github.com/RapidAI/RapidOCR, github.com/PaddlePaddle/PaddleOCR |
| zxing-cpp | 3.1.1 | Apache-2.0 | github.com/zxing-cpp/zxing-cpp |
| cryptography | 50.0.2 | Apache-2.0 OR BSD-3-Clause | github.com/pyca/cryptography |
| RapidFuzz (duplicate matching) | 3.14.6 | MIT | github.com/rapidfuzz/RapidFuzz |
| qrcode (phone-mode pairing QR code, app/phone.py) | 8.2 | BSD-3-Clause | github.com/lincolnloop/python-qrcode |
| **gender-guesser** (first-name lexicon for name ordering, app/parser.py) | 0.4.0 | **GPL-3.0** | github.com/lead-ratings/gender-guesser |
| **pillow-heif** (HEIC/HEIF photo input, app/formats.py) | 1.8.1 | **GPL-2.0** as shipped (the binary wheel bundles the **x265** encoder, GPL-2.0); Python bindings BSD-3-Clause | github.com/bigcat88/pillow_heif |
| - **libheif** (bundled in the pillow-heif wheel) | 1.23.6 | **LGPL-3.0** | github.com/strukturag/libheif |
| - **libde265** (bundled in the pillow-heif wheel) | 1.1.3 | **LGPL-3.0** | github.com/strukturag/libde265 |
| - **x265** (bundled in the pillow-heif wheel) | 4.3 | **GPL-2.0** | github.com/Multicorewareinc/x265 |
| pypdfium2 (PDF input, app/formats.py) | 5.14.0 | Apache-2.0 / BSD-3-Clause; bundles PDFium (BSD-3-Clause / Apache-2.0) and its deps (FreeType, ICU, libjpeg-turbo, OpenJPEG, libpng, zlib, lcms: permissive) | github.com/pypdfium2-team/pypdfium2 |

### Installed with them (transitive packages in requirements.lock.txt)
Generated with `pip-licenses` 5.5.5 from a clean install of `requirements.lock.txt` (Linux, Python 3.12).

| Package | Version | License | Needed by |
|---|---|---|---|
| annotated-doc | 0.0.5 | MIT | fastapi |
| annotated-types | 0.8.0 | MIT | pydantic |
| anyio | 4.15.1 | MIT | starlette |
| certifi | 2026.7.22 | MPL-2.0 | requests |
| cffi | 2.1.1 | MIT-0 | cryptography |
| charset-normalizer | 3.5.2 | MIT | requests |
| click | 8.5.0 | BSD-3-Clause | uvicorn |
| colorama (Windows only) | 0.4.6 | BSD-3-Clause | qrcode, click, colorlog, tqdm |
| colorlog | 6.12.0 | MIT | rapidocr |
| et-xmlfile | 2.0.0 | MIT | openpyxl |
| flatbuffers | 25.12.19 | Apache-2.0 | onnxruntime |
| h11 | 0.16.0 | MIT | uvicorn |
| idna | 3.20 | BSD-3-Clause | anyio, requests |
| omegaconf | 2.4.0 | BSD-3-Clause | rapidocr |
| opentelemetry-api | 1.45.1 | Apache-2.0 | fastapi |
| packaging | 26.3 | Apache-2.0 OR BSD-2-Clause | onnxruntime, pytesseract |
| protobuf | 7.36.2 | BSD-3-Clause | onnxruntime |
| pyclipper | 1.4.0 | MIT (Clipper library: BSL-1.0) | rapidocr |
| pycparser | 3.11 | BSD-3-Clause | cffi |
| pydantic-core | 2.50.1 | MIT | pydantic |
| PyYAML | 6.0.3 | MIT | rapidocr, omegaconf |
| shapely (bundles GEOS, LGPL-2.1) | 2.2.0 | BSD-3-Clause | rapidocr |
| requests | 2.34.2 | Apache-2.0 | rapidocr (never used to download models: app/ocr.py passes the bundled model paths) |
| six | 1.17.0 | MIT | rapidocr |
| tqdm | 4.70.1 | MPL-2.0 AND MIT | rapidocr |
| typing-extensions | 4.16.0 | PSF-2.0 | pydantic, fastapi, ... |
| typing-inspection | 0.4.4 | MIT | pydantic, fastapi |
| urllib3 | 2.8.0 | MIT | requests |

## Desktop installers (Windows .exe, macOS .dmg): also bundled
| Component | License | Notes |
|---|---|---|
| CPython 3.12 (the Python runtime, with its standard library and the libraries it ships: OpenSSL, SQLite, zlib, libffi, expat, bzip2, xz/liblzma, mpdecimal) | PSF-2.0 (OpenSSL: Apache-2.0; SQLite: public domain; the others MIT/BSD-style) | python.org; license text: docs.python.org/3/license.html |
| PyInstaller bootloader (the small program that starts the bundled app) | GPL-2.0-or-later **with the bootloader exception**, which allows distributing it with programs under any license | pyinstaller.org. PyInstaller itself is only a build tool and is not shipped; the runtime hooks from pyinstaller-hooks-contrib that are bundled are Apache-2.0 |
| pywebview (the app window) | BSD-3-Clause | github.com/r0x0r/pywebview. With it: bottle (MIT), proxy_tools (MIT), typing_extensions (PSF-2.0); on Windows pythonnet + clr_loader (MIT), on macOS PyObjC (MIT) |
| **Tesseract OCR** 5 + eng/osd traineddata | Apache-2.0 | github.com/tesseract-ocr/tesseract. **Bundled** with the libraries it is built with: Leptonica (BSD-2-Clause-style), libarchive, libpng, libjpeg-turbo, libtiff, libwebp, OpenJPEG, giflib, zlib, ICU and others (permissive licenses), and in the Windows build also the DLLs of the training tools (Pango, cairo, GLib, HarfBuzz, FreeType, fontconfig: LGPL-2.1+/MIT/FreeType licenses). Windows: the UB-Mannheim build; its documentation and license files are in the app's `tesseract` folder. macOS: the Homebrew build; the license files of Tesseract and every bundled Homebrew library are in `tesseract/licenses/` |
| Microsoft Edge **WebView2** Evergreen bootstrapper (Windows installer only) | Microsoft software license terms (proprietary; Microsoft allows redistributing the bootstrapper with applications) | Runs only when the WebView2 runtime is missing and installs it from Microsoft. Not covered by the GPL. macOS uses the system's WKWebView |
| Inno Setup (the Windows installer and uninstaller engine) | Inno Setup License (permissive) | jrsoftware.org/isinfo.php |

## Docker images (Dockerfile, Dockerfile.space)
Based on the official `python:3.12-slim` image (Debian). Tesseract, its English data and Leptonica come from Debian packages (Apache-2.0 / BSD-2-Clause-style); each Debian package's license is in `/usr/share/doc/<package>/copyright` inside the image. The Python packages are the ones in requirements.lock.txt (above).

## Optional AI double-check (downloaded on request, NOT bundled)
| Component | License | Notes |
|---|---|---|
| llama.cpp `llama-server` (with ggml) | MIT | github.com/ggml-org/llama.cpp. The desktop AI helper and the demo Space download a pinned release and check its SHA-256. The JSON-schema-to-grammar feature is used for strict VLM output |
| **Qwen3-VL-4B-Instruct** (GGUF Q4_K_M + mmproj Q8_0; default model) | Apache-2.0 | huggingface.co/Qwen/Qwen3-VL-4B-Instruct-GGUF (pinned revision, SHA-256 checked) |
| Qwen2.5-VL-3B-Instruct (documented fallback only, `GAC_VLM=qwen25-3b`) | **Qwen Research License: non-commercial / research use only** | do not use for Chamber operations without checking the license |

## Development, build and test tools (not shipped)
pytest (MIT), httpx (BSD-3-Clause), ruff (MIT), pip-audit (Apache-2.0), uv (MIT OR Apache-2.0), pip-licenses (MIT), PyInstaller (GPL-2.0-or-later with the bootloader exception; build tool), Playwright (Apache-2.0). The experiments in iteration 10 also used GLiNER (Apache-2.0; the urchade *-v2.1 weights are Apache-2.0), docTR (Apache-2.0), RapidOCR v3 (Apache-2.0), rembg (MIT), usaddress (MIT), probablepeople (MIT) and PyTorch (BSD-3-Clause). None of them was adopted, so none is shipped.

## Public repository and demo
- **This project's own code is licensed GPL-3.0-or-later** (see `LICENSE`). That choice is compatible with gender-guesser (GPL-3.0) and with every other dependency above (MIT, BSD, Apache-2.0, HPND, PSF, LGPL are all GPL-3.0-compatible).
- **Fonts:** Lato (app/static/fonts) and the fonts in tests/fonts are SIL Open Font License 1.1 (Google Fonts); they keep that license.
- **Greater Akron Chamber name and logo** (`app/static/brand/GAC_logo.png`) are the Chamber's marks. They are **not** covered by the GPL; forks should replace the logo and name.
- **MC Trade / MemberClicks** is a trademark of its owner; this project only produces import files in its documented layout and is not affiliated with or endorsed by it. Snapshots of its API documentation were removed from the public repository.
- **Test and demo cards** (tests/cards, tests/synth2, qa/fixtures) are synthetic, generated by tests/gen_*.py with fictional people and 555 numbers. Real card photos used during the pilot benchmark (Wikimedia Commons) are **not** included; `bench/fetch_commons.py` can download a benchmark set yourself (check each file's license).
- **Hugging Face Space:** `Dockerfile.space` downloads llama.cpp (MIT) at build time and `space/start.sh` downloads Qwen3-VL-4B-Instruct GGUF (Apache-2.0) at start, both pinned and SHA-256 checked; neither is stored in this repository.
