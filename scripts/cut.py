"""Cut one candidate into a finished vertical clip.

1080x1920, 30 fps, word-by-word burned captions (slurs and swears masked), hook box in the first seconds,
loudness normalised to -14 LUFS. Writes jobs/<id>/edits/clip_<n>.mp4 + .json (metadata for check.py).

usage: python cut.py jobs/<id> --pick 1 [--layout fill|blur|facecam|react] [--hook "TEXT"]
                     [--cam auto|x:y:w:h] [--title "TEXT" --title-style box|outline --title-secs 0] [--captions word|bubble|none]
                     [--punch 0.15] [--clean-audio] [--fps 30|60]
Also writes clip_<n>.srt and clip_<n>.ass next to the clip, for finishing touches in Kdenlive, Shotcut or OpenCut.
"""
import argparse, os, sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent))
from common import load_json, run_ffmpeg, save_json, stage, tool

W, H = 1080, 1920  # set per --platform in main()
PLATFORMS = {  # output frame per destination
    "vertical": (1080, 1920),   # TikTok, Instagram Reels, YouTube Shorts, Snapchat
    "landscape": (1920, 1080),  # YouTube, X / Twitter
    "feed": (1080, 1350),       # Instagram / Facebook feed (4:5)
    "square": (1080, 1080),     # square posts
}
CAM_PRESETS = {  # webcam box (x:y:w:h fractions) when it cannot be detected automatically
    "top-left": "0:0:0.26:0.30", "top-right": "0.74:0:0.26:0.30",
    "bottom-left": "0:0.70:0.26:0.30", "bottom-right": "0.74:0.70:0.26:0.30",
}


def ts(t):
    t = max(0, t); h = int(t // 3600); m = int(t % 3600 // 60); s = t % 60
    return f"{h}:{m:02d}:{s:05.2f}"


import re as _re
_SLURS = _re.compile(r"\b(nigg\w*|n[i1]gg?a\w*|f[a@]gg?\w*|retard\w*|tranny\w*|chink\w*|spic\w*|kike\w*)\b", _re.I)


_SWEARS = _re.compile(r"\b(fuck\w*|motherfuck\w*|shit\w*|bitch\w*|cunt\w*|dick\w*|pussy\w*|asshole\w*|bastard\w*|whore\w*|slut\w*)\b", _re.I)


def _mask(m):
    w = m.group(0)
    return w[0] + '*' * (len(w) - 1)


def clean(s, profanity=False):
    """Slurs are always masked (n-word -> n****); hard swears too unless profanity=True."""
    s = _SLURS.sub(_mask, s)
    return s if profanity else _SWEARS.sub(_mask, s)


def esc(s):
    return s.replace("\\", "").replace("{", "(").replace("}", ")").replace("\n", " ")


def wrap(text, width):
    lines, cur = [], ''
    for wd in text.split():
        if cur and len(cur) + 1 + len(wd) > width:
            lines.append(cur); cur = wd
        else:
            cur = (cur + ' ' + wd).strip()
    return lines + ([cur] if cur else [])


def caption_groups(words, s0, e0, profanity=False):
    """Words of [s0, e0) in groups of up to 3, broken on punctuation or pauses (shared by .ass and .srt)."""
    ws = [dict(w, w=clean(w["w"], profanity)) for w in words if s0 <= w["s"] < e0 and w["w"]]
    groups, cur = [], []
    for w in ws:
        if cur and (len(cur) == 3 or w["s"] - cur[-1]["e"] > 0.6 or cur[-1]["w"][-1:] in ".?!,"):
            groups.append(cur); cur = []
        cur.append(w)
    if cur:
        groups.append(cur)
    return groups


def export_subs(groups, s0, hook, base):
    """Editable subtitles for desktop editors: <base>.srt (plain) and <base>.ass (styled, rendered by libass)."""
    try:
        import pysubs2
    except ImportError:
        print("pysubs2 not installed: skipping .srt export")
        return
    subs = pysubs2.SSAFile()
    if hook:
        subs.append(pysubs2.SSAEvent(start=0, end=2600, text=hook))
    for gi, g in enumerate(groups):
        end = groups[gi + 1][0]["s"] if gi + 1 < len(groups) else g[-1]["e"] + 0.4
        end = min(end, g[-1]["e"] + 0.8)
        subs.append(pysubs2.SSAEvent(start=int((g[0]["s"] - s0) * 1000), end=int((end - s0) * 1000),
                                     text=" ".join(x["w"] for x in g)))
    subs.save(str(base.with_suffix(".srt")))


PALETTE = {  # name -> hex; the UI offers these swatches
    "vice": "#e8457f", "sunset": "#ff7a3d", "gold": "#f5c542", "mint": "#3ddc97",
    "ocean": "#2f8cff", "neon": "#9b5cff", "night": "#141018", "snow": "#f4f1ec",
}


def hex_color(c, default="#e8457f"):
    c = PALETTE.get((c or "").lower(), c or default)
    c = c if _re.fullmatch(r"#?[0-9a-fA-F]{6}", c or "") else default
    return "#" + c.lstrip("#").lower()


def ass_color(c, alpha=0):
    """#rrggbb -> ASS &HAABBGGRR."""
    h = hex_color(c).lstrip("#")
    return f"&H{alpha:02X}{h[4:6]}{h[2:4]}{h[0:2]}".upper()


def tag_color(c):
    """#rrggbb -> &HBBGGRR& for inline override tags (\\1c, \\3c)."""
    h = hex_color(c).lstrip("#")
    return f"&H{h[4:6]}{h[2:4]}{h[0:2]}&".upper()


def context_from_title(title, channel=""):
    """'GTA 6 SECRET 🔥 | Ep 3 #gta6 (4K)' -> 'GTA 6 secret' style: one clean line about what the video is."""
    t = _re.sub(r"[\U00010000-\U0010FFFF\u2600-\u27BF]", "", title or "")       # emoji
    t = _re.sub(r"#\w+", "", t)                                                     # hashtags
    t = _re.sub(r"[\[(][^\])]*[\])]", "", t)                                       # (4K) [LIVE]
    t = _re.split(r"\s[|•–—]\s|\s-\s", t)[0]                                       # first part only
    t = " ".join(t.split()).strip(" -:|")
    if t.isupper() and len(t) > 6:
        t = t.capitalize()
    if len(t) > 58:
        t = t[:58].rsplit(" ", 1)[0] + "…"
    if channel and t:
        t += f"  ·  via {channel.strip()[:24]}"
    return t


def brand_events(dur, context, handle, accent, has_hook, pill=None):
    """Context banner for the first seconds and an animated @handle end card for the last 2.5 s."""
    ev = []
    acc = tag_color(accent)
    pill_c = tag_color(pill or accent)
    if context:
        y = int(H * (0.19 if has_hook else 0.085))
        end = min(3.4, max(1.5, dur - 0.5))
        # small accent tag + dark pill, sliding down into place
        ev.append(f"Dialogue: 3,{ts(0.15)},{ts(end)},Ctx,,0,0,0,,{{\\an8\\move({W // 2},{y - 40},{W // 2},{y},0,260)"
                  f"\\fad(220,260)\\3c{pill_c}}}{esc(context)}")
    if handle and dur >= 5:
        h = handle.strip()
        h = h if h.startswith("@") else "@" + h
        t0 = max(0.0, dur - 2.5)
        cy = H // 2
        bar_w = min(int(W * 0.62), 60 + 44 * len(h))
        ev += [
            # dim the frame
            f"Dialogue: 4,{ts(t0)},{ts(dur)},Fx,,0,0,0,,{{\\an7\\pos(0,0)\\p1\\1c&H000000&\\1a&HFF&\\t(0,350,\\1a&H50&)\\bord0\\shad0}}"
            f"m 0 0 l {W} 0 {W} {H} 0 {H}{{\\p0}}",
            # @handle pops in (overshoot then settle)
            f"Dialogue: 5,{ts(t0 + 0.12)},{ts(dur)},Handle,,0,0,0,,{{\\an5\\pos({W // 2},{cy})\\fad(150,0)"
            f"\\fscx55\\fscy55\\t(0,260,\\fscx108\\fscy108)\\t(260,420,\\fscx100\\fscy100)}}{esc(h)}",
            # accent underline grows from the centre
            f"Dialogue: 5,{ts(t0 + 0.35)},{ts(dur)},Fx,,0,0,0,,{{\\an5\\pos({W // 2},{cy + 78})\\p1\\1c{acc}\\bord0\\shad0"
            f"\\fscx0\\t(0,380,\\fscx100)}}m 0 0 l {bar_w} 0 {bar_w} 12 0 12{{\\p0}}",
            # 'Follow for more' fades up
            f"Dialogue: 5,{ts(t0 + 0.6)},{ts(dur)},OutroSub,,0,0,0,,{{\\an5\\move({W // 2},{cy + 150},{W // 2},{cy + 132},0,300)"
            f"\\alpha&HFF&\\t(0,300,\\alpha&H00&)}}Follow for more",
        ]
    return ev


def build_ass(words, s0, e0, hook, cap_y, title=None, caps='word', profanity=False, context="", handle="", accent=None, pill=None):
    hdr = f"""[Script Info]
ScriptType: v4.00+
PlayResX: {W}
PlayResY: {H}
WrapStyle: 0

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Cap,Inter Black,92,&H00FFFFFF,&H0000E5FF,&H00000000,&H64000000,-1,0,0,0,100,100,0,0,1,7,3,5,60,60,0,1
Style: Hook,Inter Black,68,&H00000000,&H00000000,&H00FFFFFF,&H00FFFFFF,-1,0,0,0,100,100,0,0,3,18,0,8,70,70,170,1
Style: TitleBox,Inter Black,66,&H00000000,&H00000000,&H00FFFFFF,&H00FFFFFF,-1,0,0,0,100,100,0,0,1,0,0,5,40,40,0,1
Style: TitleOut,Inter Black,80,&H00FFFFFF,&H00FFFFFF,&H00000000,&H64000000,-1,0,0,0,100,100,0,0,1,9,2,8,50,50,0,1
Style: Bubble,Inter,58,&H00000000,&H00000000,&H00FFFFFF,&H00FFFFFF,-1,0,0,0,100,100,0,0,3,16,0,5,60,60,0,1
Style: Ctx,Inter,46,&H00FFFFFF,&H00FFFFFF,&H00E8457F,&H40140B18,-1,0,0,0,100,100,1,0,3,14,0,8,60,60,0,1
Style: Handle,Inter Black,104,&H00FFFFFF,&H00FFFFFF,&H00000000,&H80000000,-1,0,0,0,100,100,0,0,1,6,4,5,40,40,0,1
Style: OutroSub,Inter,50,&H00FFFFFF,&H00FFFFFF,&H00000000,&H80000000,0,0,0,0,100,100,2,0,1,3,2,5,40,40,0,1
Style: Fx,Inter,20,&H00FFFFFF,&H00FFFFFF,&H00000000,&H00000000,0,0,0,0,100,100,0,0,1,0,0,7,0,0,0,1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""
    ev = []
    dur = e0 - s0
    if handle and dur >= 5:  # leave the last 2.5 s to the end card
        words = [w for w in words if w["s"] < e0 - 2.5]
    groups = caption_groups(words, s0, e0, profanity)
    hook_end = 2.6 if hook else 0
    for gi, g in enumerate(groups):
        g_end = groups[gi + 1][0]["s"] if gi + 1 < len(groups) else g[-1]["e"] + 0.4
        g_end = min(g_end, g[-1]["e"] + 0.8)
        for k, w in enumerate(g):
            a = w["s"] - s0; b = (g[k + 1]["s"] - s0) if k + 1 < len(g) else g_end - s0
            if b <= a:
                continue
            parts = []
            for j, x in enumerate(g):
                t = esc(x["w"].upper())
                parts.append("{\\c&H0000E5FF&}" + t + "{\\c&H00FFFFFF&}" if j == k else t)
            pop = "{\\fscx112\\fscy112\\t(0,90,\\fscx100\\fscy100)}" if k == 0 else ""
            if caps == 'bubble':
                if k == 0:
                    txt = esc(' '.join(x['w'] for x in g)).strip()
                    txt = txt[:1].upper() + txt[1:]
                    ev.append(f"Dialogue: 0,{ts(a)},{ts(g_end - s0)},Bubble,,0,0,0,,{{\\pos({W // 2},{cap_y})}}{pop}{txt}")
                continue
            ev.append(f"Dialogue: 0,{ts(a)},{ts(b)},Cap,,0,0,0,,{{\\pos({W // 2},{cap_y})}}{pop}{' '.join(parts)}")
    if title:  # reaction title: (style, text, y, seconds)
        st, text, ty, secs = title
        end = (e0 - s0) if secs <= 0 else secs
        lines = wrap(esc(text), 26 if st == 'box' else 24)
        body = '\\N'.join(lines)
        if st == 'box':
            ev.append(f"Dialogue: 2,{ts(0)},{ts(end)},TitleBox,,0,0,0,,{{\\pos({W // 2},{ty})}}{body}")
        else:
            ev.append(f"Dialogue: 2,{ts(0)},{ts(end)},TitleOut,,0,0,0,,{{\\pos({W // 2},{ty})\\an8}}{body}")
        hook = ''
    if hook:
        ev.append(f"Dialogue: 1,{ts(0)},{ts(hook_end)},Hook,,0,0,0,,{{\\fad(0,180)\\fscx92\\fscy92\\t(0,120,\\fscx100\\fscy100)}}{esc(hook)}")
    ev += brand_events(dur, context, handle, accent or "#e8457f", bool(hook), pill)
    return hdr + "\n".join(ev) + "\n"


CAP_Y = {"fill": 1380, "blur": 1460, "facecam": 1120, "react": 1560}
TOP = 730  # react layout: face panel height = seam y (even)
GAME_H = H - TOP  # 1190


def even(n):
    return int(n) // 2 * 2


def punch_filter(a, b, z):
    """Zoom in by z (0.15 = 15%) between clip times a and b with short eases: the 'punch in' on the reaction."""
    e = f"(1+{z:.3f}*min(1,max(0,(t-{a:.2f})/0.18))*min(1,max(0,({b:.2f}-t)/0.35)))"
    return f"scale=w='trunc(iw*{e}/2)*2':h='trunc(ih*{e}/2)*2':eval=frame,crop={W}:{H},"


def video_filter(layout, cam, ass, band=None, cam_side='right', src=None, game_x=None, face_expr=None, punch=None, fps=30,
                 bg="blur", bg_color=None):
    """Layout + burned-caption filter graph ending in [vo]. Reused by translate.py."""
    if layout == "fill":
        v = f"[0:v]scale=-2:{H},crop={W}:{H}[v]"
    elif layout == "blur":
        lift = 80 if H > W else 0
        col = hex_color(bg_color).replace("#", "0x")
        if bg == "solid":    # flat colour from the palette behind the video
            v = (f"color=c={col}:s={W}x{H}:r=30[bg];[0:v]scale={W}:-2[fg];"
                 f"[bg][fg]overlay=(W-w)/2:(H-h)/2-{lift}:shortest=1[v]")
        elif bg == "tint":   # blurred video washed with the palette colour
            v = (f"[0:v]split[a][b];[a]scale=-2:{H},crop={W}:{H},boxblur=24:2,eq=brightness=-0.05[bl];"
                 f"color=c={col}@0.55:s={W}x{H}:r=30[tc];[bl][tc]overlay=shortest=1[bg];"
                 f"[b]scale={W}:-2[fg];[bg][fg]overlay=(W-w)/2:(H-h)/2-{lift}[v]")
        else:
            v = (f"[0:v]split[a][b];[a]scale=-2:{H},crop={W}:{H},boxblur=24:2,eq=brightness=-0.08[bg];"
                 f"[b]scale={W}:-2[fg];[bg][fg]overlay=(W-w)/2:(H-h)/2-{lift}[v]")
    elif layout == 'react':
        sw, sh = src
        if face_expr:  # tracked face crop (no cam frame)
            cw, chh, ex, ey = face_expr
            top = f"crop={cw}:{chh}:{ex}:{ey}"
        else:
            x, y, w, h = map(float, cam.split(':'))
            cw, chh = even(sw * w), even(sh * h)
            top = f"crop={cw}:{chh}:{even(sw * x)}:{even(sh * y)}"
        gw = even(sw * GAME_H / sh) if sw * GAME_H / sh >= W else W
        gx = game_x if game_x is not None else ((gw - W) if cam_side == 'left' else 0)
        v = (f"[0:v]split[a][b];[a]{top},scale={W}:{TOP}:force_original_aspect_ratio=increase,crop={W}:{TOP},setsar=1[cam];"
             f"[b]scale={gw}:{GAME_H},crop={W}:{GAME_H}:{even(gx)}:0,setsar=1[game];[cam][game]vstack[v]")
        if band:
            y0, bh, secs = band
            en = f":enable='lte(t,{secs})'" if secs > 0 else ''
            v = v[:-3] + f"[v0];[v0]drawbox=x=0:y={y0}:w=iw:h={bh}:color=white@1:t=fill{en}[v]"
    else:
        x, y, w, h = map(float, cam.split(":"))
        ch = even(H * 0.38); gh = H - ch  # even heights: odd ones get rounded and the frame ends up 2 px short
        v = (f"[0:v]split[a][b];[a]crop=iw*{w}:ih*{h}:iw*{x}:ih*{y},scale={W}:{ch}:force_original_aspect_ratio=increase,"
             f"crop={W}:{ch}[cam];[b]scale=-2:{gh},crop={W}:{gh}[game];[cam][game]vstack[v]")
    sub = str(ass).replace("\\", "/").replace(":", "\\:")
    # bundled Inter fonts: the same look on every platform, and text renders even where system fonts are missing
    fonts = str(Path(__file__).resolve().parent / "fonts")
    if not os.path.isdir(fonts):
        fonts = os.environ.get("VICE_FONTS_DIR", "")
    if fonts:
        sub += "':fontsdir='" + fonts.replace("\\", "/").replace(":", "\\:")
    zoom = punch_filter(*punch) if punch else ""
    # 60 fps: motion-compensated interpolation (a CPU stand-in for RIFE); slow, so it is opt-in
    rate = "fps=30" if fps != 60 else "minterpolate=fps=60:mi_mode=mci:mc_mode=aobmc:me_mode=bidir:vsbmc=1"
    return v + f";[v]{zoom}{rate},subtitles='{sub}'[vo]"


def game_offset(video, s0, e0, src, cam_box):
    """Pick the x offset of the 1080-wide game crop that avoids static overlays (viewer counters,
    alerts, chat boxes) and the webcam. Static = pixels that barely change across sampled frames
    but carry edges (text/graphics)."""
    try:
        import cv2, numpy as np
    except ImportError:
        return None
    sw, sh = src
    gw = even(sw * GAME_H / sh)
    if gw <= W:
        return 0
    cap = cv2.VideoCapture(str(video)); frames = []
    for k in range(12):
        cap.set(cv2.CAP_PROP_POS_MSEC, (s0 + (e0 - s0) * (k + 0.5) / 12) * 1000)
        ok, f = cap.read()
        if ok:
            frames.append(cv2.resize(cv2.cvtColor(f, cv2.COLOR_BGR2GRAY), (gw, GAME_H)).astype(np.float32))
    cap.release()
    if len(frames) < 4:
        return None
    st = np.stack(frames)
    std = st.std(0); med = np.median(st, 0)
    edges = cv2.Canny(med.astype(np.uint8), 60, 160) > 0
    bad = (std < 6) & cv2.dilate(edges.astype(np.uint8), np.ones((9, 9), np.uint8)).astype(bool)
    x, y, w, h = cam_box  # the cam itself also counts as overlay
    bad[int(y * GAME_H):int((y + h) * GAME_H), int(x * gw):int((x + w) * gw)] = True
    col = bad.sum(0).astype(np.float64); cs = np.concatenate([[0], np.cumsum(col)])
    best, bx = None, 0
    camcols = np.zeros(gw); camcols[int(x * gw):int((x + w) * gw)] = 1; cc = np.concatenate([[0], np.cumsum(camcols)])
    for ox in range(0, gw - W + 1, 8):
        # never show the cam twice; otherwise stay near the centre (game subtitles and action sit there),
        # moving off-centre only when that clearly removes a static overlay (counters, alerts, chat)
        if cc[ox + W] - cc[ox] > 0 and (cc[-1] < gw - W):
            continue
        cost = (cs[ox + W] - cs[ox]) * 0.2 + abs(ox - (gw - W) / 2) * GAME_H * 0.05
        if best is None or cost < best:
            best, bx = cost, ox
    return bx


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("job"); ap.add_argument("--pick", type=int, default=1)
    ap.add_argument("--layout", choices=["fill", "blur", "facecam", "react"], default="blur")
    ap.add_argument("--title", default="", help="reaction title, e.g. 'Speed REALIZED why GTA 6 took 13 YEARS'")
    ap.add_argument("--title-style", choices=["box", "outline"], default="box")
    ap.add_argument("--title-secs", type=float, default=0, help="0 = whole clip")
    ap.add_argument("--captions", choices=["word", "bubble", "none"], default="word")
    ap.add_argument("--hook", default="")
    ap.add_argument("--allow-profanity", action="store_true", help="keep swear words in captions (slurs are always masked)")
    ap.add_argument("--cam", default="auto", help="auto (find the webcam), top-left/top-right/bottom-left/bottom-right, or x:y:w:h fractions")
    ap.add_argument("--platform", choices=list(PLATFORMS), default="vertical",
                    help="vertical 9:16 (TikTok/Reels/Shorts), landscape 16:9 (YouTube/X), feed 4:5, square 1:1")
    ap.add_argument("--start", type=float); ap.add_argument("--end", type=float)
    ap.add_argument("--context", default="", help='"auto" = a line about the video from its title, or your own text')
    ap.add_argument("--outro-handle", default="", help="end the clip with an animated card showing this @account")
    ap.add_argument("--bg", choices=["blur", "tint", "solid"], default="blur", help="background of the blur layout")
    ap.add_argument("--bg-color", default="vice", help="palette name (" + ", ".join(PALETTE) + ") or #rrggbb")
    ap.add_argument("--punch", type=float, default=0, help="zoom in this much on the peak moment, e.g. 0.15 (0 = off)")
    ap.add_argument("--clean-audio", action="store_true", help="reduce mic/background noise before loudness normalising")
    ap.add_argument("--fps", type=int, choices=[30, 60], default=30, help="60 = smooth motion interpolation (slow)")
    a = ap.parse_args()
    global W, H, GAME_H
    W, H = PLATFORMS[a.platform]
    GAME_H = H - TOP
    a.cam = CAM_PRESETS.get(a.cam, a.cam)
    if a.platform != "vertical" and a.layout in ("facecam", "react"):
        print(f"{a.layout} layout stacks the webcam above the game, which needs a 9:16 frame: using blur for {a.platform}")
        a.layout = "blur"
    d = Path(a.job); c = load_json(d / "candidates.json")
    stage(1, 2, f"Preparing clip {a.pick}")
    pick = next((x for x in c["candidates"] if x["n"] == a.pick), None)
    if pick is None:
        sys.exit(f"no candidate #{a.pick} in {d / 'candidates.json'} (have {[x['n'] for x in c['candidates']]})")
    s0 = a.start if a.start is not None else pick["start"]; e0 = a.end if a.end is not None else pick["end"]
    tr = d / "transcript.json"
    words = load_json(tr) if tr.exists() else []
    if not words:
        print("no transcript for this job: cutting without captions")
    out = d / "edits"; out.mkdir(exist_ok=True)
    layout, cam, side = a.layout, a.cam, 'right'
    face_expr = None
    if layout in ('react', 'facecam') and cam == 'auto':
        try:
            from facecam import find_cam
        except ImportError:  # e.g. the Android app has no OpenCV: no automatic webcam detection
            print("automatic webcam detection is not available here: using the blur layout. "
                  "Pick the webcam position (top-left, top-right, ...) to use the facecam layout.")
            layout = 'blur'
    if layout in ('react', 'facecam') and cam == 'auto':
        r = find_cam(c['source'], s0, e0)
        if layout == 'react' and r.get('mode') not in ('cam', 'face'):
            sys.exit(f"skipped: no streamer face over gameplay in this moment ({r.get('mode')}: {r.get('reason', '')}). "
                     "React clips need the game on screen with the cam as a separate box. Pick another moment or stream.")
        if layout == 'react':
            from facecam import has_gameplay, face_crop_expr
            if not has_gameplay(c['source'], s0, e0, r['box']):
                sys.exit("skipped: the area outside the webcam is not gameplay (same scene or no game on screen). "
                         "Pick a moment where GTA 6 is on screen.")
            if r.get('mode') == 'face' and r.get('face_track'):
                from common import ffprobe as _fp
                _vs = [x for x in _fp(c['source'])['streams'] if x.get('codec_type') == 'video'][0]
                from facecam import inner_edges
                sw_, sh_ = int(_vs['width']), int(_vs['height'])
                bnd = inner_edges(c['source'], s0, e0, r['face'], sw_, sh_)
                print(f'facecam: cam borders L{bnd[0]} T{bnd[1]} R{bnd[2]} B{bnd[3]} px')
                fe = face_crop_expr(r['face_track'], sw_, sh_, W, TOP, bounds=bnd)
                face_expr = (fe['w'], fe['h'], fe['x'], fe['y'])
                print(f"facecam: no clean cam frame, tracking the face ({r.get('summary', '')})")
        if r.get('mode') in ('cam', 'face'):
            bx = list(r['box'])
            if r['mode'] == 'face':  # no webcam frame: widen the face crop so it is not a blurry close-up
                cx, cy = bx[0] + bx[2] / 2, bx[1] + bx[3] / 2
                bw, bh = min(1.0, bx[2] * 2.6), min(1.0, bx[3] * 2.2)
                bx = [min(max(0.0, cx - bw / 2), 1 - bw), min(max(0.0, cy - bh / 2), 1 - bh), bw, bh]
            cam = ':'.join(f'{v:.4f}' for v in bx)
            side = 'left' if r['box'][0] + r['box'][2] / 2 < 0.5 else 'right'
            print(f"facecam: {r.get('mode')} box {cam} ({r.get('summary', '')})")
        else:
            print(f"facecam: no stable face found ({r.get('reason', '')}), using the blur layout")
            layout = 'blur'
    elif layout in ('react', 'facecam') and cam != 'auto':
        side = 'left' if float(cam.split(':')[0]) + float(cam.split(':')[2]) / 2 < 0.5 else 'right'
    cap_y = int(CAP_Y[layout] * H / 1920)
    title, band = None, None
    if a.title and layout == 'react':
        n = len(wrap(a.title, 26 if a.title_style == 'box' else 24))
        if a.title_style == 'box':
            bh = n * 78 + 44
            band = (TOP - bh // 2, bh, a.title_secs)
            title = ('box', a.title, TOP, a.title_secs)
        else:
            title = ('outline', a.title, TOP + 40, a.title_secs)
    ass = out / f"clip_{a.pick}.ass"
    caps = a.captions
    cap_words = words if caps != 'none' else []
    info = c.get("info", {})
    context = a.context.strip()
    if context.lower() == "auto":
        context = context_from_title(info.get("title") or "", info.get("channel") or info.get("uploader") or "")
    accent = hex_color(a.bg_color)
    if accent in ("#141018", "#f4f1ec"):  # black/white backgrounds: keep the brand pink as the accent
        accent = "#e8457f"
    ass.write_text(build_ass(cap_words, s0, e0, a.hook, cap_y, title=title, caps=caps, profanity=a.allow_profanity,
                             context=context, handle=a.outro_handle, accent=accent,
                             pill="#141018" if a.bg == "solid" else None), encoding="utf-8")  # dark pill on flat colour
    src = None; gx = None
    if layout == 'react':
        from common import ffprobe
        vs = [x for x in ffprobe(c['source'])['streams'] if x.get('codec_type') == 'video'][0]
        src = (int(vs['width']), int(vs['height']))
        gx = game_offset(c['source'], s0, e0, src, [float(t) for t in cam.split(':')])
    punch = None
    if a.punch > 0:
        peak = float(pick.get("peak", (s0 + e0) / 2)) - s0
        peak = min(max(peak, 0.5), max(0.5, e0 - s0 - 1.0))
        punch = (max(0.0, peak - 0.4), min(e0 - s0, peak + 1.8), min(a.punch, 0.4))
        print(f"punch-in at {peak:.1f}s (+{punch[2] * 100:.0f}%)")
    v = video_filter(layout, cam, ass, band=band, cam_side=side, src=src, game_x=gx, face_expr=face_expr,
                     punch=punch, fps=a.fps, bg=a.bg, bg_color=a.bg_color)
    af = ("highpass=f=80,afftdn=nr=12:nf=-30," if a.clean_audio else "") + "loudnorm=I=-14:TP=-1.5:LRA=11"
    mp4 = out / f"clip_{a.pick}.mp4"
    part = out / f"clip_{a.pick}.part.mp4"  # renamed to clip_N.mp4 only when the encode completes
    (out / f"clip_{a.pick}.json").unlink(missing_ok=True)  # stale settings must not vouch for a half-made clip
    stage(2, 2, f"Encoding clip {a.pick}")
    run_ffmpeg([tool("ffmpeg"), "-y", "-v", "error", "-ss", f"{s0:.2f}", "-to", f"{e0:.2f}", "-i", c["source"],
         "-filter_complex", v, "-map", "[vo]", "-map", "0:a?", "-af", af,
         "-c:v", "libx264", "-preset", "medium", "-crf", "20", "-pix_fmt", "yuv420p", "-c:a", "aac", "-b:a", "160k",
         "-ar", "48000", "-movflags", "+faststart", str(part)], e0 - s0)
    part.replace(mp4)
    if cap_words or a.hook:
        export_subs(caption_groups(cap_words, s0, e0, a.allow_profanity), s0, a.hook, out / f"clip_{a.pick}")
    save_json(out / f"clip_{a.pick}.json", {"file": str(mp4), "start": s0, "end": e0, "layout": layout,
                                            "punch": a.punch, "clean_audio": a.clean_audio, "fps": a.fps,
                                            "platform": a.platform, "width": W, "height": H,
                                            "bg": a.bg, "bg_color": hex_color(a.bg_color), "context": context,
                                            "outro_handle": a.outro_handle, "bg_color_name": a.bg_color,
                                            "context_on": bool(a.context.strip()), "hook": a.hook or a.title, "title": a.title, "cam": cam,
                                            "source_url": info.get("webpage_url"), "source_title": info.get("title"),
                                            "source_channel": info.get("channel") or info.get("uploader")})
    print(mp4)


if __name__ == "__main__":
    main()
