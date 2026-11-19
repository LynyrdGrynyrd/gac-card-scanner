"""Install the source-only PP-OCRv6 pilot in its own Python environment."""
import os
from pathlib import Path
import subprocess
import sys
import venv

ROOT = Path(__file__).resolve().parents[1]
TRIAL = ROOT / ".venv" / "ocr-v6"


def main():
    venv.EnvBuilder(with_pip=True).create(TRIAL)
    python = TRIAL / ("Scripts/python.exe" if os.name == "nt" else "bin/python")
    packages = []
    for line in (ROOT / "requirements.lock.txt").read_text().splitlines():
        requirement = line.partition("#")[0].strip()
        if requirement and not requirement.startswith("rapidocr-onnxruntime=="):
            packages.append(requirement.replace("opencv-python==", "opencv-python-headless=="))
    subprocess.run([str(python), "-m", "pip", "install", *packages, "rapidocr==3.10.0"], check=True)
    subprocess.run([str(python), "-m", "pip", "check"], check=True)
    subprocess.run([str(python), "-c", "from app.ocr_trial import load; load()"], cwd=ROOT, check=True)
    print(f"Set OCR_MODEL=v6 and use {python} to run the pilot.")


if __name__ == "__main__":
    main()
