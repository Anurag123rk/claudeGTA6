"""Shared helpers: paths, tool lookup, yt-dlp and ffmpeg wrappers."""
import hashlib, json, os, re, shutil, subprocess, sys
from pathlib import Path

for _st in (sys.stdout, sys.stderr):  # emoji in titles must not crash a cp1252 Windows console
    try:
        _st.reconfigure(errors="replace")
    except Exception:
        pass

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


CANCEL_CHECK = None  # set by an in-process host (Android app): returns True when the user pressed Stop


def check_cancel():
    if CANCEL_CHECK is not None and CANCEL_CHECK():
        raise SystemExit("cancelled")


def stage(n, total, name):
    """Announce a pipeline stage ([STAGE] 2/5 Transcribing)."""
    check_cancel()
    print(f"[STAGE] {n}/{total} {name}", flush=True)


def progress(done, total, label=""):
    """Announce progress inside the current stage ([PROG] done|total|label)."""
    check_cancel()
    print(f"[PROG] {done:.2f}|{total:.2f}|{label}", flush=True)


# ---------------------------------------------------------------- in-process yt-dlp
# Running yt-dlp as a library is much faster than one process per video (each start of the packaged app
# costs seconds) and it is the only way on Android, where there is no Python executable to spawn.

def ytdl_opts(**extra):
    opts = {"quiet": True, "no_warnings": True, "noprogress": True, "socket_timeout": 20, "retries": 3,
            "extractor_retries": 2}
    ff = shutil.which("ffmpeg")
    if ff:
        opts["ffmpeg_location"] = os.path.dirname(ff)
    rt = os.environ.get("VICE_JS_RUNTIME")  # e.g. "quickjs:/data/.../bin/qjs" (Android); default: deno on PATH
    if rt:
        name, _, path = rt.partition(":")
        opts["js_runtimes"] = {name: ({"path": path} if path else {})}
    if sys.platform == "win32":
        opts["compat_opts"] = {"no-certifi"}
    # YouTube "Sign in to confirm you're not a bot": send a signed-in session's cookies
    cookies = os.environ.get("VICE_COOKIES")
    browser = os.environ.get("VICE_COOKIES_BROWSER")
    if cookies and os.path.isfile(cookies) and os.path.getsize(cookies) > 50:
        opts["cookiefile"] = cookies
    elif browser:
        opts["cookiesfrombrowser"] = (browser,)
    opts.update(extra)
    return opts


BOT_CHECK = ("confirm you're not a bot", "confirm you’re not a bot", "sign in to confirm")


NO_FORMATS_HELP = ("YouTube offered no playable formats for this video [no-formats]. Usually its JavaScript check was "
                   "not solved: check Dashboard > Setup shows the YouTube challenge solver as ready (update the app if not). "
                   "If it does, the video may need sign-in (Settings > YouTube sign-in) or be region-locked; then press Retry.")

COOKIE_HELP = ("YouTube asked to confirm you're not a bot [needs-cookies]. Add YouTube cookies: in Vice Desk open "
               "Settings > YouTube sign-in (phone: Sign in to YouTube; desktop: use your browser or paste cookies.txt), "
               "then press Retry.")


def is_bot_check(msg):
    m = (msg or "").lower()
    return any(b in m for b in BOT_CHECK)


def ytdl_search(url, limit):
    """One request: a YouTube results page as flat entries (title, views or live viewers, approximate upload
    time, duration, channel, live status). No per-video page loads."""
    import yt_dlp
    opts = ytdl_opts(extract_flat="in_playlist", playlistend=int(limit), skip_download=True,
                     extractor_args={"youtubetab": {"approximate_date": [""]}})
    with yt_dlp.YoutubeDL(opts) as ydl:
        info = ydl.extract_info(url, download=False)
    return [e for e in (info or {}).get("entries") or [] if e]


def ytdl_info(url):
    """Metadata of one video without format processing (fast, and never fails on 'format not available')."""
    import yt_dlp
    opts = ytdl_opts(skip_download=True, ignore_no_formats_error=True,
                     extractor_args={"youtube": {"skip": ["dash", "hls", "translated_subs"]}})
    with yt_dlp.YoutubeDL(opts) as ydl:
        return ydl.sanitize_info(ydl.extract_info(url, download=False, process=False))


def ytdl_download(url, out, fmt, max_seconds=None):
    """Download url to out (mp4), printing [VPROG] lines. Raises SystemExit with a readable message on failure."""
    import yt_dlp

    def hook(d):
        check_cancel()
        if d.get("status") in ("downloading", "finished"):
            n = lambda k: "NA" if d.get(k) is None else d.get(k)
            print(f"[VPROG] {n('downloaded_bytes')}|{n('total_bytes')}|{n('total_bytes_estimate')}|{n('speed')}|"
                  f"{n('eta')}|{d.get('status')}", flush=True)

    opts = ytdl_opts(format=fmt, outtmpl=str(out), merge_output_format="mp4", progress_hooks=[hook],
                     concurrent_fragment_downloads=4, noprogress=True)
    if max_seconds:
        from yt_dlp.utils import download_range_func
        opts["download_ranges"] = download_range_func([], [[0, max_seconds]])
        opts["force_keyframes_at_cuts"] = False
    try:
        with yt_dlp.YoutubeDL(opts) as ydl:
            rc = ydl.download([url])
    except yt_dlp.utils.DownloadError as e:
        sys.exit(f"download failed: {str(e).replace('ERROR: ', '')[:400]}")
    if rc:
        sys.exit("download failed (see log)")


def ytdl_chat_replay(url, outtmpl):
    """Save a finished stream's YouTube live-chat replay next to the job (best effort)."""
    import yt_dlp
    opts = ytdl_opts(skip_download=True, writesubtitles=True, subtitleslangs=["live_chat"], outtmpl=str(outtmpl))
    try:
        with yt_dlp.YoutubeDL(opts) as ydl:
            ydl.download([url])
    except Exception as e:  # chat is optional
        print(f"chat replay unavailable: {str(e)[:160]}", flush=True)


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
    jobs = Path(os.environ.get("CLIP_DESK_HOME", ROOT)) / "jobs"  # read each time: the app can switch workspace
    d = jobs / f"{stem or 'job'}-{key}"
    d.mkdir(parents=True, exist_ok=True)
    return d


def run_ffmpeg(cmd, duration, label="encoded"):
    """Run an ffmpeg command and report [PROG] lines from its -progress output. Exits on failure like run()."""
    cmd = list(cmd[:1]) + ["-progress", "pipe:1", "-nostats"] + list(cmd[1:])
    p = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, encoding="utf-8", errors="replace")
    import threading
    err = []
    t = threading.Thread(target=lambda: err.extend(p.stderr), daemon=True); t.start()
    try:
        for line in p.stdout:
            if line.startswith("out_time_us=") or line.startswith("out_time_ms="):
                try:
                    sec = int(line.split("=", 1)[1]) / 1e6
                except ValueError:
                    continue
                progress(min(max(sec, 0), duration), duration, label)
    finally:
        if p.poll() is None and CANCEL_CHECK is not None and CANCEL_CHECK():
            p.kill()
    p.wait(); t.join(2)
    for pipe in (p.stdout, p.stderr):  # close them: unclosed pipes print ResourceWarnings into the log
        try:
            pipe.close()
        except Exception:
            pass
    if p.returncode != 0:
        sys.exit(f"command failed ({p.returncode}): {' '.join(map(str, cmd))[:200]}\n{''.join(err)[-1500:]}")
    progress(duration, duration, label)


def media_ok(path, need_video=True):
    """True if path is a complete, readable media file (a download cut off half-way is not)."""
    path = Path(path)
    if not path.exists() or path.stat().st_size < 1024:
        return False
    r = run([tool("ffprobe"), "-v", "error", "-show_entries", "format=duration:stream=codec_type", "-of", "json", str(path)],
            check=False, capture=True)
    if r.returncode != 0:
        return False
    try:
        j = json.loads(r.stdout)
        dur = float(j.get("format", {}).get("duration") or 0)
        kinds = {s_.get("codec_type") for s_ in j.get("streams", [])}
    except (ValueError, TypeError):
        return False
    return dur > 1 and ("video" in kinds or not need_video)


def retry(fn, what, attempts=3, wait=5):
    """Call fn(); on failure (network drop, app suspended...) wait and try again. Stop is never retried."""
    import time as _time
    for k in range(1, attempts + 1):
        try:
            return fn()
        except (SystemExit, Exception) as e:  # yt-dlp failures surface as SystemExit (ytdl_download) or exceptions
            msg = str(e.code if isinstance(e, SystemExit) else e)
            if msg == "cancelled" or k == attempts or is_bot_check(msg) or "format is not available" in msg:
                raise  # retrying cannot fix these
            print(f"{what} failed ({msg[:160]}); retrying in {wait * k}s ({k}/{attempts - 1})", flush=True)
            for _ in range(wait * k):
                check_cancel()
                _time.sleep(1)


def ffprobe(path):
    r = run([tool("ffprobe"), "-v", "error", "-show_entries", "format=duration:stream=codec_type,width,height,r_frame_rate",
             "-of", "json", str(path)], capture=True)
    return json.loads(r.stdout)


def save_json(path, obj):
    Path(path).write_text(json.dumps(obj, ensure_ascii=False, indent=1), encoding="utf-8")


def load_json(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))
