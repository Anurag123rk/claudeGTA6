"""Vice Desk: desktop GUI for the claudeGTA6 clip pipeline.

The same executable has three modes:
  ViceDesk.exe                          -> the GUI
  ViceDesk.exe --script moments.py ...  -> run one pipeline script (used by the GUI for every step)
  ViceDesk.exe -m yt_dlp ...            -> run a bundled module (the scripts call yt-dlp this way)
Extra GUI flags: --browser (use the default browser instead of a native window), --port N.
"""
import io, os, runpy, sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))


def _fix_streams():
    """Child mode writes UTF-8, line by line. A frozen .exe ignores PYTHONIOENCODING/PYTHONUNBUFFERED, so on
    Windows the default would be cp1252 (crashes on emoji in video titles) and block-buffered (late progress).
    A windowed .exe can also start without stdout/stderr; give it real streams when the handles exist."""
    for fd, name in ((1, "stdout"), (2, "stderr")):
        st = getattr(sys, name)
        if st is not None:
            try:
                st.reconfigure(encoding="utf-8", errors="replace", line_buffering=True)
                continue
            except Exception:
                pass
        try:
            setattr(sys, name, io.TextIOWrapper(io.FileIO(fd, "w", closefd=False), encoding="utf-8",
                                                errors="replace", line_buffering=True))
        except OSError:
            setattr(sys, name, open(os.devnull, "w"))


def _no_console_windows():
    """On Windows, console tools (ffmpeg, ffprobe) started from a windowless app pop up a black window.
    Child mode starts every subprocess with CREATE_NO_WINDOW instead."""
    if sys.platform != "win32":
        return
    import subprocess
    flag = 0x08000000  # CREATE_NO_WINDOW
    orig = subprocess.Popen.__init__

    def init(self, *a, **kw):
        kw["creationflags"] = (kw.get("creationflags") or 0) | flag
        orig(self, *a, **kw)
    subprocess.Popen.__init__ = init


def _bundled_deps():  # never called: lists imports so PyInstaller bundles what the scripts need
    import concurrent.futures, csv, ctypes, hashlib, socket, ssl, urllib.request, wave  # noqa: F401
    import numpy, requests, cv2, faster_whisper, ctranslate2, deep_translator, edge_tts, yt_dlp  # noqa: F401
    import truststore, anthropic  # noqa: F401


def main():
    argv = sys.argv[1:]
    if len(argv) >= 2 and argv[0] == "-m":
        _fix_streams(); _no_console_windows()
        mod = argv[1]
        sys.argv = [mod] + argv[2:]
        runpy.run_module(mod, run_name="__main__", alter_sys=True)
        return
    if len(argv) >= 2 and argv[0] == "--script":
        _fix_streams(); _no_console_windows()
        from desk.core import scripts_dir
        sd = scripts_dir()
        script = sd / Path(argv[1]).name
        if not script.is_file():
            sys.exit(f"unknown script: {argv[1]}")
        sys.path.insert(0, str(sd))
        sys.argv = [str(script)] + argv[2:]
        runpy.run_path(str(script), run_name="__main__")
        return
    from desk.server import run_gui
    port = int(argv[argv.index("--port") + 1]) if "--port" in argv else 0
    run_gui(browser="--browser" in argv, port=port)


if __name__ == "__main__":
    main()
