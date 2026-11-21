"""Android entry point (called from Kotlin through Chaquopy).

start() prepares the environment, links the bundled native tools (ffmpeg, ffprobe, QuickJS) into a bin
folder on PATH, starts the local server and returns its URL for the WebView.
"""
import os
from pathlib import Path

TOOLS = {"ffmpeg": "libffmpeg.so", "ffprobe": "libffprobe.so", "qjs": "libqjs.so"}


def _link_tools(native_dir, bin_dir):
    """Android only allows executing files from the app's native library folder, so the tools ship there as
    lib*.so and get friendly names through symlinks (exec follows the link to the allowed file)."""
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


def start(files_dir, native_dir, workspace_dir, bundle_dir):
    home = Path(files_dir)
    os.environ.update({
        "VICE_ANDROID": "1",
        "VICE_HOME": str(home),
        "VICE_BUNDLE": str(bundle_dir),
        "VICE_WORKSPACE": str(workspace_dir),
        "VICE_MAX_HEIGHT": "720",  # phone-friendly downloads
        "HOME": str(home),
        "TMPDIR": str(home / "tmp"),
    })
    (home / "tmp").mkdir(parents=True, exist_ok=True)
    tools = _link_tools(native_dir, home / "bin")
    os.environ["PATH"] = str(home / "bin") + os.pathsep + os.environ.get("PATH", "/system/bin")
    if "qjs" in tools:  # YouTube needs a JavaScript runtime for its player challenges
        os.environ["VICE_JS_RUNTIME"] = "quickjs:" + tools["qjs"]
    try:  # Python on Android has no system CA store
        import certifi
        os.environ.setdefault("SSL_CERT_FILE", certifi.where())
        os.environ.setdefault("REQUESTS_CA_BUNDLE", certifi.where())
    except ImportError:
        pass
    from desk import server
    return server.serve(0)


def stop():
    from desk import server
    server.shutdown()
