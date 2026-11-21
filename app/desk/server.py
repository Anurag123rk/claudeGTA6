"""Local HTTP server for the Vice Desk UI. Binds to 127.0.0.1 only and requires a per-launch token,
so other web pages on the machine cannot drive it. No login, no remote backend."""
import json, mimetypes, os, secrets, subprocess, sys, threading, time, webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from . import core

TOKEN = secrets.token_urlsafe(16)
TASKS = core.TaskManager()
QUIT = threading.Event()


def _inside(path, root):
    try:
        Path(path).resolve().relative_to(Path(root).resolve())
        return True
    except ValueError:
        return False


class Handler(BaseHTTPRequestHandler):
    server_version = "ViceDesk/" + core.VERSION
    protocol_version = "HTTP/1.1"

    def log_message(self, *a):
        pass

    # ---- helpers
    def _authed(self, q):
        return self.headers.get("X-Desk-Token") == TOKEN or (q.get("t") or [""])[0] == TOKEN

    def _json(self, obj, code=200):
        body = json.dumps(obj, default=str).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def _err(self, code, msg):
        self._json({"error": msg}, code)

    def _body(self):
        n = int(self.headers.get("Content-Length") or 0)
        if not n:
            return {}
        try:
            return json.loads(self.rfile.read(n).decode("utf-8") or "{}")
        except ValueError:
            return {}

    def _static(self, name):
        root = core.ui_dir()
        f = (root / (name or "index.html")).resolve()
        if not _inside(f, root) or not f.is_file():
            return self._err(404, "not found")
        data = f.read_bytes()
        if f.name == "index.html":
            data = data.replace(b"__DESK_TOKEN__", TOKEN.encode())
        self.send_response(200)
        self.send_header("Content-Type", (mimetypes.guess_type(f.name)[0] or "application/octet-stream") +
                         ("; charset=utf-8" if f.suffix in (".html", ".js", ".css") else ""))
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(data)

    def _file(self, path):
        """Serve a workspace file with HTTP Range support (video seeking)."""
        f = Path(path)
        if not _inside(f, core.SETTINGS.workspace) or not f.is_file():
            return self._err(404, "not found")
        size = f.stat().st_size
        start, end = 0, size - 1
        rng = self.headers.get("Range")
        if rng and rng.startswith("bytes="):
            a, _, b = rng[6:].split(",")[0].partition("-")
            if a:
                start = int(a); end = int(b) if b else size - 1
            elif b:
                start = max(0, size - int(b))
            end = min(end, size - 1)
            if start > end:
                self.send_response(416); self.send_header("Content-Range", f"bytes */{size}"); self.end_headers(); return
            self.send_response(206)
            self.send_header("Content-Range", f"bytes {start}-{end}/{size}")
        else:
            self.send_response(200)
        ctype = mimetypes.guess_type(f.name)[0] or ("text/markdown" if f.suffix == ".md" else "application/octet-stream")
        if ctype.startswith("text/"):
            ctype += "; charset=utf-8"
        self.send_header("Content-Type", ctype)
        self.send_header("Accept-Ranges", "bytes")
        self.send_header("Content-Length", str(end - start + 1))
        self.end_headers()
        with open(f, "rb") as fh:
            fh.seek(start)
            left = end - start + 1
            try:
                while left > 0:
                    chunk = fh.read(min(left, 512 * 1024))
                    if not chunk:
                        break
                    self.wfile.write(chunk); left -= len(chunk)
            except (BrokenPipeError, ConnectionResetError):
                pass

    def _events(self):
        """Server-sent events: a snapshot of every task whenever anything changes (live monitor)."""
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Connection", "keep-alive")
        self.end_headers()
        last, beat = None, 0
        try:
            while not QUIT.is_set():
                rev = TASKS.changed()
                running = any(t.state == "running" for t in TASKS.list())
                if rev != last or (running and time.time() - beat > 1) or time.time() - beat > 15:
                    data = json.dumps({"tasks": [t.summary() for t in reversed(TASKS.list())], "now": time.time()}, default=str)
                    self.wfile.write(f"data: {data}\n\n".encode()); self.wfile.flush()
                    last, beat = rev, time.time()
                time.sleep(0.4)
        except (BrokenPipeError, ConnectionResetError, OSError):
            pass
        self.close_connection = True

    # ---- routes
    def do_GET(self):
        u = urlparse(self.path); q = parse_qs(u.query); path = u.path
        if path == "/" or (path.startswith("/") and not path.startswith("/api/") and "." in path.rsplit("/", 1)[-1]):
            return self._static(path.lstrip("/") or "index.html")
        if not path.startswith("/api/"):
            return self._static("index.html")
        if not self._authed(q):
            return self._err(403, "bad token")
        if path == "/api/status":
            return self._json({"app": core.APP_NAME, "version": core.VERSION, "tools": core.tool_status(),
                               "settings": core.SETTINGS.public(), "workspace": str(core.SETTINGS.workspace),
                               "platform": sys.platform, "frozen": core.FROZEN, "bin": str(core.bin_dir()),
                               "models": core.WHISPER_MODELS, "installed_models": core.installed_models(),
                               "android": core.IS_ANDROID,
                               "first_run": (not core.IS_ANDROID and not core.SETTINGS.data.get("model_choice_done")
                                             and not core.installed_models())})
        if path == "/api/events":
            return self._events()
        if path == "/api/tasks":
            return self._json({"tasks": [t.summary() for t in reversed(TASKS.list())]})
        if path.startswith("/api/tasks/"):
            t = TASKS.get(path.rsplit("/", 1)[-1])
            return self._json(t.summary(full=True)) if t else self._err(404, "no such task")
        if path == "/api/jobs":
            return self._json({"jobs": core.list_jobs()})
        if path == "/api/file":
            return self._file((q.get("path") or [""])[0])
        if path == "/api/text":
            name = (q.get("name") or [""])[0]
            if name not in ("trends.md", "streams.md", "campaigns.md"):
                return self._err(400, "unknown file")
            f = core.SETTINGS.workspace / name
            return self._json({"name": name, "text": f.read_text(encoding="utf-8") if f.exists() else "",
                               "mtime": f.stat().st_mtime if f.exists() else None})
        return self._err(404, "unknown endpoint")

    def do_POST(self):
        u = urlparse(self.path); q = parse_qs(u.query); path = u.path
        if not self._authed(q):
            return self._err(403, "bad token")
        b = self._body()
        if path == "/api/run":
            kind = b.get("kind"); p = b.get("params") or {}
            if kind not in core.RUNNERS:
                return self._err(400, "unknown task kind")
            need = {"moments": "src", "pipeline": "src", "cut": "job", "check": "clip", "live": "url"}.get(kind)
            if need and not str(p.get(need) or "").strip():
                return self._err(400, f"missing {need}")
            if need:
                p[need] = str(p[need]).strip().strip('"')
            if kind in ("moments", "pipeline"):
                src = p["src"]
                if "\n" in src or len(src) > 2000:
                    return self._err(400, "Paste a single video URL or file path.")
                if not src.startswith(("http://", "https://")) and not Path(src).expanduser().is_file():
                    return self._err(400, f"Not a video URL and no such file: {src[:120]}")
            if core.IS_ANDROID and kind in ("live", "install_ffmpeg", "install_model"):
                return self._err(400, "Not available in the Android app (use the Windows app for this).")
            if kind == "live" and not p["url"].startswith(("http://", "https://")):
                return self._err(400, "Live mode needs a stream URL (https://...).")
            if kind in ("moments", "pipeline", "cut", "live") and not core.find_tool("ffmpeg"):
                return self._err(400, "ffmpeg is not installed yet. Install it from the Dashboard first.")
            title = {"trends": "Trend radar: " + (p.get("query") or "gta 6"),
                     "streams": "Live streams: " + (p.get("query") or "gta 6"),
                     "moments": "Find moments: " + p.get("src", ""), "pipeline": "Full pipeline: " + p.get("src", ""),
                     "cut": f"Cut clip {p.get('pick')}: " + Path(p.get("job", "")).name,
                     "check": "Rule check: " + Path(p.get("clip", "")).name, "live": "Live: " + p.get("url", ""),
                     "install_ffmpeg": "Install ffmpeg",
                     "install_model": "Download speech model: " + str(p.get("model", ""))}[kind]
            t = TASKS.start(kind, title, p, core.RUNNERS[kind](p))
            return self._json({"id": t.id})
        if path.startswith("/api/tasks/") and path.endswith("/cancel"):
            return self._json({"ok": TASKS.cancel(path.split("/")[3])})
        if path == "/api/tasks/clear":
            with TASKS.lock:
                for k in [k for k, v in TASKS.tasks.items() if v.state not in ("queued", "running")]:
                    TASKS.tasks.pop(k)
            return self._json({"ok": True})
        if path == "/api/settings":
            core.SETTINGS.update(**{k: v for k, v in b.items() if k in core.Settings.DEFAULTS})
            return self._json({"settings": core.SETTINGS.public(), "workspace": str(core.SETTINGS.workspace)})
        if path == "/api/open":
            if core.IS_ANDROID:
                return self._err(400, "Use Share or Save to gallery on Android.")
            target = Path(b.get("path") or core.SETTINGS.workspace)
            if not _inside(target, core.SETTINGS.workspace) and target.resolve() != core.bin_dir().resolve():
                return self._err(400, "outside workspace")
            open_path(target if target.exists() else target.parent)
            return self._json({"ok": True})
        if path == "/api/open-url":
            url = str(b.get("url") or "")
            if not url.startswith(("https://", "http://")):
                return self._err(400, "not a web link")
            webbrowser.open(url)
            return self._json({"ok": True})
        if path == "/api/campaigns":
            (core.SETTINGS.workspace / "campaigns.md").write_text(str(b.get("text") or ""), encoding="utf-8")
            return self._json({"ok": True})
        if path == "/api/quit":
            threading.Timer(0.3, shutdown).start()
            return self._json({"ok": True})
        return self._err(404, "unknown endpoint")


def open_path(p):
    p = str(p)
    if core.IS_WIN:
        os.startfile(p)  # noqa: S606 - opening the user's own folder in Explorer
    elif sys.platform == "darwin":
        subprocess.Popen(["open", p])
    else:
        subprocess.Popen(["xdg-open", p], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


_httpd = None


def shutdown():
    TASKS.cancel_all()
    QUIT.set()
    if _httpd:
        threading.Thread(target=_httpd.shutdown, daemon=True).start()


def serve(port=0):
    global _httpd
    _httpd = ThreadingHTTPServer(("127.0.0.1", port), Handler)
    _httpd.daemon_threads = True
    threading.Thread(target=_httpd.serve_forever, daemon=True).start()
    return f"http://127.0.0.1:{_httpd.server_address[1]}/?t={TOKEN}"


def run_gui(browser=False, port=0):
    url = serve(port)
    print(f"{core.APP_NAME} {core.VERSION} running at {url}", flush=True)
    if not browser and not os.environ.get("VICE_DESK_BROWSER"):
        try:
            import webview  # pywebview: native window (Edge WebView2 on Windows)
            webview.create_window(core.APP_NAME, url, width=1360, height=880, min_size=(980, 640),
                                  background_color="#140b18")
            # Edge WebView2 only: the legacy IE engine cannot run this UI, so fall back to the browser instead
            webview.start(gui="edgechromium" if core.IS_WIN else None)
            shutdown()
            return
        except Exception as e:  # no WebView2 / pywebview: fall back to the default browser
            print(f"native window unavailable ({e}); opening the browser", flush=True)
    webbrowser.open(url)
    try:
        while not QUIT.is_set():
            time.sleep(0.5)
    except KeyboardInterrupt:
        shutdown()
