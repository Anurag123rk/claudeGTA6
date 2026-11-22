"""Vice Desk core: settings, tool detection, ffmpeg installer and the pipeline task runner.

Every pipeline step runs as a child process (the scripts in ../scripts). Their output is parsed for
the machine-readable lines the scripts print:

  [STAGE] 2/5 Downloading video         -> current stage
  [PROG] 12.00|60.00|transcribed        -> progress inside the stage
  [VPROG] bytes|total|estimate|speed|eta|status   -> yt-dlp download progress (speed in bytes/s)

plus tqdm bars (Whisper model download) and, as a last resort, the growth of files being downloaded.
"""
import collections, json, os, re, shutil, subprocess, sys, threading, time, uuid, zipfile
from pathlib import Path

APP_NAME = "Vice Desk"
VERSION = "2.2.8"
IS_WIN = sys.platform == "win32"
FROZEN = getattr(sys, "frozen", False)
IS_ANDROID = bool(os.environ.get("VICE_ANDROID"))  # set by the Android app before the engine starts


# ---------------------------------------------------------------- paths & settings

def bundle_dir():
    """Folder that holds scripts/ and ui/ (PyInstaller unpack dir when frozen)."""
    if IS_ANDROID:
        return Path(os.environ["VICE_BUNDLE"])  # assets unpacked by the app
    if FROZEN:
        return Path(getattr(sys, "_MEIPASS", Path(sys.executable).parent))
    return Path(__file__).resolve().parents[2]  # repo root


def scripts_dir():
    return bundle_dir() / "scripts"


def ui_dir():
    return bundle_dir() / "ui" if (FROZEN or IS_ANDROID) else Path(__file__).resolve().parent / "ui"


def config_dir():
    if IS_ANDROID:
        d = Path(os.environ["VICE_HOME"]) / "config"
        d.mkdir(parents=True, exist_ok=True)
        return d
    if IS_WIN:
        base = Path(os.environ.get("APPDATA") or Path.home() / "AppData" / "Roaming")
    else:
        base = Path(os.environ.get("XDG_CONFIG_HOME") or Path.home() / ".config")
    d = base / "ViceDesk"
    d.mkdir(parents=True, exist_ok=True)
    return d


def bin_dir():
    if IS_ANDROID:
        d = Path(os.environ["VICE_HOME"]) / "bin"
        d.mkdir(parents=True, exist_ok=True)
        return d
    if IS_WIN:
        base = Path(os.environ.get("LOCALAPPDATA") or Path.home() / "AppData" / "Local")
    else:
        base = Path(os.environ.get("XDG_DATA_HOME") or Path.home() / ".local" / "share")
    d = base / "ViceDesk" / "bin"
    d.mkdir(parents=True, exist_ok=True)
    return d


def default_workspace():
    if IS_ANDROID:
        return Path(os.environ["VICE_WORKSPACE"])
    docs = Path.home() / "Documents"
    return (docs if docs.exists() else Path.home()) / "ViceDesk"


class Settings:
    DEFAULTS = {"workspace": "", "whisper_model": "small", "model_choice_done": "", "twitch_client_id": "", "twitch_token": "",
                "cookies_browser": "", "mode": "", "longform_channel": ""}

    def __init__(self):
        self.path = config_dir() / "settings.json"
        self.data = dict(self.DEFAULTS)
        try:
            self.data.update(json.loads(self.path.read_text(encoding="utf-8")))
        except Exception:
            pass
        if not self.data["workspace"]:
            self.data["workspace"] = str(default_workspace())
        self.lock = threading.Lock()

    @property
    def workspace(self):
        p = Path(self.data["workspace"]).expanduser()
        p.mkdir(parents=True, exist_ok=True)
        return p

    def update(self, **kw):
        with self.lock:
            for k, v in kw.items():
                if k in self.DEFAULTS and isinstance(v, str):
                    self.data[k] = v.strip()
            self.path.write_text(json.dumps(self.data, indent=1), encoding="utf-8")

    def public(self):
        d = dict(self.data)
        d["twitch_token"] = "set" if d.get("twitch_token") else ""
        return d


SETTINGS = Settings()


def cookies_file():
    """Netscape cookies.txt for yt-dlp (YouTube bot check). Written by the phone's in-app sign-in or pasted."""
    return config_dir() / "youtube_cookies.txt"


def cookie_status():
    f = cookies_file()
    if f.exists():
        names = [ln.split("\t")[5] for ln in f.read_text(encoding="utf-8", errors="ignore").splitlines()
                 if ln and (not ln.startswith("#") or ln.startswith("#HttpOnly_")) and ln.count("\t") >= 6]
        signed = any(n in ("SID", "__Secure-3PSID", "LOGIN_INFO", "SAPISID") for n in names)
        return {"source": "file", "cookies": len(names), "signed_in": signed,
                "updated": f.stat().st_mtime}
    if SETTINGS.data.get("cookies_browser"):
        return {"source": "browser", "browser": SETTINGS.data["cookies_browser"], "signed_in": None}
    return {"source": None, "signed_in": False}


def save_cookies_text(text):
    """Accept a pasted cookies.txt (Netscape format, as exported by browser add-ons). Keeps YouTube/Google rows."""
    rows = []
    for ln in (text or "").splitlines():
        ln = ln.strip("\r")
        if not ln or ln.startswith("#") and not ln.startswith("#HttpOnly_"):
            continue
        parts = ln.split("\t")
        if len(parts) >= 7 and ("youtube.com" in parts[0] or "google.com" in parts[0]):
            rows.append(ln)
    if not rows:
        raise ValueError("no YouTube cookies found: paste a cookies.txt (Netscape format) exported while signed in to YouTube")
    cookies_file().write_text("# Netscape HTTP Cookie File\n" + "\n".join(rows) + "\n", encoding="utf-8")
    return len(rows)


def child_env(extra=None):
    env = dict(os.environ)
    env["PATH"] = os.pathsep.join([str(bundle_dir() / "bin"), str(bin_dir()), env.get("PATH", "")])
    env["PYTHONUNBUFFERED"] = "1"
    env["PYTHONIOENCODING"] = "utf-8"
    env["CLIP_DESK_HOME"] = str(SETTINGS.workspace)
    env["WHISPER_MODEL"] = whisper_model_ref(SETTINGS.data.get("whisper_model") or "base")
    env["VICE_AI_CONFIG"] = str(config_dir() / "ai.json")  # the long-form runner reads the chosen AI model here
    if cookies_file().exists():
        env["VICE_COOKIES"] = str(cookies_file())
    if SETTINGS.data.get("cookies_browser"):
        env["VICE_COOKIES_BROWSER"] = SETTINGS.data["cookies_browser"]
    if SETTINGS.data.get("twitch_client_id") and SETTINGS.data.get("twitch_token"):
        env["TWITCH_CLIENT_ID"] = SETTINGS.data["twitch_client_id"]
        env["TWITCH_TOKEN"] = SETTINGS.data["twitch_token"]
    env.update(extra or {})
    return env


def self_cmd():
    """Command that starts this app in child mode (the .exe itself when frozen)."""
    if FROZEN:
        return [sys.executable]
    return [sys.executable, str(Path(__file__).resolve().parents[1] / "vicedesk.py")]


NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)


# ---------------------------------------------------------------- tools

WHISPER_MODELS = [  # name, approx download, what it is good for
    {"name": "tiny", "size": "75 MB", "speed": "fastest", "quality": "rough captions, fine for loud hype clips"},
    {"name": "base", "size": "145 MB", "speed": "fast", "quality": "good captions for clear speech"},
    {"name": "small", "size": "485 MB", "speed": "medium", "quality": "recommended: accurate captions, handles slang"},
    {"name": "medium", "size": "1.5 GB", "speed": "slow on CPU", "quality": "best accuracy, needs a strong PC or NVIDIA GPU"},
]
MODEL_FILES = ("config.json", "model.bin", "tokenizer.json", "vocabulary.txt", "vocabulary.json", "preprocessor_config.json")


def models_dir():
    d = bin_dir().parent / "models"
    d.mkdir(parents=True, exist_ok=True)
    return d


def installed_models():
    return sorted(x.name for x in models_dir().iterdir() if (x / "model.bin").exists() and not (x / ".partial").exists())


def bundled_models():
    d = bundle_dir() / "models"
    return sorted(x.name for x in d.iterdir() if (x / "model.bin").exists()) if d.exists() else []


def whisper_model_ref(name):
    """A bundled model is passed as its folder (works offline); anything else is downloaded by faster-whisper."""
    for d in (models_dir() / name, bundle_dir() / "models" / name):
        if (d / "model.bin").exists() and not (d / ".partial").exists():
            return str(d)
    return name


def find_tool(name):
    exe = name + (".exe" if IS_WIN else "")
    for local in (bundle_dir() / "bin" / exe, bin_dir() / exe):
        if local.exists():
            return str(local)
    return shutil.which(name)


def tool_status():
    out = {}
    for t in ("ffmpeg", "ffprobe"):
        p = find_tool(t)
        out[t] = {"ok": bool(p), "path": p or ""}
    try:
        import yt_dlp.version
        out["yt-dlp"] = {"ok": True, "path": "bundled " + yt_dlp.version.__version__}
        try:
            import importlib.util
            ejs = importlib.util.find_spec("yt_dlp_ejs") is not None
        except Exception:
            ejs = False
        out["youtube-solver"] = {"ok": ejs, "path": "yt-dlp-ejs: solves YouTube's JavaScript check" if ejs
                                 else "missing: YouTube will hide every format (update the app)"}
    except Exception:
        p = shutil.which("yt-dlp")
        out["yt-dlp"] = {"ok": bool(p), "path": p or ""}
    try:
        import importlib.util
        ok = importlib.util.find_spec("faster_whisper") is not None
    except Exception:
        ok = False
    if IS_ANDROID:
        from desk.android_main import TOOL_CHECK
        for t in ("ffmpeg", "ffprobe"):
            res = TOOL_CHECK.get(t)
            if res and res != "ok":
                out[t] = {"ok": False, "path": res}
        qjs = TOOL_CHECK.get("qjs")
        out["quickjs"] = {"ok": qjs == "ok", "path": "YouTube JS runtime" if qjs == "ok" else (qjs or "not checked")}
        out["faster-whisper"] = {"ok": False, "models": [], "path": "not on Android: clips are cut without captions"}
        return out
    m = installed_models() + [x for x in bundled_models() if x not in installed_models()]
    out["faster-whisper"] = {"ok": ok and bool(m), "models": m, "path": ("models: " + ", ".join(m)) if (ok and m) else ("no speech model yet" if ok else "")}
    return out


FFMPEG_URLS = [
    "https://www.gyan.dev/ffmpeg/builds/ffmpeg-release-essentials.zip",
    "https://github.com/BtbN/FFmpeg-Builds/releases/download/latest/ffmpeg-master-latest-win64-gpl.zip",
]


# ---------------------------------------------------------------- tasks

def fmt_bytes(n):
    if n is None:
        return ""
    n = float(n)
    for u in ("B", "KB", "MB", "GB"):
        if n < 1024 or u == "GB":
            return f"{n:.0f} {u}" if u == "B" else f"{n:.1f} {u}"
        n /= 1024


_UNITS = {"": 1, "k": 1e3, "K": 1024, "M": 1024 ** 2, "G": 1024 ** 3}
TQDM = re.compile(r"(\d{1,3})%\|.*?\|\s*([\d.]+)([kKMG]?)B?/([\d.]+)([kKMG]?)B?\s*\[[^,\]]*(?:<([^,\]]*))?,\s*([\d.]+)([kKMG]?)B/s")
STAGE = re.compile(r"^\[STAGE\]\s+(\d+)/(\d+)\s+(.*)$")
PROG = re.compile(r"^\[PROG\]\s+([\d.]+)\|([\d.]+)\|(.*)$")
VPROG = re.compile(r"\[VPROG\]\s+(\S+)\|(\S+)\|(\S+)\|(\S+)\|(\S+)\|(\S*)")
# weights of the [STAGE] numbers inside a script, for the overall bar
STAGE_WEIGHTS = {"moments.py": [0.03, 0.45, 0.04, 0.43, 0.05], "cut.py": [0.12, 0.88],
                 "lf_run.py": [0.06, 0.04, 0.12, 0.18, 0.12, 0.18, 0.27, 0.03]}


def _num(s):
    try:
        return float(s)
    except (TypeError, ValueError):
        return None


class Cancelled(Exception):
    pass


class Task:
    def __init__(self, kind, title, params):
        self.id = uuid.uuid4().hex[:10]
        self.kind, self.title, self.params = kind, title, params
        self.state = "queued"  # queued running done failed cancelled
        self.created = time.time(); self.started = None; self.ended = None
        self.log = collections.deque(maxlen=800)
        self.step = ""            # e.g. "Analyze video" / "Cut clip 2 of 3"
        self.step_i, self.step_n = 0, 1
        self.stage, self.stage_i, self.stage_n = "", 0, 0
        self.stage_frac = None    # 0..1 or None (indeterminate)
        self.detail = ""
        self.download = None      # {bytes,total,speed,eta,source}
        self.speed_hist = collections.deque(maxlen=90)
        self.result = {}
        self.error = ""
        self.proc = None
        self.cancel_flag = threading.Event()
        self.stop_file = None
        self.rev = 0
        self._step_weights = [1.0]
        self._last_vprog = 0
        self._watch = None        # (glob root, patterns) for the file-growth speed fallback
        self._watch_prev = None

    # overall progress 0..1, or None when unknown
    def progress(self):
        if self.state == "done":
            return 1.0
        w = self._step_weights
        done = sum(w[: self.step_i])
        cur = w[self.step_i] if self.step_i < len(w) else 0
        sf = self._script_frac()
        if sf is None:
            return None if self.step_n <= 1 else min(1.0, done / sum(w))
        return min(1.0, (done + cur * sf) / sum(w))

    def _script_frac(self):
        """Progress of the running script, 0..1, from its [STAGE]/[PROG] lines (None if unknown)."""
        if self.stage_n == 0:
            return self.stage_frac
        sw = STAGE_WEIGHTS.get(self.params.get("_script", ""))
        i = max(0, min(self.stage_i - 1, self.stage_n - 1))
        f = self.stage_frac or 0
        if not sw or len(sw) != self.stage_n:
            return min(1.0, (i + f) / self.stage_n)
        return min(1.0, sum(sw[:i]) + sw[i] * f)

    def summary(self, full=False):
        d = {"id": self.id, "kind": self.kind, "title": self.title, "state": self.state,
             "created": self.created, "started": self.started, "ended": self.ended,
             "elapsed": ((self.ended or time.time()) - self.started) if self.started else 0,
             "step": self.step, "step_i": self.step_i, "step_n": self.step_n,
             "stage": self.stage, "stage_i": self.stage_i, "stage_n": self.stage_n,
             "stage_frac": self.stage_frac, "progress": self.progress(), "detail": self.detail,
             "download": self.download, "speed_hist": list(self.speed_hist), "result": self.result,
             "error": self.error, "last": self.log[-1] if self.log else "", "params": {k: v for k, v in self.params.items() if not k.startswith("_")}}
        if full:
            d["log"] = list(self.log)
        return d

    def touch(self):
        self.rev += 1

    def add_log(self, line):
        self.log.append(line)
        self.touch()


class TaskManager:
    def __init__(self):
        self.tasks = collections.OrderedDict()
        self.lock = threading.Lock()
        self.rev = 0
        threading.Thread(target=self._monitor, daemon=True).start()

    def list(self):
        with self.lock:
            return list(self.tasks.values())

    def get(self, tid):
        return self.tasks.get(tid)

    def changed(self):
        return sum(t.rev for t in self.list()) + len(self.tasks)

    def start(self, kind, title, params, runner):
        t = Task(kind, title, params)
        with self.lock:
            self.tasks[t.id] = t
            while len(self.tasks) > 60:  # forget the oldest finished tasks
                old = next((k for k, v in self.tasks.items() if v.state not in ("queued", "running")), None)
                if not old:
                    break
                self.tasks.pop(old)

        def go():
            t.state = "running"; t.started = time.time(); t.touch()
            try:
                runner(t)
                t.state = "cancelled" if t.cancel_flag.is_set() else "done"
            except Cancelled:
                t.state = "cancelled"
            except Exception as e:  # noqa: BLE001 - surface every failure in the UI
                t.state = "cancelled" if t.cancel_flag.is_set() else "failed"
                if t.state == "failed":
                    t.error = str(e) or e.__class__.__name__
                    t.add_log("ERROR: " + t.error)
            finally:
                t.ended = time.time(); t.proc = None
                if t.download:
                    t.download["speed"] = 0
                t.touch()
                if IS_ANDROID and not any(x.state in ("queued", "running") for x in self.list()):
                    from desk.android_main import set_busy
                    set_busy("")  # last task done: release the background keep-alive
        threading.Thread(target=go, daemon=True).start()
        return t

    def cancel(self, tid):
        t = self.get(tid)
        if not t or t.state not in ("queued", "running"):
            return False
        t.cancel_flag.set()
        t.add_log("cancel requested")
        if t.stop_file:  # live recording: ask it to stop and cut what is pending
            Path(t.stop_file).write_text("stop", encoding="utf-8")
            threading.Timer(90, lambda: kill_tree(t.proc)).start()
        else:
            kill_tree(t.proc)
        return True

    def retry(self, tid):
        """Start a failed/stopped task again with the same settings. Finished steps are reused: a complete
        download, the transcript and moments are kept, partial downloads resume, and clips already cut with the
        same settings are skipped."""
        t = self.get(tid)
        if not t or t.state not in ("failed", "cancelled") or t.kind not in RUNNERS:
            return None
        p = {k: v for k, v in t.params.items() if not k.startswith("_")}
        p["_resume"] = True
        title = t.title if t.title.startswith("Retry: ") else "Retry: " + t.title
        return self.start(t.kind, title, p, RUNNERS[t.kind](p))

    def cancel_all(self):
        for t in self.list():
            if t.state == "running":
                self.cancel(t.id)

    # speed fallback: when yt-dlp reports nothing (e.g. ffmpeg section downloads), measure file growth
    def _monitor(self):
        while True:
            time.sleep(1)
            for t in self.list():
                if t.state != "running":
                    continue
                if t.download and time.time() - t._last_vprog < 2.5:
                    t.speed_hist.append(t.download.get("speed") or 0)
                    continue
                if t._watch and "ownload" in (t.stage or ""):
                    size = 0
                    root, pats = t._watch
                    for pat in pats:
                        for f in root.glob(pat):
                            try:
                                size += f.stat().st_size
                            except OSError:
                                pass
                    now = time.time()
                    if t._watch_prev and size >= t._watch_prev[1]:
                        sp = (size - t._watch_prev[1]) / max(0.2, now - t._watch_prev[0])
                        t.download = dict(t.download or {}, bytes=size, speed=sp, source="file growth")
                        t.speed_hist.append(sp); t.touch()
                    t._watch_prev = (now, size)
                elif t.download:
                    t.speed_hist.append(0)


def kill_tree(proc):
    if not proc or proc.poll() is not None:
        return
    try:
        if IS_WIN:
            subprocess.run(["taskkill", "/T", "/F", "/PID", str(proc.pid)], capture_output=True, creationflags=NO_WINDOW)
        else:
            import signal
            os.killpg(os.getpgid(proc.pid), signal.SIGTERM)
    except Exception:
        try:
            proc.kill()
        except Exception:
            pass


def handle_line(t, line):
    line = line.rstrip()
    if not line:
        return
    m = VPROG.search(line)
    if m:
        dl, tot, est, sp, eta = (_num(x) for x in m.groups()[:5])
        status = m.group(6)
        total = tot or est
        prev = t.download or {}
        part = prev.get("part", 1)
        if prev.get("status") == "finished" and status != "finished":
            part += 1  # yt-dlp finished one file and started the next (video, then audio)
        fm = re.match(r"frag_(\d+)/(\d+)", status or "")
        t.download = {"bytes": dl, "total": total, "speed": sp or 0, "eta": eta, "part": part, "source": "yt-dlp",
                      "status": status}
        if fm:  # fragmented stream: the fragment count is the reliable progress, sizes are per-fragment estimates
            fi, fc = int(fm.group(1)), int(fm.group(2))
            t.stage_frac = fi / fc if fc else t.stage_frac
            t.detail = f"piece {fi} of {fc}" + (f" (file {part})" if part > 1 else "")
        else:
            t.stage_frac = (dl / total) if (dl is not None and total) else t.stage_frac
            t.detail = f"{fmt_bytes(dl)} of {fmt_bytes(total)}" + (f" (file {part})" if part > 1 else "") if total else fmt_bytes(dl)
        t._last_vprog = time.time()
        t.touch()
        return
    m = STAGE.match(line)
    if m:
        t.stage_i, t.stage_n, t.stage = int(m.group(1)), int(m.group(2)), m.group(3)
        t.stage_frac = 0.0; t.detail = ""
        if "ownload" not in t.stage and t.download:
            t.download = dict(t.download, speed=0)
        t.add_log(f"» {t.stage}")
        return
    m = PROG.match(line)
    if m:
        d, tot, label = float(m.group(1)), float(m.group(2)), m.group(3)
        t.stage_frac = d / tot if tot else None
        mm = lambda s: f"{int(s // 60)}:{int(s % 60):02d}"
        t.detail = f"{mm(d)} / {mm(tot)} {label}".strip()
        t.touch()
        return
    m = TQDM.search(line)
    if m:  # e.g. Whisper model download from Hugging Face
        pct = int(m.group(1))
        done = float(m.group(2)) * _UNITS.get(m.group(3), 1)
        tot = float(m.group(4)) * _UNITS.get(m.group(5), 1)
        sp = float(m.group(7)) * _UNITS.get(m.group(8), 1)
        t.download = {"bytes": done, "total": tot, "speed": sp, "eta": None, "part": 1, "source": "model download"}
        t.detail = f"speech model {pct}% ({fmt_bytes(done)} of {fmt_bytes(tot)})"
        t._last_vprog = time.time()
        t.touch()
        return
    t.add_log(line)


class _Router:
    """sys.stdout/sys.stderr stand-in for in-process scripts: text goes to the running task's log."""
    encoding = "utf-8"
    errors = "replace"

    def __init__(self, base):
        self.base = base

    def write(self, s):
        sink = _INPROC["sink"]
        if sink:
            sink(s)
        elif self.base is not None:
            self.base.write(s)
        return len(s)

    def flush(self):
        if self.base is not None:
            try:
                self.base.flush()
            except Exception:
                pass

    def isatty(self):
        return False

    def reconfigure(self, **kw):
        pass


_INPROC = {"sink": None, "lock": threading.Lock(), "installed": False}


def run_script_inproc(t, script, args, ok_codes=(0,), extra_env=None):
    """Android: run a script inside this process (one at a time), with its output routed to the task."""
    import runpy, traceback
    if not _INPROC["installed"]:
        sys.stdout, sys.stderr = _Router(sys.stdout), _Router(sys.stderr)
        _INPROC["installed"] = True
    if not _INPROC["lock"].acquire(blocking=False):
        t.stage, t.detail = "Waiting for the running task to finish", ""; t.touch()
        while not _INPROC["lock"].acquire(timeout=0.5):
            if t.cancel_flag.is_set():
                raise Cancelled()
    buf = [""]

    def sink(text):
        buf[0] += text
        parts = re.split(r"[\r\n]", buf[0])
        buf[0] = parts.pop()
        for line in parts:
            handle_line(t, line)
    rc = 0
    try:
        os.environ.update(child_env(extra_env))
        os.chdir(SETTINGS.workspace)
        sd = str(scripts_dir())
        if sd not in sys.path:
            sys.path.insert(0, sd)
        import common
        common.CANCEL_CHECK = t.cancel_flag.is_set
        _INPROC["sink"] = sink
        sys.argv = [os.path.join(sd, script)] + [str(a) for a in args]
        try:
            runpy.run_path(sys.argv[0], run_name="__main__")
        except SystemExit as e:
            if e.code not in (None, 0):
                rc = e.code if isinstance(e.code, int) else 1
                if not isinstance(e.code, int):
                    sink(str(e.code) + "\n")
        except Exception:
            sink(traceback.format_exc()); rc = 1
    finally:
        _INPROC["sink"] = None
        if buf[0]:
            handle_line(t, buf[0])
        try:
            common.CANCEL_CHECK = None
        except NameError:
            pass
        _INPROC["lock"].release()
    if t.cancel_flag.is_set() and not t.stop_file:
        raise Cancelled()
    if rc not in ok_codes:
        tail = [x for x in list(t.log)[-6:] if not x.startswith("$ ")]
        raise RuntimeError(f"{script} failed: " + (tail[-1] if tail else "no output"))
    return rc


def run_script(t, script, args, weight_i=0, ok_codes=(0,), extra_env=None, watch=None):
    """Run scripts/<script> in a child process (in-process on Android) and stream its output into the task."""
    if t.cancel_flag.is_set():
        raise Cancelled()
    t.params["_script"] = script
    t.stage, t.stage_i, t.stage_n, t.stage_frac, t.detail = "", 0, 0, None, ""
    t.step_i = weight_i
    t._watch, t._watch_prev = watch, None
    if IS_ANDROID:
        t.add_log("$ " + script + " " + " ".join(_q(a) for a in args))
        return run_script_inproc(t, script, args, ok_codes=ok_codes, extra_env=extra_env)
    cmd = self_cmd() + ["--script", script] + [str(a) for a in args]
    t.add_log("$ " + script + " " + " ".join(_q(a) for a in args))
    kw = {}
    if IS_WIN:
        kw["creationflags"] = NO_WINDOW
    else:
        kw["start_new_session"] = True
    t.proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, stdin=subprocess.DEVNULL,
                              cwd=str(SETTINGS.workspace), env=child_env(extra_env), **kw)
    buf = b""
    while True:
        chunk = t.proc.stdout.read1(4096) if hasattr(t.proc.stdout, "read1") else t.proc.stdout.read(4096)
        if not chunk:
            break
        buf += chunk
        parts = re.split(rb"[\r\n]", buf)
        buf = parts.pop()
        for p in parts:
            handle_line(t, p.decode("utf-8", "replace"))
    if buf:
        handle_line(t, buf.decode("utf-8", "replace"))
    rc = t.proc.wait()
    if t.cancel_flag.is_set() and not t.stop_file:
        raise Cancelled()
    if rc not in ok_codes:
        tail = [x for x in list(t.log)[-6:] if not x.startswith("$ ")]
        raise RuntimeError(f"{script} failed (exit {rc}): " + (tail[-1] if tail else "no output"))
    return rc


def _q(a):
    a = str(a)
    return f'"{a}"' if (" " in a or not a) else a


# ---------------------------------------------------------------- pipeline runners

def ws():
    return SETTINGS.workspace


def job_from_log(t):
    for line in reversed(t.log):
        if line.startswith("job: "):
            return line[5:].strip()
    return None


def runner_trends(p):
    def r(t):
        t.step = "Trend radar"
        out = ws() / "trends.md"
        run_script(t, "trends.py", ["--query", p.get("query") or "gta 6", "--hours", p.get("hours") or 24,
                                    "--limit", p.get("limit") or 30, "--deep", 8 if p.get("deep", "1") else 0,
                                    "--out", out])
        t.result = {"file": str(out)}
    return r


def runner_streams(p):
    def r(t):
        t.step = "Live stream finder"
        out = ws() / "streams.md"
        run_script(t, "streams.py", ["--query", p.get("query") or "gta 6", "--limit", p.get("limit") or 20, "--out", out])
        t.result = {"file": str(out)}
    return r


def _moment_args(p):
    return [p["src"], "--top", p.get("top") or 8, "--min", p.get("min") or 15, "--max", p.get("max") or 40,
            "--max-minutes", p.get("max_minutes") or 90]


def _cut_args(job, n, p):
    a = [job, "--pick", n, "--layout", p.get("layout") or "blur", "--captions", p.get("captions") or "word",
         "--platform", p.get("platform") or "vertical", "--cam", p.get("cam") or "auto"]
    if p.get("hook"):
        a += ["--hook", p["hook"]]
    if p.get("title"):
        a += ["--title", p["title"]]
    if p.get("start") not in (None, ""):
        a += ["--start", p["start"]]
    if p.get("end") not in (None, ""):
        a += ["--end", p["end"]]
    if p.get("context"):
        a += ["--context", (p.get("context_text") or "").strip() or "auto"]
    handle = (p.get("handle") or "").strip()
    if p.get("outro") and handle:
        a += ["--outro-handle", handle]
    a += ["--bg", p.get("bg") or "blur", "--bg-color", p.get("bg_color") or "vice"]
    a += ["--card-theme", p.get("card_theme") or "vice"]
    if p.get("punch"):
        a += ["--punch", 0.15]
    if p.get("clean_audio"):
        a += ["--clean-audio"]
    if p.get("fps60"):
        a += ["--fps", 60]
    return a


def _check(t, clip, p, i):
    a = [clip]
    camp = ws() / "campaigns.md"
    if camp.exists():
        a += ["--campaign", camp]
    if p.get("caption"):
        a += ["--caption", p["caption"]]
    start = len(t.log)
    rc = run_script(t, "check.py", a, weight_i=i, ok_codes=(0, 1))
    lines = [x for x in list(t.log)[start:] if x.startswith(("PASS", "FAIL", "RESULT"))]
    return {"clip": clip, "pass": rc == 0, "lines": lines}


def runner_moments(p):
    def r(t):
        t.step = "Find best moments"
        run_script(t, "moments.py", _moment_args(p), watch=(ws() / "jobs", ["*/source.mp4*", "*/source.*.part", "*/source.f*"]))
        t.result = {"job": job_from_log(t)}
    return r


def runner_cut(p):
    def r(t):
        t._step_weights = [0.8, 0.2]; t.step_n = 2
        t.step = f"Cut clip {p['pick']}"
        run_script(t, "cut.py", _cut_args(p["job"], p["pick"], p), weight_i=0)
        clip = str(Path(p["job"]) / "edits" / f"clip_{p['pick']}.mp4")
        t.step = "Rule check"
        chk = _check(t, clip, p, 1)
        t.result = {"job": p["job"], "clips": [clip], "checks": [chk]}
    return r


def runner_check(p):
    def r(t):
        t.step = "Rule check"
        t.result = {"checks": [_check(t, p["clip"], p, 0)]}
    return r


def _clip_done(job, n, p):
    """True if clip n exists, is not empty, and was cut with the same layout/platform/effects as p."""
    mp4 = Path(job) / "edits" / f"clip_{n}.mp4"
    meta = mp4.with_suffix(".json")
    if not (mp4.exists() and mp4.stat().st_size > 10000 and meta.exists()):
        return False
    try:
        m = json.loads(meta.read_text(encoding="utf-8"))
    except ValueError:
        return False
    want = {"layout": p.get("layout") or "blur", "platform": p.get("platform") or "vertical",
            "punch": 0.15 if p.get("punch") else 0, "clean_audio": bool(p.get("clean_audio")),
            "fps": 60 if p.get("fps60") else 30, "hook": p.get("hook") or "",
            "bg": p.get("bg") or "blur", "bg_color_name": p.get("bg_color") or "vice",
            "outro_handle": (p.get("handle") or "").strip() if p.get("outro") else "",
            "context_on": bool(p.get("context")), "card_theme": p.get("card_theme") or "vice"}
    return all(m.get(k, want[k]) == v for k, v in want.items() if k != "layout") and \
        (m.get("layout") == want["layout"] or want["layout"] in ("facecam", "react", "crop"))  # facecam may fall back to blur


def runner_pipeline(p):
    """Full pipeline: find moments -> cut the N best -> rule-check each."""
    def r(t):
        n = max(1, min(int(p.get("clips") or 3), 10))
        t.step_n = 1 + 2 * n
        t._step_weights = [6.0] + [1.2, 0.1] * n
        t.step = "Find best moments"
        run_script(t, "moments.py", _moment_args(p), weight_i=0,
                   watch=(ws() / "jobs", ["*/source.mp4*", "*/source.*.part", "*/source.f*"]))
        job = job_from_log(t)
        if not job:
            raise RuntimeError("moments.py did not report a job folder")
        cands = json.loads((Path(job) / "candidates.json").read_text(encoding="utf-8"))["candidates"]
        best = sorted(cands, key=lambda c: -c["score"])[:n]
        if not best:
            raise RuntimeError("no clip-worthy moments found in this video")
        clips, checks = [], []
        t.result = {"job": job, "clips": clips, "checks": checks}
        for k, c in enumerate(best):
            t.step = f"Cut clip {k + 1} of {len(best)} (moment #{c['n']})"
            if p.get("_resume") and _clip_done(job, c["n"], p):
                t.add_log(f"clip {c['n']} already cut with these settings: kept")
            else:
                try:
                    run_script(t, "cut.py", _cut_args(job, c["n"], p), weight_i=1 + 2 * k)
                except Cancelled:
                    raise
                except RuntimeError as e:  # one bad moment (e.g. no facecam) should not kill the batch
                    t.add_log(f"skipped moment #{c['n']}: {e}")
                    continue
            clip = str(Path(job) / "edits" / f"clip_{c['n']}.mp4")
            clips.append(clip)
            t.step = f"Rule check {k + 1} of {len(best)}"
            checks.append(_check(t, clip, p, 2 + 2 * k))
            t.touch()
        if not clips:
            raise RuntimeError("no clip could be cut; try another layout (blur works everywhere)")
    return r


def runner_live(p):
    def r(t):
        t.step = "Live recording"
        t.stop_file = str(config_dir() / f"stop-{t.id}")
        Path(t.stop_file).unlink(missing_ok=True)
        args = [p["url"], "--minutes", p.get("minutes") or 60, "--ratio", p.get("ratio") or 3,
                "--before", p.get("before") or 15, "--after", p.get("after") or 20]
        try:
            run_script(t, "live.py", args, extra_env={"VICE_STOP_FILE": t.stop_file})
        finally:
            Path(t.stop_file).unlink(missing_ok=True)
        t.result = {"job": next((x.split(" -> ")[-1].split("  ")[0] for x in t.log if x.startswith("recording ")), "")}
    return r


def stream_download(t, url, sink, done_before=0, grand_total=None, source="download", label=""):
    """Stream url into sink (file-like), reporting bytes / speed / ETA on the task. Returns bytes written."""
    import requests
    with requests.get(url, stream=True, timeout=30) as resp:
        resp.raise_for_status()
        size = int(resp.headers.get("content-length") or 0) or None
        total = grand_total or size
        got, win = 0, collections.deque()
        for chunk in resp.iter_content(256 * 1024):
            if t.cancel_flag.is_set():
                raise Cancelled()
            sink.write(chunk); got += len(chunk)
            now = time.time(); win.append((now, got))
            while len(win) > 2 and now - win[0][0] > 3:
                win.popleft()
            sp = (got - win[0][1]) / max(0.05, now - win[0][0]) if len(win) > 1 else 0
            cur = done_before + got
            eta = (total - cur) / sp if (total and sp) else None
            t.download = {"bytes": cur, "total": total, "speed": sp, "eta": eta, "part": 1, "source": source}
            t._last_vprog = now
            t.stage_frac = min(1.0, cur / total) if total else None
            t.detail = (label + " " if label else "") + (f"{fmt_bytes(cur)} of {fmt_bytes(total)}" if total else fmt_bytes(cur))
            t.touch()
    return got


def runner_install_ffmpeg(p):
    def r(t):
        import io
        t.step = "Install ffmpeg"
        if not IS_WIN:
            raise RuntimeError("Automatic install is for Windows. Install ffmpeg with your package manager "
                               "(apt install ffmpeg / brew install ffmpeg).")
        last = None
        for url in FFMPEG_URLS:
            try:
                t.stage, t.stage_frac = "Downloading ffmpeg", 0.0
                t.add_log("downloading " + url)
                data = io.BytesIO()
                stream_download(t, url, data, source="ffmpeg")
                t.stage, t.stage_frac, t.detail = "Unpacking", None, ""
                t.add_log("unpacking")
                with zipfile.ZipFile(data) as z:
                    found = 0
                    for name in z.namelist():
                        base = name.rsplit("/", 1)[-1].lower()
                        if base in ("ffmpeg.exe", "ffprobe.exe"):
                            (bin_dir() / base).write_bytes(z.read(name)); found += 1
                if found < 2:
                    raise RuntimeError("archive did not contain ffmpeg.exe and ffprobe.exe")
                t.add_log(f"installed to {bin_dir()}")
                t.result = {"path": str(bin_dir())}
                return
            except Cancelled:
                raise
            except Exception as e:  # try the next mirror
                last = e
                t.add_log(f"failed: {e}")
        raise RuntimeError(f"could not install ffmpeg: {last}")
    return r


def runner_install_model(p):
    """Download a faster-whisper model from Hugging Face into the app's models folder, with live speed."""
    def r(t):
        import requests
        name = p.get("model") or "small"
        if name not in [m["name"] for m in WHISPER_MODELS]:
            raise RuntimeError(f"unknown model {name}")
        repo = f"Systran/faster-whisper-{name}"
        hub = os.environ.get("HF_ENDPOINT", "https://huggingface.co").rstrip("/")  # mirror support
        t.step = f"Download speech model: {name}"
        t.stage, t.stage_i, t.stage_n = "Listing files", 1, 2
        tree = requests.get(f"{hub}/api/models/{repo}/tree/main", timeout=30)
        tree.raise_for_status()
        files = [(f["path"], (f.get("lfs") or {}).get("size") or f.get("size") or 0)
                 for f in tree.json() if f.get("type") == "file" and f["path"] in MODEL_FILES]
        if not any(f == "model.bin" for f, _ in files):
            raise RuntimeError(f"{repo} has no model.bin")
        total = sum(sz for _, sz in files) or None
        dest = models_dir() / name
        dest.mkdir(parents=True, exist_ok=True)
        (dest / ".partial").write_text("downloading", encoding="utf-8")
        t.stage, t.stage_i, t.stage_n = "Downloading model", 0, 0  # main bar = download progress
        done = 0
        for fname, sz in files:
            target = dest / fname
            if target.exists() and sz and target.stat().st_size == sz:
                done += sz
                continue
            tmp = target.with_suffix(target.suffix + ".part")
            t.add_log(f"downloading {fname} ({fmt_bytes(sz)})")
            with open(tmp, "wb") as fh:
                got = stream_download(t, f"{hub}/{repo}/resolve/main/{fname}", fh, done_before=done,
                                      grand_total=total, source=hub.split("//")[-1], label=fname)
            tmp.replace(target)
            done += sz or got
        (dest / ".partial").unlink(missing_ok=True)
        SETTINGS.update(whisper_model=name, model_choice_done="1")
        t.add_log(f"model {name} ready in {dest}")
        t.result = {"model": name, "path": str(dest)}
    return r


def runner_longform(p):
    """In-app long-form guide with the chosen AI model (scripts/lf_run.py)."""
    def r(t):
        from desk import longform
        proj = longform.create_project(SETTINGS.workspace, p.get("channel"), p.get("topics"))
        t.step = "Long-form guide"
        args = ["--project", proj["path"], "--idea", p.get("idea") or "outliers", "--minutes", p.get("minutes") or 8,
                "--voice", p.get("voice") or "auto"]
        if p.get("topics"):
            args += ["--topics", p["topics"]]
        if p.get("topic"):
            args += ["--topic", p["topic"]]
        if p.get("footage"):
            args += ["--footage", p["footage"]]
        if p.get("fresh"):
            args += ["--fresh"]
        run_script(t, "lf_run.py", args)
        draft = next((ln.split("draft: ", 1)[1] for ln in t.log if ln.startswith("draft: ")), "")
        pack = next((ln.split("publish pack: ", 1)[1] for ln in t.log if ln.startswith("publish pack: ")), "")
        t.result = {"draft": draft, "publish": pack, "project": proj["path"]}
    return r


RUNNERS = {"trends": runner_trends, "streams": runner_streams, "moments": runner_moments, "cut": runner_cut,
           "check": runner_check, "pipeline": runner_pipeline, "live": runner_live, "install_ffmpeg": runner_install_ffmpeg,
           "install_model": runner_install_model, "longform": runner_longform}


# ---------------------------------------------------------------- library

def list_longform():
    """Finished long-form drafts, newest first (each run keeps its own draft, title and thumbnail)."""
    out = []
    root = ws() / "longform"
    for draft in root.glob("*/runs/run_*/build/draft.mp4") if root.exists() else []:
        if draft.stat().st_size < 100_000:  # empty or still being written
            continue
        rd = draft.parent.parent
        title = ""
        try:
            title = (rd / "publish" / "title.txt").read_text(encoding="utf-8").strip()
        except Exception:
            pass
        st = draft.stat()
        thumb = rd / "publish" / "thumbnail.jpg"
        out.append({"file": str(draft), "name": title or rd.name, "title": title or rd.name, "size": st.st_size,
                    "mtime": st.st_mtime, "channel": rd.parent.parent.name, "run": str(rd),
                    "publish": str(rd / "publish"), "thumb": str(thumb) if thumb.exists() else ""})
    out.sort(key=lambda x: -x["mtime"])
    return out


def list_jobs():
    root = ws() / "jobs"
    out = []
    if not root.exists():
        return out
    for d in sorted(root.iterdir(), key=lambda p: p.stat().st_mtime, reverse=True):
        if not d.is_dir():
            continue
        j = {"dir": str(d), "name": d.name, "mtime": d.stat().st_mtime, "title": d.name, "url": "", "candidates": [],
             "clips": [], "live": []}
        try:
            info = json.loads((d / "info.json").read_text(encoding="utf-8"))
            j["title"] = info.get("title") or d.name; j["url"] = info.get("webpage_url") or ""
            j["channel"] = info.get("channel") or info.get("uploader") or ""
        except Exception:
            pass
        try:
            c = json.loads((d / "candidates.json").read_text(encoding="utf-8"))
            j["candidates"] = c.get("candidates", []); j["duration"] = c.get("duration")
        except Exception:
            pass
        for f in sorted((d / "edits").glob("clip_*.mp4")) if (d / "edits").exists() else []:
            if f.name.endswith(".part.mp4"):  # an encode that was stopped half-way
                continue
            meta = {}
            try:
                meta = json.loads(f.with_suffix(".json").read_text(encoding="utf-8"))
            except Exception:
                pass
            st = f.stat()
            m_ = re.match(r"clip_(\d+)\.mp4$", f.name)
            j["clips"].append({"file": str(f), "name": f.name, "size": st.st_size, "mtime": st.st_mtime,
                               "moment": int(m_.group(1)) if m_ else None, "hook": meta.get("hook", ""),
                               "layout": meta.get("layout", ""), "platform": meta.get("platform", ""),
                               "start": meta.get("start"), "end": meta.get("end")})
        j["clips"].sort(key=lambda c: -c["mtime"])  # newest first
        if (d / "live").exists():
            j["live"] = [{"file": str(f), "name": f.name, "size": f.stat().st_size} for f in sorted((d / "live").glob("spike_*.mp4"))]
        out.append(j)
    return out
