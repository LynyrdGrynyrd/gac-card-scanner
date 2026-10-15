"""Audit 2026-10 (CI / release, Docker, Space): static checks on the build and packaging files, so the fixes can't
quietly regress (unpinned actions, write permissions everywhere, a partial lock, unverified downloads, ...)."""
import os, re
import pytest
from app import ai_helper as AH

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
def read(*p): return open(os.path.join(ROOT, *p), encoding="utf-8").read()
def code(text, comment=("#",)):   # the lines that do something (comments dropped)
    return "\n".join(l for l in text.splitlines() if not l.lstrip().startswith(comment))
def lock_pins():
    pins = {}
    for line in read("requirements.lock.txt").splitlines():
        line = line.split("#", 1)[0].strip()
        if not line: continue
        m = re.fullmatch(r"([A-Za-z0-9_.\-]+)==([^\s;]+)\s*(;.*)?", line)
        assert m, f"not an exact pin: {line!r}"
        pins[re.sub(r"[-_.]+", "-", m.group(1)).lower()] = m.group(2)
    return pins


def test_lock_is_a_full_pin_set_with_one_opencv():
    # rapidocr 3.x depends on the headless OpenCV; opencv-python next to it would overwrite the same cv2/ folder
    pins = lock_pins()
    assert "opencv-python-headless" in pins and "opencv-python" not in pins
    assert not any(re.match(r"opencv-python\s*[<>=!~;]", l.strip()) for l in read("requirements.txt").splitlines())
    # every direct requirement is pinned ...
    for line in read("requirements.txt").splitlines():
        name = re.split(r"[<>=!~;\s#]", line.strip(), maxsplit=1)[0]
        if name: assert re.sub(r"[-_.]+", "-", name).lower() in pins, name
    # ... and so is every dependency of every pinned package (for this platform), as installed here
    from importlib import metadata
    from packaging.requirements import Requirement
    missing = []
    for name in pins:
        try: dist = metadata.distribution(name)
        except metadata.PackageNotFoundError: continue
        for r in dist.requires or []:
            req = Requirement(r)
            if req.marker and not req.marker.evaluate({"extra": ""}): continue
            if re.sub(r"[-_.]+", "-", req.name).lower() not in pins: missing.append(f"{name} -> {req.name}")
    assert not missing, missing


def _workflow(name):
    yaml = pytest.importorskip("yaml")
    return read(".github", "workflows", name), yaml.safe_load(read(".github", "workflows", name))


@pytest.mark.parametrize("name", ["ci.yml", "release.yml"])
def test_actions_pinned_by_sha_and_checkout_without_credentials(name):
    text, wf = _workflow(name)
    uses = re.findall(r"uses:\s*([^\s#]+)", text)
    assert uses
    for u in uses: assert re.fullmatch(r"[\w.\-]+/[\w.\-/]+@[0-9a-f]{40}", u), f"not pinned to a commit SHA: {u}"
    for job in wf["jobs"].values():
        for st in job.get("steps", []):
            if str(st.get("uses", "")).startswith("actions/checkout@"):
                assert st.get("with", {}).get("persist-credentials") is False


def test_release_permissions_version_check_and_pins():
    text, wf = _workflow("release.yml")
    assert wf["permissions"] == {"contents": "read"}
    writers = {n for n, j in wf["jobs"].items() if (j.get("permissions") or {}).get("contents") == "write"}
    assert writers == {"release"}
    assert wf["jobs"]["provenance"]["permissions"] == {"contents": "read", "id-token": "write", "attestations": "write"}
    assert "VERSION" in str(wf["jobs"]["check"]) and "--notes-file" in text
    for k in ("PYINSTALLER_VERSION", "PYWEBVIEW_VERSION"): assert re.fullmatch(r"\d+(\.\d+)+", wf["env"][k])
    assert re.fullmatch(r"[0-9a-f]{64}", wf["env"]["WEBVIEW2_SHA256"]) and "Get-FileHash" in text
    assert "sign.ps1" in text and "sign_notarize.sh" in text


def test_docker_images_use_the_lock_and_ship_what_the_app_reads():
    for df in ("Dockerfile", "Dockerfile.space"):
        t = code(read(df))
        assert "pip install -r requirements.lock.txt" in t and "requirements.txt" not in t.replace("requirements.lock.txt", "")
        assert re.search(r"^COPY .*VERSION", t, re.M) and re.search(r"^COPY .*mctrade-dryrun", t, re.M), df
        assert re.search(r"^FROM python:3\.12-slim@sha256:[0-9a-f]{64}$", t, re.M), df
    ign = [l.strip() for l in read(".dockerignore").splitlines() if l.strip() and not l.startswith("#")]
    assert "tests" not in ign and "!tests/synth2" in ign and "!tests/synth2_gt.json" in ign   # Dockerfile.space COPYs them
    for p in ("VERSION", "mctrade-dryrun", "app", "requirements.lock.txt"): assert p not in ign


def test_space_downloads_are_pinned_and_verified_like_the_desktop_helper():
    df, sh = read("Dockerfile.space"), read("space", "start.sh")
    assert f"ARG LLAMA_TAG={AH.LLAMA_BUILD}" in df and "sha256sum -c" in df
    assert re.search(r"^ARG LLAMA_SHA256=[0-9a-f]{64}$", df, re.M)
    assert AH.HF_REVISION in sh and "resolve/main" not in sh and "resolve/main" not in AH._HF
    for name, sha, _size in (AH.MODEL, AH.MMPROJ): assert name in sh and sha in sh
    assert "--api-key-file" in sh and "--no-slots" in sh and "--cache-ram 0" in sh


def test_installer_and_signing_scripts():
    iss = code(read("packaging", "windows", "installer.iss"), (";",))
    assert re.search(r'^\[InstallDelete\]\s*\nType: filesandordirs; Name: "\{app\}\\_internal"', iss, re.M)
    assert "/IM llama-server.exe" not in iss and "ai-helper" in iss
    sn = read("packaging", "macos", "sign_notarize.sh")
    for line in sn.splitlines():
        if "codesign" in line and "--sign" in line: assert "|| true" not in line and "2>/dev/null" not in line, line
    for f in ("start-ai-checker.command",):
        assert '[ -n "$SRV" ]' in read(f)   # no 'exec "./"' when no llama-server was found
    assert 'if not exist "%SRV%"' in read("start-ai-checker.bat")
