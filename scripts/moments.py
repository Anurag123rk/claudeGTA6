"""Find the best clip moments in a video or VOD.

Signals per second: loudness spikes, YouTube "most replayed" heatmap, live-chat spikes
(YouTube VOD chat replay or a TwitchDownloader chat.json) and hype words in the transcript.
Writes jobs/<id>/candidates.md + candidates.json.

usage: python moments.py <url-or-file> [--top 8] [--min 15] [--max 40] [--chat chat.json] [--max-minutes 90]
"""
import argparse, json, math, os, re, sys, wave
from pathlib import Path
import numpy as np
sys.path.insert(0, str(Path(__file__).parent))
from common import COOKIE_HELP, NO_FORMATS_HELP, ffprobe, is_bot_check, is_url, job_dir, load_json, media_ok, progress, retry, run, save_json, stage, tool, ytdl_chat_replay, ytdl_download, ytdl_info

HYPE = re.compile(r"\b(no way|oh my god|omg|what|wait|bro|let'?s go|holy|insane|crazy|yo+|wtf|dude|look at|nah|run|go go)\b", re.I)
CHAT_HYPE = re.compile(r"(LMAO|LOL|KEKW|OMEGALUL|W+\b|CLIP|💀|😂|🔥|NO WAY|HOLY)", re.I)


def fetch(src, d, max_min):
    info = {}
    if is_url(src):
        stage(1, 5, "Reading video info")
        try:
            info = retry(lambda: ytdl_info(src), "reading video info")
        except Exception as e:
            if is_bot_check(str(e)):
                sys.exit(COOKIE_HELP)
            sys.exit(f"could not read this video: {str(e).replace('ERROR: ', '')[:300]}")
        save_json(d / "info.json", {k: info.get(k) for k in ("id", "title", "uploader", "channel", "uploader_id", "webpage_url",
                                                             "duration", "view_count", "upload_date", "heatmap", "is_live", "was_live")})
        if info.get("is_live"):
            sys.exit("this video is live right now: use Live mode to record it, or wait until it has ended")
        vid = d / "source.mp4"
        stage(2, 5, "Downloading video")
        if vid.exists() and not media_ok(vid):  # e.g. an earlier run was cut off when the phone paused the app
            print("the previous download is incomplete or damaged: downloading it again", flush=True)
            vid.unlink()
            for f in (d / "audio.wav", d / "transcript.json"):
                f.unlink(missing_ok=True)
        if not vid.exists():
            h = int(os.environ.get("VICE_MAX_HEIGHT") or 1080)  # the Android app asks for 720p
            fmt = f"bv*[height<={h}][ext=mp4]+ba[ext=m4a]/bv*[height<={h}]+ba/b[height<={h}]/b"
            long = (info.get("duration") or 0) > max_min * 60
            tmp = d / "download.mp4"  # renamed to source.mp4 only once it is complete and readable
            tmp.unlink(missing_ok=True)  # a finished-but-broken file; yt-dlp's .part files are kept and resumed
            try:
                retry(lambda: ytdl_download(src, tmp, fmt, max_seconds=max_min * 60 if long else None), "download")
            except SystemExit as e:
                if is_bot_check(str(e.code)):
                    sys.exit(COOKIE_HELP)
                if "format is not available" in str(e.code):
                    sys.exit(NO_FORMATS_HELP)
                raise
            if not media_ok(tmp):
                tmp.unlink(missing_ok=True)
                sys.exit("the download finished but the file is damaged (connection dropped?). Please run it again.")
            tmp.replace(vid)
        if info.get("was_live") and not list(d.glob("chat*.live_chat.json")):  # YouTube chat replay
            ytdl_chat_replay(src, d / "chat")
    else:
        stage(2, 5, "Using local file")
        vid = Path(src).resolve()
        if not vid.exists():
            sys.exit(f"file not found: {vid}")
        save_json(d / "info.json", {"title": vid.stem, "webpage_url": str(vid)})
    return vid, info


def audio_rms(vid, d):
    wav = d / "audio.wav"
    stage(3, 5, "Extracting audio")
    if wav.exists() and wav.stat().st_size < 44 + 16000 * 2:  # header only: an interrupted earlier run
        wav.unlink()
    if not wav.exists():
        part = d / "audio.part.wav"
        run([tool("ffmpeg"), "-y", "-v", "error", "-i", str(vid), "-ac", "1", "-ar", "16000", str(part)])
        part.replace(wav)
    with wave.open(str(wav)) as w:
        x = np.frombuffer(w.readframes(w.getnframes()), dtype=np.int16).astype(np.float32) / 32768
    n = len(x) // 16000
    rms = np.sqrt((x[: n * 16000].reshape(n, 16000) ** 2).mean(1) + 1e-9)
    return wav, 20 * np.log10(rms)


def transcribe(wav, d):
    out = d / "transcript.json"
    stage(4, 5, "Transcribing speech")
    if out.exists():
        return load_json(out)
    try:
        from faster_whisper import WhisperModel
    except ImportError:  # e.g. the Android app: no speech engine, score on loudness/heatmap/chat only
        print("speech engine not available here: scoring without a transcript (no captions)", flush=True)
        return []
    try:
        import ctranslate2
        cuda = ctranslate2.get_cuda_device_count() > 0
    except Exception:
        cuda = False
    with wave.open(str(wav)) as w:  # pass samples directly (16 kHz mono), no extra decoder needed
        pcm = np.frombuffer(w.readframes(w.getnframes()), dtype=np.int16).astype(np.float32) / 32768

    def run_on(device):
        import os
        model = WhisperModel(os.environ.get("WHISPER_MODEL", "small"), device=device, compute_type="float16" if device == "cuda" else "int8")
        segs, _ = model.transcribe(pcm, word_timestamps=True, vad_filter=True)
        total = len(pcm) / 16000
        words = []
        for s in segs:
            words += [{"w": w.word.strip(), "s": round(w.start, 2), "e": round(w.end, 2)} for w in (s.words or [])]
            progress(min(s.end, total), total, "transcribed")
        progress(total, total, "transcribed")
        return words
    try:
        try:
            words = run_on("cuda" if cuda else "cpu")
        except RuntimeError as e:  # GPU present but CUDA libraries missing: fall back to CPU
            if not cuda:
                raise
            print(f"GPU transcription unavailable ({str(e)[:80]}), using CPU")
            words = run_on("cpu")
    except Exception as e:  # model download blocked/offline: keep going on loudness, heatmap and chat
        print(f"WARNING: transcription unavailable ({str(e)[:160]}). Scoring without speech; clips will have no captions. "
              "Check your internet connection and run again to get captions.", flush=True)
        return []
    save_json(out, words)
    return words


def chat_series(d, n, chat_arg, info):
    """Messages per second from YouTube live_chat json lines or a TwitchDownloader chat.json."""
    c = np.zeros(n)
    yt = list(d.glob("chat*.live_chat.json"))
    if yt:
        for line in yt[0].read_text(encoding="utf-8", errors="ignore").splitlines():
            try:
                a = json.loads(line)["replayChatItemAction"]
                t = int(a["videoOffsetTimeMsec"]) / 1000
                txt = json.dumps(a["actions"], ensure_ascii=False)
            except Exception:
                continue
            if 0 <= t < n:
                c[int(t)] += 2 if CHAT_HYPE.search(txt) else 1
    elif chat_arg:
        js = load_json(chat_arg)
        for m in js.get("comments", []):
            t = m.get("content_offset_seconds", 0)
            body = (m.get("message") or {}).get("body", "")
            if 0 <= t < n:
                c[int(t)] += 2 if CHAT_HYPE.search(body) else 1
    return c


def z(a):
    a = np.asarray(a, dtype=float)
    if a.std() < 1e-9:
        return np.zeros_like(a)
    return (a - np.median(a)) / (a.std() + 1e-9)


def smooth(a, k):
    k = max(1, min(int(k), len(a)))  # a window longer than the clip would change the array length
    return np.convolve(a, np.ones(k) / k, mode="same")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("src"); ap.add_argument("--top", type=int, default=8)
    ap.add_argument("--min", type=float, default=15); ap.add_argument("--max", type=float, default=40)
    ap.add_argument("--chat"); ap.add_argument("--max-minutes", type=int, default=90)
    a = ap.parse_args()
    d = job_dir(a.src)
    vid, info = fetch(a.src, d, a.max_minutes)
    dur = float(ffprobe(vid)["format"]["duration"])
    wav, db = audio_rms(vid, d)
    n = len(db)
    words = transcribe(wav, d)
    stage(5, 5, "Scoring moments")
    # signals
    loud = smooth(np.clip(z(db - smooth(db, 30)), 0, None), 3)          # jumps above the local level
    hype = np.zeros(n)
    for w in words:
        if HYPE.search(w["w"]) and int(w["s"]) < n:
            hype[int(w["s"])] += 1
    hype = smooth(hype, 5)
    heat = np.zeros(n)
    for h in (info.get("heatmap") or []):
        heat[int(h["start_time"]):int(math.ceil(h["end_time"]))] = h["value"]
    chat = chat_series(d, n, a.chat, info)
    chatz = smooth(np.clip(z(smooth(chat, 10)), 0, None), 3)
    w_heat = 2.0 if heat.any() else 0
    w_chat = 1.5 if chat.any() else 0
    score = 1.0 * loud + 0.8 * z(hype).clip(0) + w_heat * z(heat).clip(0) + w_chat * chatz
    # pick non-overlapping windows around peaks
    picks, used = [], np.zeros(n, bool)
    order = np.argsort(-score)
    for p in order:
        if len(picks) >= a.top or score[p] <= 0:
            break
        s0 = max(0, p - 0.55 * a.max); e0 = min(dur, s0 + a.max)
        # snap start to the first word after s0 and end to a word end, keep length in [min, max]
        ws = [x for x in words if x["s"] >= s0 and x["e"] <= e0]
        if ws:
            s0 = max(0, ws[0]["s"] - 0.3); e0 = min(dur, ws[-1]["e"] + 0.6)
        if e0 - s0 < a.min:
            e0 = min(dur, s0 + a.min)
        e0 = min(e0, s0 + a.max)
        if used[int(s0):int(e0)].any():
            continue
        used[int(s0):int(e0)] = True
        text = " ".join(x["w"] for x in words if s0 <= x["s"] < e0)
        why = []
        if loud[p] > 1: why.append("loudness spike")
        if hype[p] > 0: why.append("hype words")
        if heat[p] > 0.5: why.append(f"most replayed {heat[p]:.2f}")
        if w_chat and chatz[p] > 1: why.append("chat spike")
        picks.append({"n": len(picks) + 1, "start": round(s0, 2), "end": round(e0, 2), "peak": int(p),
                      "score": round(float(score[p]), 2), "why": why or ["overall energy"], "text": text[:400]})
    picks.sort(key=lambda x: x["start"])
    for i, x in enumerate(picks, 1):
        x["n"] = i
    meta = load_json(d / "info.json")
    save_json(d / "candidates.json", {"source": str(vid), "info": meta, "duration": dur, "candidates": picks,
                                      "signals": {"heatmap": bool(w_heat), "chat": bool(w_chat), "words": len(words)}})
    fmt = lambda t: f"{int(t // 60)}:{int(t % 60):02d}"
    md = [f"# Candidates: {meta.get('title', '')}", f"source: {meta.get('webpage_url', '')}",
          f"signals: loudness, transcript ({len(words)} words)" + (", most replayed" if w_heat else "") + (", chat" if w_chat else ""), ""]
    for x in picks:
        md += [f"## {x['n']}. {fmt(x['start'])}-{fmt(x['end'])} ({x['end'] - x['start']:.0f}s) score {x['score']}",
               f"why: {', '.join(x['why'])}", f"> {x['text']}", ""]
    (d / "candidates.md").write_text("\n".join(md), encoding="utf-8")
    print(f"job: {d}\n{len(picks)} candidates -> {d / 'candidates.md'}")


if __name__ == "__main__":
    main()
