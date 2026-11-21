# PyInstaller spec for Vice Desk: one-file windowed .exe (Windows) / binary (Linux, macOS).
# Build from the app/ folder:  pyinstaller --noconfirm vicedesk.spec
import os, sys
from PyInstaller.utils.hooks import collect_all, collect_submodules

HERE = os.path.abspath(SPECPATH)
SCRIPTS = os.path.join(HERE, "..", "scripts")

datas = [(os.path.join(HERE, "desk", "ui"), "ui"), (SCRIPTS, "scripts")]
binaries = []
# ffmpeg/ffprobe placed in app/vendor/bin by the CI workflow are shipped inside the .exe (bin/)
VENDOR = os.path.join(HERE, "vendor", "bin")
if os.path.isdir(VENDOR):
    binaries += [(os.path.join(VENDOR, f), "bin") for f in os.listdir(VENDOR)]
hiddenimports = collect_submodules("yt_dlp") + collect_submodules("desk")
# the pipeline scripts are run from data files; list them so their imports get bundled too
hiddenimports += ["common", "moments", "cut", "check", "trends", "streams", "live", "twitch", "facecam",
                  "translate", "questions", "secrets_map", "payouts"]
for pkg in ("faster_whisper", "ctranslate2", "onnxruntime", "tokenizers", "av", "yt_dlp_ejs", "certifi", "truststore"):
    try:
        d, b, h = collect_all(pkg)
        datas += d; binaries += b; hiddenimports += h
    except Exception as e:
        print("skip", pkg, e)
if sys.platform == "win32":
    for pkg in ("webview", "clr_loader", "pythonnet"):
        try:
            d, b, h = collect_all(pkg)
            datas += d; binaries += b; hiddenimports += h
        except Exception as e:
            print("skip", pkg, e)

a = Analysis([os.path.join(HERE, "vicedesk.py")], pathex=[HERE, SCRIPTS], binaries=binaries, datas=datas,
             hiddenimports=hiddenimports, excludes=["tkinter", "matplotlib", "IPython", "pytest", "torch"], noarchive=False)
pyz = PYZ(a.pure)
exe = EXE(pyz, a.scripts, a.binaries, a.datas, [], name="ViceDesk", console=False, upx=False,
          icon=os.path.join(HERE, "vicedesk.ico"), version=os.path.join(HERE, "version_info.txt") if sys.platform == "win32" else None)
