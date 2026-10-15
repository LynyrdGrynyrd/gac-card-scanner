"""Audit 2026-10 (Security Low / CI-release): the desktop AI helper starts llama-server with a random per-start API key
(--api-key-file), one slot, no prompt cache in RAM and no /slots endpoint; app/vlm.py sends the key as a Bearer token,
and sends nothing when no key is configured (a llama-server started by hand without a key keeps working)."""
import io, json, os
import pytest
from app import ai_helper as AH, vlm


class _FakeProc:
    def __init__(self): self.alive = True
    def poll(self): return None if self.alive else 0
    def terminate(self): self.alive = False
    def wait(self, *_a): return 0
    def kill(self): self.alive = False


@pytest.fixture
def helper(monkeypatch, tmp_path):
    calls = []
    monkeypatch.setattr(AH, "DIR", str(tmp_path))
    monkeypatch.setattr(AH, "KEY_FILE", str(tmp_path / "api-key"))
    monkeypatch.setattr(AH, "installed", lambda: True)
    monkeypatch.setattr(AH, "_server_path", lambda: str(tmp_path / "llama-server"))
    monkeypatch.setattr(AH, "_port_answers", lambda: False)
    monkeypatch.setattr(AH.subprocess, "Popen", lambda cmd, **kw: calls.append(cmd) or _FakeProc())
    AH._proc["p"] = None
    yield calls
    AH._proc["p"] = None


def test_start_flags_and_random_key_file(helper):
    assert AH.start() is True
    cmd = helper[-1]
    for flag in ("--no-slots", "--api-key-file"):
        assert flag in cmd
    assert cmd[cmd.index("-np") + 1] == "1" and cmd[cmd.index("--cache-ram") + 1] == "0"
    assert cmd[cmd.index("--host") + 1] == "127.0.0.1"
    assert "--api-key" not in cmd                       # the key never appears on the command line (process list)
    kf = cmd[cmd.index("--api-key-file") + 1]; assert kf == AH.KEY_FILE
    key1 = open(kf, encoding="utf-8").read().strip(); assert len(key1) >= 32
    if os.name != "nt": assert os.stat(kf).st_mode & 0o077 == 0   # owner-only
    AH.stop(); assert not os.path.exists(kf)            # stopping our server removes its key
    assert AH.start() is True
    key2 = open(kf, encoding="utf-8").read().strip(); assert key2 and key2 != key1   # new key on every start
    AH.stop()


def test_server_left_running_keeps_its_key(helper, monkeypatch):
    """A llama-server still running after an app crash keeps the key it was started with: no second copy, no new key."""
    open(AH.KEY_FILE, "w").write("old-key\n")
    monkeypatch.setattr(AH, "_port_answers", lambda: True)
    assert AH.start() is False and helper == []
    assert open(AH.KEY_FILE).read().strip() == "old-key"


def _capture(monkeypatch):
    seen = {}
    class R:
        def read(self): return json.dumps({"choices": [{"message": {"content": "{}"}}]}).encode()
    def fake_urlopen(req, timeout=None):
        seen["headers"] = {k.lower(): v for k, v in req.header_items()}; return R()
    monkeypatch.setattr(vlm.urllib.request, "urlopen", fake_urlopen)
    from PIL import Image
    b = io.BytesIO(); Image.new("RGB", (64, 40), "white").save(b, "JPEG")
    return seen, b.getvalue()


def test_vlm_sends_no_key_when_none_configured(monkeypatch, tmp_path):
    from app import paths
    monkeypatch.delenv("VLM_API_KEY", raising=False)
    monkeypatch.setattr(paths, "DATA", str(tmp_path))               # no ai-helper/api-key here
    seen, img = _capture(monkeypatch)
    vlm.extract(img, "x")
    assert "authorization" not in seen["headers"] and seen["headers"]["content-type"] == "application/json"


def test_vlm_sends_helper_key_and_env_override(monkeypatch, tmp_path):
    from app import paths
    monkeypatch.delenv("VLM_API_KEY", raising=False)
    monkeypatch.setattr(paths, "DATA", str(tmp_path))
    os.makedirs(tmp_path / "ai-helper"); (tmp_path / "ai-helper" / "api-key").write_text("k-file\n")
    monkeypatch.setattr(vlm, "URL", "http://127.0.0.1:8090")
    seen, img = _capture(monkeypatch)
    vlm.extract(img, "x"); assert seen["headers"]["authorization"] == "Bearer k-file"
    monkeypatch.setenv("VLM_API_KEY", "k-env")
    vlm.extract(img, "x"); assert seen["headers"]["authorization"] == "Bearer k-env"
    # the helper's local key is never sent to a server on another computer; an explicit VLM_API_KEY is
    monkeypatch.setattr(vlm, "URL", "http://ai.example.org:8090")
    vlm.extract(img, "x"); assert seen["headers"]["authorization"] == "Bearer k-env"
    monkeypatch.delenv("VLM_API_KEY")
    vlm.extract(img, "x"); assert "authorization" not in seen["headers"]
