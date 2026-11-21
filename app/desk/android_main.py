"""Android entry point (called from Kotlin through Chaquopy).

start() prepares the environment, makes the bundled native tools runnable, starts the local server and
returns its URL for the WebView.

The tools are Android builds (bionic, /system/bin/linker64) taken from youtubedl-android, the same ones the
Seal and YTDLnis apps use:
  libffmpeg.so / libffprobe.so  ffmpeg executables; their shared libraries (libav*, x264, libass, freetype...)
                                ship zipped as libffmpeg.zip.so and are unpacked once into files/ffmpeg-pkg
  libqjs.so                     QuickJS, the JavaScript runtime yt-dlp needs for YouTube
Android only lets an app execute files from its native library folder, so they ship there as lib*.so and get
plain names (ffmpeg, ffprobe, qjs) through symlinks in files/bin, which is put on PATH.
"""
import os, subprocess, zipfile
from pathlib import Path

TOOLS = {"ffmpeg": "libffmpeg.so", "ffprobe": "libffprobe.so", "qjs": "libqjs.so"}
FONTS = "/system/fonts"
TOOL_CHECK = {}  # name -> "ok" or the error text, shown on the Setup card


def _link_tools(native_dir, bin_dir):
    bin_dir.mkdir(parents=True, exist_ok=True)
    found = {}
    for name, lib in TOOLS.items():
        src = Path(native_dir) / lib
        link = bin_dir / name
        if not src.exists():
            continue
        try:
            if link.is_symlink() or link.exists():
                if os.path.realpath(link) == str(src):
                    found[name] = str(link)
                    continue
                link.unlink()
            link.symlink_to(src)
            found[name] = str(link)
        except OSError:
            found[name] = str(src)  # fall back to the real path
    return found


def _unpack_ffmpeg_libs(native_dir, home):
    """Unpack ffmpeg's shared libraries once per app version (stamp = sizes + mtimes of the zips).
    libffmpeg.zip.so holds libav*, x264, libass...; libffdeps.zip.so holds the few runtime libraries they share
    with youtubedl-android's Python package (libc++_shared, libcrypto, libexpat, libandroid-support...)."""
    zips = [z for z in (Path(native_dir) / "libffmpeg.zip.so", Path(native_dir) / "libffdeps.zip.so") if z.exists()]
    if not zips:
        return None
    dest = home / "ffmpeg-pkg"
    stamp = dest / ".stamp"
    want = "v3-" + "-".join(f"{z.name}:{z.stat().st_size}:{int(z.stat().st_mtime)}" for z in zips)
    if not (stamp.exists() and stamp.read_text() == want):
        import shutil, stat
        shutil.rmtree(dest, ignore_errors=True)
        dest.mkdir(parents=True)
        for z in zips:
            _extract_libs(z, dest, stat)
        stamp.write_text(want)
    return dest / "usr" / "lib"


def _extract_libs(z, dest, stat):
    """Extract usr/lib/*.so* from z into dest, recreating symlinks (zipfile alone writes them as tiny text files)."""
    with zipfile.ZipFile(z) as zf:
        for m in zf.infolist():  # libraries only; skip headers/static archives to save space
            if m.is_dir() or not (m.filename.startswith("usr/lib/") and ".so" in m.filename):
                continue
            target = dest / m.filename
            if target.exists() or target.is_symlink():
                continue
            if stat.S_ISLNK(m.external_attr >> 16):  # e.g. libavdevice.so.61 -> libavdevice.so.61.3.100
                target.parent.mkdir(parents=True, exist_ok=True)
                os.symlink(zf.read(m).decode(), target)
            else:
                zf.extract(m, dest)


def _fontconfig(home):
    """libass finds fonts through fontconfig; point it at Android's system fonts."""
    conf = home / "fonts.conf"
    cache = home / "fc-cache"
    cache.mkdir(parents=True, exist_ok=True)
    conf.write_text(f"""<?xml version="1.0"?>
<!DOCTYPE fontconfig SYSTEM "fonts.dtd">
<fontconfig>
  <dir>{FONTS}</dir>
  <cachedir>{cache}</cachedir>
  <alias><family>Arial Black</family><prefer><family>Roboto</family></prefer></alias>
  <alias><family>Arial</family><prefer><family>Roboto</family></prefer></alias>
</fontconfig>
""", encoding="utf-8")
    return conf


def check_tools():
    """Run each tool once so a broken binary shows up on the Setup card instead of failing mid-pipeline."""
    for name, args in {"ffmpeg": ["-hide_banner", "-version"], "ffprobe": ["-hide_banner", "-version"],
                       "qjs": ["-e", "print(1+1)"]}.items():
        path = Path(os.environ.get("VICE_HOME", "")) / "bin" / name
        if not path.exists():
            TOOL_CHECK[name] = "missing from this build"
            continue
        try:
            r = subprocess.run([str(path)] + args, capture_output=True, text=True, timeout=20)
            TOOL_CHECK[name] = "ok" if r.returncode == 0 else f"exit {r.returncode}: {(r.stderr or r.stdout).strip()[-300:]}"
        except Exception as e:
            TOOL_CHECK[name] = f"cannot run: {e}"
    print("tool check:", TOOL_CHECK, flush=True)
    return TOOL_CHECK


def start(files_dir, native_dir, workspace_dir, bundle_dir):
    home = Path(files_dir)
    os.environ.update({
        "VICE_ANDROID": "1",
        "VICE_HOME": str(home),
        "VICE_BUNDLE": str(bundle_dir),
        "VICE_WORKSPACE": str(workspace_dir),
        "VICE_MAX_HEIGHT": "720",  # phone-friendly downloads
        "VICE_FONTS_DIR": FONTS,
        "HOME": str(home),
        "TMPDIR": str(home / "tmp"),
    })
    (home / "tmp").mkdir(parents=True, exist_ok=True)
    tools = _link_tools(native_dir, home / "bin")
    os.environ["PATH"] = str(home / "bin") + os.pathsep + os.environ.get("PATH", "/system/bin")
    try:
        libs = _unpack_ffmpeg_libs(native_dir, home)
        if libs:
            old = os.environ.get("LD_LIBRARY_PATH")
            os.environ["LD_LIBRARY_PATH"] = str(libs) + (os.pathsep + old if old else "")
        os.environ["FONTCONFIG_FILE"] = str(_fontconfig(home))
    except Exception as e:  # reported by check_tools below
        print("ffmpeg setup failed:", e, flush=True)
    if "qjs" in tools:  # YouTube needs a JavaScript runtime for its player challenges
        os.environ["VICE_JS_RUNTIME"] = "quickjs:" + tools["qjs"]
    try:  # Python on Android has no system CA store
        import certifi
        os.environ.setdefault("SSL_CERT_FILE", certifi.where())
        os.environ.setdefault("REQUESTS_CA_BUNDLE", certifi.where())
    except ImportError:
        pass
    check_tools()
    from desk import server
    return server.serve(0)


def set_busy(text):
    """Tell the Android foreground service what is running ("" = idle, it stops). Safe to call from any thread."""
    try:
        from java import jclass
        from com.chaquo.python import Python
        app = Python.getPlatform().getApplication()
        jclass("com.claudegta6.vicedesk.EngineService").update(app, text or "")
    except Exception as e:  # not on Android, or an older app build
        print("set_busy:", e, flush=True)


def stop():
    from desk import server
    server.shutdown()
