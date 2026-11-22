"""Long-form GTA 6 guide, run inside Vice Desk with the AI model you chose (Claude, ChatGPT, Gemini, ...).

Stages (each saved under <project>/, so a re-run reuses what is finished):
  1 study      outliers in the niche: views / the channel's usual views, one video per channel   -> research/
  2 topic      three concepts from the study (or your own idea), the strongest picked             -> research/
  3 script     chaptered script; every claim tagged official/measured/in-game/unverified          -> build/script.json
  4 critics    three blind critics (story, honesty, pacing), a judge ranks fixes, one revision   -> rounds/
  5 voice      ElevenLabs (your key) or the free Microsoft voice, per chapter                    -> voice/
  6 footage    official trailers/gameplay only (your URLs, or Rockstar Games' own uploads)      -> footage/
  7 build      1920x1080 rough cut: footage under the voice, chapter cards, captions, -14 LUFS  -> build/draft.mp4
  8 publish    title, description with chapter timestamps, thumbnail                           -> publish/

usage: python lf_run.py --project DIR [--topic "..."] [--idea outliers|own] [--minutes 8]
                        [--footage "url1,url2"] [--voice auto|elevenlabs|free|none] [--fresh]
"""
import argparse, json, os, re, statistics, sys, time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from common import is_video_url, media_ok, progress, run, stage, tool, ytdl_download, ytdl_search  # noqa: E402

N = 8  # stages


def ai():
    from desk import ai as _ai  # the configured provider (keys live in the app's private config)
    return _ai


def say(msg):
    print(msg, flush=True)


def wj(path, obj):
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    Path(path).write_text(json.dumps(obj, ensure_ascii=False, indent=1), encoding="utf-8")


def rj(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


USAGE = {"input": 0, "output": 0, "calls": 0}


def llm_json(system, prompt, effort="high"):
    data, u = ai().generate_json(system, prompt, effort=effort)
    USAGE["calls"] += 1
    USAGE["input"] += u.get("input") or 0
    USAGE["output"] += u.get("output") or 0
    return data


def llm_text(system, prompt, effort="high"):
    text, u = ai().generate(system, prompt, effort=effort)
    USAGE["calls"] += 1
    USAGE["input"] += u.get("input") or 0
    USAGE["output"] += u.get("output") or 0
    return text


BRIEF = ("You make long-form YouTube guides in the GTA 6 niche: map guides, mission walkthroughs, hidden locations, "
         "lore. Honesty rules: no invented numbers, no invented geography, no creator names on screen. Every fact is "
         "tagged official (Rockstar/Take-Two sources), measured, in-game or unverified; only official and measured "
         "facts may be stated as fact. Unverified things are framed as questions or rumours, or left out.")


# ---------------------------------------------------------------- 1 study
def study(d, topics):
    out = d / "research" / "outliers.json"
    if out.exists():
        return rj(out)
    q = f"gta 6 {topics.split(',')[0].strip()} guide"
    entries = ytdl_search(f"https://www.youtube.com/results?search_query={q.replace(' ', '+')}&sp=EgIYAw%253D%253D", 30)
    seen, rows = set(), []
    cands = [e for e in entries if e.get("channel_id") and e.get("view_count")]
    for k, e in enumerate(cands[:12]):
        if e["channel_id"] in seen:
            continue  # one video per channel
        seen.add(e["channel_id"])
        try:
            uploads = ytdl_search(f"https://www.youtube.com/channel/{e['channel_id']}/videos", 15)
            views = [u.get("view_count") for u in uploads if u.get("view_count")]
            usual = statistics.median(views) if views else None
        except Exception:
            usual = None
        score = (e["view_count"] / usual) if usual else None
        rows.append({"title": e.get("title"), "channel": e.get("channel"), "views": e["view_count"],
                     "usual_views": usual, "outlier": round(score, 2) if score else None,
                     "minutes": round((e.get("duration") or 0) / 60), "url": e.get("url")})
        progress(k + 1, min(12, len(cands)), "channels studied")
    rows.sort(key=lambda r: -(r["outlier"] or 0))
    wj(out, rows)
    md = ["# Outliers", "", "| outlier | views | usual | min | title |", "|---|---|---|---|---|"]
    md += [f"| {r['outlier']} | {r['views']:,} | {r['usual_views'] or ''} | {r['minutes']} | {r['title']} |" for r in rows]
    (d / "research" / "outliers.md").write_text("\n".join(md) + "\n", encoding="utf-8")
    return rows


# ---------------------------------------------------------------- 2 topic
def pick_topic(d, outliers, topics, idea, topic):
    out = d / "research" / "concept.json"
    if out.exists():
        return rj(out)
    ctx = json.dumps([{k: o[k] for k in ("title", "outlier", "minutes")} for o in outliers[:10]], ensure_ascii=False)
    ask = (f"Our topics: {topics}. " + (f"The user chose this topic, and every concept must be about it (not a different subject): {topic}. " if topic else "") +
           ("Study these niche outliers (title, outlier score = views / channel's usual views, length) and pitch three "
            f"concepts that ride what is already winning:\n{ctx}\n" if idea == "outliers" and outliers else
            "Pitch three original concepts players would care about this month.\n") +
           'Return {"concepts":[{"title":"","angle":"","why":"","needs_facts":[""]}],"pick":0,"pick_reason":""} '
           "where pick is the index of the strongest concept that can be fully sourced from official information.")
    data = llm_json(BRIEF, ask)
    concepts = data.get("concepts") if isinstance(data, dict) else data
    if not concepts:
        sys.exit("the model returned no concepts: press Retry or choose another model")
    try:
        pick = int(data.get("pick", 0)) if isinstance(data, dict) else 0
    except (TypeError, ValueError):
        pick = 0
    concept = concepts[pick if 0 <= pick < len(concepts) else 0]
    if not isinstance(concept, dict):
        concept = {"title": str(concept)}
    concept["pick_reason"] = data.get("pick_reason", "") if isinstance(data, dict) else ""
    wj(d / "research" / "concepts.json", data)
    wj(out, concept)
    return concept


# ---------------------------------------------------------------- 3 script
def write_script(d, concept, minutes, facts):
    out = d / "build" / "script.json"
    if out.exists():
        return rj(out)
    words = int(minutes * 150)
    ask = (f"Concept: {json.dumps(concept, ensure_ascii=False)}\nTarget length: about {words} spoken words "
           f"({minutes} minutes). Facts you may state (with sources):\n{facts or '(none provided: keep claims to what is officially announced and say so)'}\n"
           "Write one flowing spoken script, hedged exactly as much as the source, split into a cold open and 3-6 chapters. "
           'Return {"title":"","cold_open":"","chapters":[{"heading":"","narration":""}],'
           '"claims":[{"text":"","status":"official|measured|in-game|unverified","source":""}],'
           '"description":"","thumbnail_words":"max 3 words"}')
    script = llm_json(BRIEF, ask)
    wj(out, script)
    return script


# ---------------------------------------------------------------- 4 critics + judge + revision
CRITICS = {
    "story": "You are a story editor for YouTube guides. Judge the hook in the first 20 seconds, the chapter flow and the payoff.",
    "honesty": "You are a fact checker. Flag every claim stated as fact that is not official or measured, any invented number or place, and any creator name.",
    "pacing": "You are a retention analyst. Judge pacing, repetition, dead air and where viewers would drop off.",
}


def critic_loop(d, script):
    out = d / "build" / "script_final.json"
    if out.exists():
        return rj(out)
    rd = d / "rounds" / "round1"
    reports = {}
    for name, role in CRITICS.items():  # fresh, blind: they see only the script, never the brief or the sources
        reports[name] = llm_json(role, "Grade this script out of 10 and list concrete faults, worst first. "
                                       'Return {"score":0,"faults":[{"issue":"","fix":""}]}\n\n' + json.dumps(script, ensure_ascii=False),
                                 effort="medium")
        wj(rd / f"critic_{name}.json", reports[name])
    judge = llm_json("You are the judge. Check each critic's claims against the script itself and rank the fixes; "
                     "a factual-honesty defect always ranks first.",
                     'Return {"ranked_fixes":[{"fix":"","from":"","why":""}],"overall":0}\n\nScript:\n'
                     + json.dumps(script, ensure_ascii=False) + "\n\nCritics:\n" + json.dumps(reports, ensure_ascii=False))
    wj(rd / "judge.json", judge)
    fixed = llm_json(BRIEF, "Apply the top fixes (at most 5) to this script without changing its structure keys. "
                            "Return the full revised script JSON in the same shape.\n\nFixes:\n"
                     + json.dumps(judge.get("ranked_fixes", [])[:5], ensure_ascii=False) + "\n\nScript:\n" + json.dumps(script, ensure_ascii=False))
    if not fixed.get("chapters"):
        fixed = script
    wj(out, fixed)
    return fixed


# ---------------------------------------------------------------- 5 voice
def tts_eleven(text, path, key, voice_id):
    import requests
    if not voice_id:
        r = requests.get("https://api.elevenlabs.io/v1/voices", headers={"xi-api-key": key}, timeout=30)
        r.raise_for_status()
        voices = r.json().get("voices") or []
        if not voices:
            raise RuntimeError("no ElevenLabs voices on this account")
        voice_id = voices[0]["voice_id"]
    r = requests.post(f"https://api.elevenlabs.io/v1/text-to-speech/{voice_id}?output_format=mp3_44100_128",
                      headers={"xi-api-key": key}, json={"text": text, "model_id": "eleven_multilingual_v2"}, timeout=300)
    if r.status_code >= 400:
        raise RuntimeError(f"ElevenLabs error {r.status_code}: {r.text[:200]}")
    Path(path).write_bytes(r.content)


def tts_free(text, path):
    import asyncio, edge_tts
    text = re.sub(r"[<>&*_#`|~\[\]{}]", " ", text)  # markup the speech service may choke on
    text = re.sub(r"\s+", " ", text).strip()
    err = None
    for v in ("en-US-AndrewNeural", "en-US-GuyNeural"):
        try:
            asyncio.run(edge_tts.Communicate(text, v).save(str(path)))
            if path.exists() and path.stat().st_size > 1000:
                return
        except Exception as e:
            err = e
        path.unlink(missing_ok=True)
    raise err or RuntimeError("no audio from the Microsoft voice")


def on_android():
    try:
        from java import jclass
        jclass("com.claudegta6.vicedesk.Speech")
        return True
    except Exception:
        return False


def tts_phone(text, path):
    """The phone's built-in text-to-speech: offline and free. Long text goes in sentence chunks, joined by ffmpeg."""
    from java import jclass
    from com.chaquo.python import Python
    app, S = Python.getPlatform().getApplication(), jclass("com.claudegta6.vicedesk.Speech")
    limit = max(500, min(3000, int(S.maxChars()) - 100))
    chunks, cur = [], ""
    for s in re.split(r"(?<=[.!?])\s+", text.strip()):
        while len(s) > limit:  # one very long sentence
            chunks.append(s[:limit]); s = s[limit:]
        if cur and len(cur) + len(s) + 1 > limit:
            chunks.append(cur); cur = ""
        cur = (cur + " " + s).strip()
    if cur:
        chunks.append(cur)
    wavs = []
    try:
        for i, c in enumerate(chunks):
            w = path.with_name(f"{path.stem}.{i}.wav")
            err = str(S.synth(app, c, str(w)) or "")
            if err:
                raise RuntimeError(err)
            wavs.append(w)
        args = [tool("ffmpeg"), "-y", "-v", "error"]
        for w in wavs:
            args += ["-i", str(w)]
        run(args + ["-filter_complex", f"concat=n={len(wavs)}:v=0:a=1", "-ar", "44100", "-b:a", "160k", str(path)])
    finally:
        for w in wavs:
            w.unlink(missing_ok=True)


def tts_offline(text, path):
    """Free voice: Microsoft's (needs internet), else the phone's own voice on Android."""
    try:
        tts_free(text, path)
        return
    except Exception as e:
        path.unlink(missing_ok=True)
        if not on_android():
            raise
        first = e
    try:
        tts_phone(text, path)
    except Exception as e:
        raise RuntimeError(f"Microsoft voice: {str(first)[:80]}; phone voice: {str(e)[:120]}")


def voice(d, script, mode):
    cfg = ai().load()
    key, vid = cfg.get("eleven_key"), cfg.get("voice_id")
    parts = [("00_cold_open", script.get("cold_open", ""))] + [(f"{i + 1:02d}_chapter", c["narration"]) for i, c in enumerate(script["chapters"])]
    files = []
    for k, (name, text) in enumerate(parts):
        p = d / "voice" / f"{name}.mp3"
        p.parent.mkdir(parents=True, exist_ok=True)
        if not p.exists() and text.strip() and mode != "none":
            if mode in ("auto", "elevenlabs") and key:
                try:
                    tts_eleven(text, p, key, vid)
                except Exception:
                    p.unlink(missing_ok=True)
                    raise
            else:
                try:
                    tts_phone(text, p) if mode == "phone" else tts_offline(text, p)
                except Exception as e:
                    p.unlink(missing_ok=True)  # never keep a half-written file
                    say(f"free voice unavailable here ({str(e)[:80]}): building without voice-over")
                    mode = "none"
        if p.exists() and media_seconds(p) < 0.5:  # empty or broken audio
            p.unlink()
        files.append((p if p.exists() else None, text))
        progress(k + 1, len(parts), "voice parts")
    return files


# ---------------------------------------------------------------- 6 footage
def footage(d, urls, need_seconds=480):
    """Official footage only. Downloads just enough of each video to cover the narration (not whole videos)."""
    fd = d / "footage"
    fd.mkdir(parents=True, exist_ok=True)
    for f in fd.glob("src_*.mp4"):
        if not media_ok(f):  # an interrupted earlier run
            f.unlink()
    have = sorted(fd.glob("src_*.mp4"))
    if have:
        return have
    if not urls:  # official only: Rockstar Games' own channel
        say("finding official Rockstar Games videos")
        res = ytdl_search("https://www.youtube.com/results?search_query=grand+theft+auto+vi+trailer+rockstar+games", 15)
        urls = [e["url"] for e in res if (e.get("channel") or "").lower().strip() == "rockstar games"
                and is_video_url(e.get("url")) and (e.get("duration") or 61) > 60
                and e.get("live_status") not in ("is_live", "is_upcoming")][:2]
        if not urls:
            sys.exit("no official footage found: paste official trailer/gameplay URLs in the Long-form form")
    bad = [u for u in urls if not is_video_url(u)]
    if bad:
        say("skipping links that are not single videos (channel or playlist pages): " + ", ".join(bad))
    urls = [u for u in urls if is_video_url(u)][:4]
    if not urls:
        sys.exit("no single-video links for footage: paste official trailer/gameplay video URLs (youtube.com/watch?v=...)")
    # each source is reused across chapters: about the narration length split across sources, plus a margin
    per = int(min(600, max(90, need_seconds / len(urls) + 45)))
    h = int(os.environ.get("VICE_MAX_HEIGHT") or 1080)  # 720 on phones: lighter and less often refused
    for i, u in enumerate(urls):
        say(f"official video {i + 1} of {len(urls)}: {u} (first {per // 60}:{per % 60:02d})")
        out = fd / f"src_{i}.mp4"
        ytdl_download(u, out, f"bv*[height<={h}][ext=mp4]+ba[ext=m4a]/bv*[height<={h}]+ba/b[height<={h}]/b", max_seconds=per)
        say(f"  done: {out.stat().st_size / 1e6:.1f} MB" if out.exists() else "  done")
        progress(i + 1, len(urls), "official videos downloaded")
    return sorted(fd.glob("src_*.mp4"))


def media_seconds(p):
    r = run([tool("ffprobe"), "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", str(p)], capture=True, check=False)
    try:
        return float(r.stdout.strip())
    except ValueError:
        return 0.0


# ---------------------------------------------------------------- 7 build
def ass_time(t):
    return f"{int(t // 3600)}:{int(t % 3600 // 60):02d}:{t % 60:05.2f}"


def build(d, script, voices, sources):
    out = d / "build" / "draft.mp4"
    heads = ["Cold open"] + [c["heading"] for c in script["chapters"]]
    fonts = str(Path(__file__).parent / "fonts")
    pieces, cursor, chapters_at, t_total = [], [0.0] * len(sources), [], 0.0
    lengths = [media_seconds(s) for s in sources]
    for i, ((vo, text), head) in enumerate(zip(voices, heads)):
        dur = media_seconds(vo) if vo else max(6.0, len(text.split()) / 2.5)
        src = sources[i % len(sources)]
        start = max(6.0, cursor[i % len(sources)])
        if start + dur > lengths[i % len(sources)] - 2:
            start = 6.0
        cursor[i % len(sources)] = start + dur
        sents = [s.strip() for s in re.split(r"(?<=[.!?])\s+", text) if s.strip()]
        total_w = sum(len(s.split()) for s in sents) or 1
        ev, t = [], 0.0
        for s in sents:
            sd = dur * len(s.split()) / total_w
            ev.append(f"Dialogue: 0,{ass_time(t)},{ass_time(t + sd)},Cap,,0,0,0,,{s.replace('{', '(').replace('}', ')')}")
            t += sd
        if i > 0:
            ev.append(f"Dialogue: 1,{ass_time(0)},{ass_time(min(3.2, dur))},Chap,,0,0,0,,{{\\fad(250,300)\\fax-0.1}}CHAPTER {i}\\N{head.upper()}")
        ass = d / "build" / f"part_{i:02d}.ass"
        ass.write_text("[Script Info]\nScriptType: v4.00+\nPlayResX: 1920\nPlayResY: 1080\nWrapStyle: 0\n\n[V4+ Styles]\n"
                       "Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding\n"
                       "Style: Cap,Inter,46,&H00FFFFFF,&H00FFFFFF,&H00000000,&H90000000,-1,0,0,0,100,100,0,0,1,4,2,2,160,160,70,1\n"
                       "Style: Chap,Inter Black,84,&H00FFFFFF,&H00FFFFFF,&H008B3DFF,&H003D8AFF,-1,0,0,0,100,100,2,0,1,5,6,7,110,110,110,1\n\n"
                       "[Events]\nFormat: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text\n" + "\n".join(ev) + "\n",
                       encoding="utf-8")
        part = d / "build" / f"part_{i:02d}.mp4"
        sub = str(ass).replace("\\", "/").replace(":", "\\:")
        fd_ = fonts.replace("\\", "/").replace(":", "\\:")
        cmd = [tool("ffmpeg"), "-y", "-v", "error", "-ss", f"{start:.2f}", "-t", f"{dur:.2f}", "-i", str(src)]
        if vo:
            cmd += ["-i", str(vo)]
        cmd += ["-filter_complex", f"[0:v]scale=1920:1080:force_original_aspect_ratio=increase,crop=1920:1080,fps=30,"
                                   f"subtitles='{sub}':fontsdir='{fd_}'[v]",
                "-map", "[v]", "-map", "1:a" if vo else "0:a?", "-c:v", "libx264", "-preset", "veryfast", "-crf", "21",
                "-pix_fmt", "yuv420p", "-c:a", "aac", "-ar", "48000", "-ac", "2", "-shortest", str(part)]
        run(cmd)
        pieces.append(part)
        chapters_at.append((t_total, head))
        t_total += dur
        progress(i + 1, len(heads), "parts built")
    lst = d / "build" / "parts.txt"
    lst.write_text("".join(f"file '{p.resolve().as_posix()}'\n" for p in pieces), encoding="utf-8")
    run([tool("ffmpeg"), "-y", "-v", "error", "-f", "concat", "-safe", "0", "-i", str(lst), "-c:v", "copy",
         "-af", "loudnorm=I=-14:TP=-1.5:LRA=11", "-c:a", "aac", "-b:a", "192k", "-movflags", "+faststart", str(out)])
    return out, chapters_at


# ---------------------------------------------------------------- 8 publish
def publish(d, script, chapters_at, draft, sources):
    pd = d / "publish"
    pd.mkdir(parents=True, exist_ok=True)
    stamp = lambda t: f"{int(t // 60)}:{int(t % 60):02d}"
    chapters = "\n".join(f"{stamp(t)} {h}" for t, h in chapters_at)
    cites = sorted({c.get("source", "") for c in script.get("claims", []) if c.get("status") in ("official", "measured") and c.get("source")})
    desc = (script.get("description", "").strip() + "\n\nChapters\n" + chapters +
            ("\n\nSources\n" + "\n".join(cites) if cites else "") + "\n\nFootage: official Rockstar Games trailers and gameplay.\n")
    (pd / "title.txt").write_text(script.get("title", "").strip() + "\n", encoding="utf-8")
    (pd / "description.txt").write_text(desc, encoding="utf-8")
    words = " ".join(str(script.get("thumbnail_words", "")).split()[:3]).upper()
    clean = sources[0]  # thumbnail from clean official footage (the draft has captions burned in)
    at = max(1.0, media_seconds(clean) * 0.6)  # a late, payoff-ish frame
    ass = pd / "thumb.ass"
    ass.write_text("[Script Info]\nScriptType: v4.00+\nPlayResX: 1280\nPlayResY: 720\n\n[V4+ Styles]\nFormat: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding\n"
                   "Style: T,Inter Black,150,&H00FFFFFF,&H00FFFFFF,&H008B3DFF,&H003D8AFF,-1,0,0,0,100,100,0,0,1,10,10,1,70,70,60,1\n\n"
                   f"[Events]\nFormat: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text\nDialogue: 0,0:00:00.00,0:00:05.00,T,,0,0,0,,{{\\fax-0.1}}{words}\n", encoding="utf-8")
    sub = str(ass).replace("\\", "/").replace(":", "\\:")
    fd_ = str(Path(__file__).parent / "fonts").replace("\\", "/").replace(":", "\\:")
    run([tool("ffmpeg"), "-y", "-v", "error", "-ss", f"{at:.2f}", "-i", str(clean), "-frames:v", "1",
         "-vf", f"scale=1280:720,subtitles='{sub}':fontsdir='{fd_}'", str(pd / "thumbnail.jpg")])
    return pd


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--project", required=True); ap.add_argument("--topic", default="")
    ap.add_argument("--topics", default="map guides, mission walkthroughs, hidden locations, lore")
    ap.add_argument("--idea", choices=["outliers", "own"], default="outliers"); ap.add_argument("--minutes", type=float, default=8)
    ap.add_argument("--footage", default=""); ap.add_argument("--voice", choices=["auto", "elevenlabs", "free", "phone", "none"], default="auto")
    ap.add_argument("--fresh", action="store_true", help="start a new run instead of resuming the last one")
    a = ap.parse_args()
    d = Path(a.project)
    runs = d / "runs"
    last = sorted(runs.glob("run_*")) if runs.exists() else []
    # Continue the last run only if it is the same request (a Retry) and it never finished;
    # a new topic, idea or length always starts a new run.
    want = {"topic": a.topic.strip(), "topics": a.topics.strip(), "idea": a.idea, "minutes": float(a.minutes),
            "footage": a.footage.strip()}
    rd = None
    if last and not a.fresh and not (last[-1] / "publish" / "thumbnail.jpg").exists():
        try:
            if json.loads((last[-1] / "request.json").read_text(encoding="utf-8")) == want:
                rd = last[-1]
        except Exception:
            pass
    if rd is None:
        rd = runs / time.strftime("run_%Y%m%d_%H%M%S")
    else:
        say("continuing the unfinished run for this same request")
    rd.mkdir(parents=True, exist_ok=True)
    (rd / "request.json").write_text(json.dumps(want), encoding="utf-8")
    say(f"run folder: {rd}")
    m = ai().public()
    say(f"model: {m['providers'][m['provider']]['label']} · {m['model']}")
    facts_file = d / "facts.md"
    facts = facts_file.read_text(encoding="utf-8") if facts_file.exists() else ""
    stage(1, N, "Studying the niche (outliers)")
    outliers = study(rd, a.topic.strip() or a.topics) if a.idea == "outliers" else []
    stage(2, N, "Choosing the topic")
    concept = pick_topic(rd, outliers, a.topics, a.idea, a.topic)
    say(f"concept: {concept.get('title')} | {concept.get('pick_reason', '')[:140]}")
    stage(3, N, "Writing the script")
    script = write_script(rd, concept, a.minutes, facts)
    stage(4, N, "Critics, judge and revision")
    script = critic_loop(rd, script)
    unverified = [c["text"] for c in script.get("claims", []) if c.get("status") == "unverified"]
    if unverified:
        say(f"{len(unverified)} unverified claim(s) kept off-screen as facts: see build/script_final.json")
    stage(5, N, "Voice-over")
    voices = voice(rd, script, a.voice)
    stage(6, N, "Official footage")
    words = len((script.get("cold_open", "") + " " + " ".join(c.get("narration", "") for c in script.get("chapters", []))).split())
    sources = footage(rd, [u.strip() for u in a.footage.replace("\n", ",").split(",") if u.strip()],
                      need_seconds=max(60, words / 2.5))
    stage(7, N, "Building the rough cut")
    draft, chapters_at = build(rd, script, voices, sources)
    stage(8, N, "Title, description, thumbnail")
    pd = publish(rd, script, chapters_at, draft, sources)
    (rd / "usage.json").write_text(json.dumps(USAGE), encoding="utf-8")
    say(f"AI usage: {USAGE['calls']} calls, {USAGE['input']:,} input + {USAGE['output']:,} output tokens")
    say(f"draft: {draft}")
    say(f"publish pack: {pd}")


if __name__ == "__main__":
    main()
