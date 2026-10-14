# PyInstaller spec (onedir). Build from the repo root:  pyinstaller packaging/gac.spec --noconfirm
# Expects a prepared Tesseract folder in packaging/build/tesseract (see .github/workflows/release.yml).
import os, sys
from PyInstaller.utils.hooks import collect_data_files, collect_submodules, collect_dynamic_libs
ROOT = os.path.abspath(os.path.join(SPECPATH, ".."))
NAME = "GAC Card Scanner"
datas = [(os.path.join(ROOT, "app", "static"), "app/static"),
         (os.path.join(ROOT, "data", "existing_contacts.csv"), "data"),
         (os.path.join(ROOT, "packaging", "icon.png"), "packaging"),
         (os.path.join(ROOT, "LICENSE"), "."), (os.path.join(ROOT, "THIRD-PARTY-NOTICES.md"), ".")]
tess = os.path.join(ROOT, "packaging", "build", "tesseract")
if os.path.isdir(tess): datas.append((tess, "tesseract"))
else: print("WARNING: packaging/build/tesseract missing: the bundle will rely on a system Tesseract")
for pkg in ("gender_guesser", "rapidocr_onnxruntime", "phonenumbers", "zxingcpp", "webview"):
    try: datas += collect_data_files(pkg)
    except Exception as e: print("skip data", pkg, e)
binaries = []
for pkg in ("onnxruntime", "zxingcpp"):
    try: binaries += collect_dynamic_libs(pkg)
    except Exception as e: print("skip libs", pkg, e)
hidden = (collect_submodules("app") + collect_submodules("uvicorn") + collect_submodules("rapidocr_onnxruntime")
          + collect_submodules("webview") + ["multipart", "python_multipart", "openpyxl", "cryptography"])
a = Analysis([os.path.join(ROOT, "packaging", "launcher.py")], pathex=[ROOT], binaries=binaries, datas=datas,
             hiddenimports=hidden, excludes=["tkinter", "matplotlib", "pytest", "IPython"], noarchive=False)
pyz = PYZ(a.pure)
icon = os.path.join(ROOT, "packaging", "icon.ico" if sys.platform == "win32" else "icon.icns")
exe = EXE(pyz, a.scripts, [], exclude_binaries=True, name=NAME, console=False, icon=icon,
          target_arch=os.environ.get("GAC_TARGET_ARCH") or None, upx=False)
coll = COLLECT(exe, a.binaries, a.datas, name=NAME, upx=False)
if sys.platform == "darwin":
    app = BUNDLE(coll, name=NAME + ".app", icon=icon, bundle_identifier="org.gac.cardscanner",
                 version=os.environ.get("GAC_VERSION", "0.0.0"),
                 info_plist={"LSUIElement": True, "NSHighResolutionCapable": True, "CFBundleShortVersionString": os.environ.get("GAC_VERSION", "0.0.0")})
