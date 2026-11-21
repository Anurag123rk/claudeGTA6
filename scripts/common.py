"""Shared helpers: paths, tool lookup, yt-dlp and ffmpeg wrappers."""
import hashlib, json, os, re, shutil, subprocess, sys
from pathlib import Path

ROOT = Path(os.environ.get("CLIP_DESK_HOME", Path.cwd()))
JOBS = ROOT / "jobs"


def tool(name):
    p = shutil.which(name)
    if not p:
        sys.exit(f"{name} not found. Run the setup skill first (it installs ffmpeg and yt-dlp).")
    return p


def run(cmd, check=True, capture=False):
    r = subprocess.run(cmd, check=False, text=True, encoding="utf-8", errors="replace",
                       stdout=subprocess.PIPE if capture else None, stderr=subprocess.PIPE if capture else None)
    if check and r.returncode != 0:
        msg = (r.stderr or "")[-1500:] if capture else ""
        sys.exit(f"command failed ({r.returncode}): {' '.join(map(str, cmd))[:200]}\n{msg}")
    return r


# Machine-readable progress lines. The Vice Desk GUI parses these; on a terminal they are harmless.
PROGRESS_TEMPLATE = ("download:[VPROG] %(progress.downloaded_bytes)s|%(progress.total_bytes)s|"
                     "%(progress.total_bytes_estimate)s|%(progress.speed)s|%(progress.eta)s|%(progress.status)s")


def ytdlp_base(progress=False):
    """yt-dlp command prefix. progress=True prints one [VPROG] line per update (bytes|total|estimate|speed|eta|status)."""
    import importlib.util
    if getattr(sys, "frozen", False):  # Vice Desk .exe: it runs `-m yt_dlp` itself
        exe = [sys.executable, "-m", "yt_dlp"]
    else:
        exe = [sys.executable, "-m", "yt_dlp"] if importlib.util.find_spec("yt_dlp") else [tool("yt-dlp")]
    base = exe + ["--no-warnings"]
    if progress:
        base += ["--newline", "--progress", "--progress-template", PROGRESS_TEMPLATE]
    else:
        base += ["--no-progress"]
    if sys.platform == "win32":
        base += ["--compat-options", "no-certifi"]  # use the Windows certificate store
    return base


def stage(n, total, name):
    """Announce a pipeline stage ([STAGE] 2/5 Transcribing)."""
    print(f"[STAGE] {n}/{total} {name}", flush=True)


def progress(done, total, label=""):
    """Announce progress inside the current stage ([PROG] done|total|label)."""
    print(f"[PROG] {done:.2f}|{total:.2f}|{label}", flush=True)


def stop_requested():
    """True when the GUI (or a user) created the file named by VICE_STOP_FILE."""
    f = os.environ.get("VICE_STOP_FILE")
    return bool(f) and Path(f).exists()


def ytdlp_json(url, extra=()):
    r = run(ytdlp_base() + ["-J", *extra, url], capture=True)
    return json.loads(r.stdout)


def is_url(s):
    return bool(re.match(r"https?://", s))


def job_dir(src):
    key = hashlib.sha1(src.encode()).hexdigest()[:8]
    stem = re.sub(r"[^a-z0-9]+", "-", Path(src).stem.lower() if not is_url(src) else src.split("v=")[-1].split("/")[-1].lower())[:24].strip("-")
    d = JOBS / f"{stem or 'job'}-{key}"
    d.mkdir(parents=True, exist_ok=True)
    return d


def run_ffmpeg(cmd, duration, label="encoded"):
    """Run an ffmpeg command and report [PROG] lines from its -progress output. Exits on failure like run()."""
    cmd = list(cmd[:1]) + ["-progress", "pipe:1", "-nostats"] + list(cmd[1:])
    p = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, encoding="utf-8", errors="replace")
    import threading
    err = []
    t = threading.Thread(target=lambda: err.extend(p.stderr), daemon=True); t.start()
    for line in p.stdout:
        if line.startswith("out_time_us=") or line.startswith("out_time_ms="):
            try:
                sec = int(line.split("=", 1)[1]) / 1e6
            except ValueError:
                continue
            progress(min(max(sec, 0), duration), duration, label)
    p.wait(); t.join(2)
    if p.returncode != 0:
        sys.exit(f"command failed ({p.returncode}): {' '.join(map(str, cmd))[:200]}\n{''.join(err)[-1500:]}")
    progress(duration, duration, label)


def ffprobe(path):
    r = run([tool("ffprobe"), "-v", "error", "-show_entries", "format=duration:stream=codec_type,width,height,r_frame_rate",
             "-of", "json", str(path)], capture=True)
    return json.loads(r.stdout)


def save_json(path, obj):
    Path(path).write_text(json.dumps(obj, ensure_ascii=False, indent=1), encoding="utf-8")


def load_json(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))
