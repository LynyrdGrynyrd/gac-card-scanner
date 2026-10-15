"""Desktop launcher for the packaged GAC Card Scanner (PyInstaller entry point).
Runs the FastAPI app in a background thread on 127.0.0.1:<random free port> and shows it in a native window
(pywebview: Edge WebView2 on Windows, WKWebView on macOS). Closing the window stops the server (and the AI helper).
Single instance: a second launch asks the running one to bring its window to the front.
Data: %LOCALAPPDATA%\\GAC Card Scanner (Windows), ~/Library/Application Support/GAC Card Scanner (macOS).
  --headless   no window (CI smoke tests); stops on SIGTERM/Ctrl+C
  --port N     fixed port instead of a random free one"""
import argparse, base64, json, mimetypes, os, secrets, socket, sys, threading, time, urllib.request, webbrowser

APP = "GAC Card Scanner"
if not getattr(sys, "frozen", False): sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
IMG_EXT = (".jpg", ".jpeg", ".png", ".heic", ".heif", ".webp", ".tif", ".tiff", ".bmp")

def base_dir():
    return getattr(sys, "_MEIPASS", os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

def data_dir():
    if os.environ.get("GAC_DATA_DIR"): return os.environ["GAC_DATA_DIR"]
    if sys.platform == "win32": root = os.environ.get("LOCALAPPDATA") or os.path.expanduser("~\\AppData\\Local")
    elif sys.platform == "darwin": root = os.path.expanduser("~/Library/Application Support")
    else: root = os.environ.get("XDG_DATA_HOME") or os.path.expanduser("~/.local/share")
    return os.path.join(root, APP)

def setup_env():
    b = base_dir(); d = data_dir(); os.makedirs(d, exist_ok=True)
    os.environ["GAC_DATA_DIR"] = d; os.environ["GAC_DESKTOP"] = "1"
    os.environ.setdefault("CORRECTIONS_DIR", os.path.join(d, "corrections"))
    tess = os.path.join(b, "tesseract")
    if os.path.isdir(tess):   # bundled Tesseract (binary + tessdata)
        os.environ["PATH"] = tess + os.pathsep + os.environ.get("PATH", "")
        os.environ["TESSDATA_PREFIX"] = os.path.join(tess, "tessdata")
    elif sys.platform == "darwin":
        os.environ["PATH"] = "/opt/homebrew/bin:/usr/local/bin:" + os.environ.get("PATH", "")
    return d

def free_port():
    s = socket.socket(); s.bind(("127.0.0.1", 0)); p = s.getsockname()[1]; s.close(); return p

def _log_to_file(d):
    if sys.stdout is None or sys.stderr is None or getattr(sys, "frozen", False):
        f = open(os.path.join(d, "app.log"), "a", buffering=1, encoding="utf-8"); sys.stdout = sys.stderr = f

INSTANCE = lambda d: os.path.join(d, "instance.json")
def _ping_existing(d):
    """If another copy is running, ask it to show its window and return True."""
    try:
        info = json.load(open(INSTANCE(d)))
        req = urllib.request.Request(f"http://127.0.0.1:{info['port']}/__desktop/focus", b"", {"X-GAC-Instance": info["token"], "Origin": f"http://127.0.0.1:{info['port']}"})
        return urllib.request.urlopen(req, timeout=2).status == 200
    except Exception: return False

def _dlg(kind):
    import webview
    fd = getattr(webview, "FileDialog", None)
    return getattr(fd, kind) if fd is not None else getattr(webview, kind + "_DIALOG")

class Api:
    """Exposed to the page as window.pywebview.api (see app/static/ui/desktop.js)."""
    def __init__(self, url, d):
        self.url, self.d, self.win, self.last_dir = url, d, None, None
        self._lock = threading.Lock()
    def save_file(self, name, b64data):
        # v0.2.1: one Save dialog at a time (an export saves 3 files back to back; parallel dialogs lost the companions),
        # each opening in the folder the previous one was saved to
        with self._lock:
            name = os.path.basename(name or "download")
            start = self.last_dir if self.last_dir and os.path.isdir(self.last_dir) else os.path.expanduser("~/Downloads")
            r = self.win.create_file_dialog(_dlg('SAVE'), directory=start, save_filename=name)
            if not r: return ""
            path = r if isinstance(r, str) else r[0]
            self.last_dir = os.path.dirname(path)
            with open(path, "wb") as f: f.write(base64.b64decode(b64data))
            return path
    def pick_folder(self):
        import webview
        r = self.win.create_file_dialog(_dlg('FOLDER'))
        if not r: return []
        root = r if isinstance(r, str) else r[0]; out = []
        for dp, _, fs in os.walk(root):
            for n in sorted(fs):
                if n.lower().endswith(IMG_EXT) and not n.startswith("."):
                    p = os.path.join(dp, n)
                    if os.path.getsize(p) <= 25 * 1024 * 1024:
                        out.append({"name": n, "type": mimetypes.guess_type(n)[0] or "image/jpeg", "b64": base64.b64encode(open(p, "rb").read()).decode()})
                if len(out) >= 500: return out
        return out
    def open_in_browser(self): webbrowser.open(self.url)
    def open_url(self, path):   # v0.2.1: Help PDF links open in the system browser (webviews can't show/download PDFs reliably)
        from urllib.parse import urlsplit
        path = str(path or "")
        if not path.startswith("/static/") or ".." in path or "//" in path: return False
        u = urlsplit(self.url); webbrowser.open(f"{u.scheme}://{u.netloc}{path}"); return True
    def open_data_folder(self): _open_folder(self.d)

def main(argv=None):
    a = argparse.ArgumentParser(); a.add_argument("--headless", action="store_true"); a.add_argument("--port", type=int)
    args = a.parse_args(argv)
    d = setup_env(); _log_to_file(d)
    if not args.headless and _ping_existing(d): return 0
    port = args.port or free_port(); token = secrets.token_hex(16)
    url = f"http://127.0.0.1:{port}/ui"
    import uvicorn
    from fastapi import Request
    from fastapi.responses import JSONResponse
    from app.main import app   # imported after setup_env so the data dir applies
    from app import ai_helper
    api = Api(url, d)

    @app.post("/__desktop/focus", include_in_schema=False)
    def _focus(request: Request):   # loopback-only + per-run token; lets a second launch raise this window
        if request.headers.get("X-GAC-Instance") != token: return JSONResponse({}, 403)
        w = api.win
        if w:
            try: w.restore(); w.show()
            except Exception: pass
            try: w.on_top = True; w.on_top = False
            except Exception: pass
        return {"ok": True}
    # the auth middleware runs first; exempt this one loopback path (it checks its own token)
    from app import auth as _auth
    _auth.PUBLIC.add("/__desktop/focus")

    server = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=port, log_level="info", log_config=None))
    print(f"{APP}: serving {url} (data: {d})", flush=True)
    def stop_all():
        server.should_exit = True
        try: ai_helper.stop()
        except Exception: pass
    if args.headless:
        import signal
        for sig in (signal.SIGINT, signal.SIGTERM): signal.signal(sig, lambda *_: stop_all())
        server.run(); ai_helper.stop(); return 0

    t = threading.Thread(target=server.run, daemon=True); t.start()
    for _ in range(600):
        if server.started: break
        time.sleep(0.05)
    json.dump({"port": port, "token": token, "pid": os.getpid()}, open(INSTANCE(d), "w"))
    try:
        import webview
        from webview.menu import Menu, MenuAction, MenuSeparator
        menu = [Menu("File", [MenuAction("Open in browser", api.open_in_browser), MenuAction("Open data folder", api.open_data_folder),
                              MenuSeparator(), MenuAction("Quit", lambda: api.win and api.win.destroy())])]
        # pywebview cancels every download unless ALLOW_DOWNLOADS is set (edgechromium on_download_starting, cocoa, qt):
        # with it, a download the page can't route through desktop.js still gets a native Save dialog instead of vanishing
        webview.settings["ALLOW_DOWNLOADS"] = True
        api.win = webview.create_window(APP, url, js_api=api, width=1280, height=860, min_size=(900, 600), text_select=True)
        api.win.events.closed += stop_all
        webview.start(menu=menu, icon=os.path.join(base_dir(), "packaging", "icon.png"), private_mode=False,
                      storage_path=os.path.join(d, "webview"))
    except Exception as e:   # no webview runtime: fall back to the default browser and keep serving
        print("Native window unavailable, opening the browser instead:", repr(e), flush=True)
        webbrowser.open(url)
        try:
            while t.is_alive(): t.join(1)
        except KeyboardInterrupt: pass
    stop_all(); t.join(10)
    try: os.remove(INSTANCE(d))
    except OSError: pass
    return 0

def _open_folder(p):
    import subprocess
    if sys.platform == "win32": os.startfile(p)
    elif sys.platform == "darwin": subprocess.Popen(["open", p])
    else: subprocess.Popen(["xdg-open", p])

if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "--gac-reader":   # v0.3: the capped reader child (PDF/HEIC/OCR), see app/reader.py
        from app import reader; reader.cli(sys.argv[2:]); sys.exit(0)
    import multiprocessing; multiprocessing.freeze_support()
    sys.exit(main())
