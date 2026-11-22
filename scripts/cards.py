"""Intro (context) and outro (@account) cards for clips, drawn with libass so they render the same everywhere.

Themes:
  vice  - GTA VI / Vice City look: sunset pink-orange stripes, slanted heavy type with a neon glow, wanted-level stars
  clean - minimal pill and underline
Colours in ASS are &HBBGGRR& for override tags.
"""
import math

PINK, ORANGE, GOLD = "#ff3d8b", "#ff8a3d", "#ffc83d"


def _tag(hexc):
    h = hexc.lstrip("#")
    return f"&H{h[4:6]}{h[2:4]}{h[0:2]}&".upper()


def _ts(t):
    t = max(0.0, t); h = int(t // 3600); m = int(t % 3600 // 60); s = t % 60
    return f"{h}:{m:02d}:{s:05.2f}"


def _esc(s):
    return s.replace("\\", "").replace("{", "(").replace("}", ")").replace("\n", " ")


def _star(r_out, r_in):
    """ASS drawing of a 5-point star with its top-left at (0, 0)."""
    pts = []
    for k in range(10):
        r = r_out if k % 2 == 0 else r_in
        a = -math.pi / 2 + k * math.pi / 5
        pts.append((r_out + r * math.cos(a), r_out + r * math.sin(a)))
    p = [f"{x:.0f} {y:.0f}" for x, y in pts]
    return "m " + p[0] + " l " + " ".join(p[1:])


STYLES = """Style: Ctx,Inter,46,&H00FFFFFF,&H00FFFFFF,&H00E8457F,&H40140B18,-1,0,0,0,100,100,1,0,3,14,0,8,60,60,0,1
Style: Handle,Inter Black,104,&H00FFFFFF,&H00FFFFFF,&H00000000,&H80000000,-1,0,0,0,100,100,0,0,1,6,4,5,40,40,0,1
Style: OutroSub,Inter,50,&H00FFFFFF,&H00FFFFFF,&H00000000,&H80000000,0,0,0,0,100,100,2,0,1,3,2,5,40,40,0,1
Style: Fx,Inter,20,&H00FFFFFF,&H00FFFFFF,&H00000000,&H00000000,0,0,0,0,100,100,0,0,1,0,0,7,0,0,0,1
Style: ViceTag,Inter Black,34,&H008B3DFF,&H008B3DFF,&H00140B18,&H00000000,-1,0,0,0,100,100,9,0,1,3,0,7,0,0,0,1
Style: ViceMain,Inter Black,62,&H00FFFFFF,&H00FFFFFF,&H008B3DFF,&H003D8AFF,-1,0,0,0,100,100,1,0,1,4,5,7,70,70,0,1
Style: ViceHandle,Inter Black,118,&H00FFFFFF,&H00FFFFFF,&H008B3DFF,&H003D8AFF,-1,0,0,0,100,100,2,0,1,5,7,5,40,40,0,1
Style: ViceSub,Inter Black,40,&H00FFFFFF,&H00FFFFFF,&H00000000,&H80000000,-1,0,0,0,100,100,8,0,1,2,2,5,40,40,0,1
"""


def events(theme, W, H, dur, context, handle, accent, has_hook, pill=None):
    """Dialogue lines for the intro context card (first ~3.4 s) and the @account end card (last 2.5 s)."""
    if theme == "clean":
        return _clean(W, H, dur, context, handle, accent, has_hook, pill)
    return _vice(W, H, dur, context, handle, has_hook)


def _clean(W, H, dur, context, handle, accent, has_hook, pill):
    ev = []
    acc, pill_c = _tag(accent), _tag(pill or accent)
    if context:
        y = int(H * (0.25 if has_hook else 0.18))
        end = min(3.4, max(1.5, dur - 0.5))
        ev.append(f"Dialogue: 3,{_ts(0.15)},{_ts(end)},Ctx,,0,0,0,,{{\\an8\\move({W // 2},{y - 40},{W // 2},{y},0,260)"
                  f"\\fad(220,260)\\3c{pill_c}}}{_esc(context)}")
    if handle and dur >= 5:
        h = handle if handle.startswith("@") else "@" + handle
        t0, cy = max(0.0, dur - 2.5), H // 2
        bar_w = min(int(W * 0.62), 60 + 44 * len(h))
        ev += [
            f"Dialogue: 4,{_ts(t0)},{_ts(dur)},Fx,,0,0,0,,{{\\an7\\pos(0,0)\\p1\\1c&H000000&\\1a&HFF&\\t(0,350,\\1a&H50&)\\bord0\\shad0}}"
            f"m 0 0 l {W} 0 {W} {H} 0 {H}{{\\p0}}",
            f"Dialogue: 5,{_ts(t0 + 0.12)},{_ts(dur)},Handle,,0,0,0,,{{\\an5\\pos({W // 2},{cy})\\fad(150,0)"
            f"\\fscx55\\fscy55\\t(0,260,\\fscx108\\fscy108)\\t(260,420,\\fscx100\\fscy100)}}{_esc(h)}",
            f"Dialogue: 5,{_ts(t0 + 0.35)},{_ts(dur)},Fx,,0,0,0,,{{\\an5\\pos({W // 2},{cy + 78})\\p1\\1c{acc}\\bord0\\shad0"
            f"\\fscx0\\t(0,380,\\fscx100)}}m 0 0 l {bar_w} 0 {bar_w} 12 0 12{{\\p0}}",
            f"Dialogue: 5,{_ts(t0 + 0.6)},{_ts(dur)},OutroSub,,0,0,0,,{{\\an5\\move({W // 2},{cy + 150},{W // 2},{cy + 132},0,300)"
            f"\\alpha&HFF&\\t(0,300,\\alpha&H00&)}}Follow for more",
        ]
    return ev


def _vice(W, H, dur, context, handle, has_hook):
    ev = []
    pink, orange, gold = _tag(PINK), _tag(ORANGE), _tag(GOLD)
    if context:
        # lower than before: just above the video in the 9:16 layouts, under the hook
        y = int(H * (0.265 if has_hook else 0.2))
        x = int(W * 0.075)
        end = min(3.6, max(1.6, dur - 0.5))
        stripe_w = int(W * 0.16)
        ev += [
            # sunset double stripe wipes in
            f"Dialogue: 3,{_ts(0.1)},{_ts(end)},Fx,,0,0,0,,{{\\an7\\pos({x},{y + 6})\\p1\\1c{pink}\\bord0\\shad0\\fscx0"
            f"\\t(0,240,\\fscx100)\\fad(0,260)}}m 0 0 l {stripe_w} 0 {stripe_w - 10} 10 -10 10{{\\p0}}",
            f"Dialogue: 3,{_ts(0.16)},{_ts(end)},Fx,,0,0,0,,{{\\an7\\pos({x},{y + 22})\\p1\\1c{orange}\\bord0\\shad0\\fscx0"
            f"\\t(0,260,\\fscx100)\\fad(0,260)}}m 0 0 l {int(stripe_w * 0.7)} 0 {int(stripe_w * 0.7) - 10} 10 -10 10{{\\p0}}",
            # tag line + slanted title sliding in from the left with a neon glow
            f"Dialogue: 4,{_ts(0.2)},{_ts(end)},ViceTag,,0,0,0,,{{\\an7\\move({x - 60},{y + 44},{x},{y + 44},0,260)"
            f"\\fad(160,260)}}GTA VI  ·  WHAT YOU'RE WATCHING",
            f"Dialogue: 4,{_ts(0.28)},{_ts(end)},ViceMain,,0,0,0,,{{\\an7\\move({x - 90},{y + 90},{x},{y + 90},0,300)"
            f"\\fax-0.12\\blur1.2\\fad(180,260)}}{_esc(context).upper()}",
        ]
    if handle and dur >= 5:
        h = handle if handle.startswith("@") else "@" + handle
        t0, cy = max(0.0, dur - 2.5), H // 2
        band = int(H * 0.06)
        ev += [
            # dim the frame
            f"Dialogue: 4,{_ts(t0)},{_ts(dur)},Fx,,0,0,0,,{{\\an7\\pos(0,0)\\p1\\1c&H180A14&\\1a&HFF&\\t(0,320,\\1a&H48&)\\bord0\\shad0}}"
            f"m 0 0 l {W} 0 {W} {H} 0 {H}{{\\p0}}",
            # sunset stripes sweep across behind the handle (slanted parallelograms)
            f"Dialogue: 5,{_ts(t0 + 0.05)},{_ts(dur)},Fx,,0,0,0,,{{\\an7\\move({-W},{cy - band - 20},0,{cy - band - 20},0,320)"
            f"\\p1\\1c{pink}\\1a&H30&\\bord0\\shad0}}m 0 0 l {W} 0 {W - 40} {band} -40 {band}{{\\p0}}",
            f"Dialogue: 5,{_ts(t0 + 0.12)},{_ts(dur)},Fx,,0,0,0,,{{\\an7\\move({W},{cy + 24},0,{cy + 24},0,340)"
            f"\\p1\\1c{orange}\\1a&H40&\\bord0\\shad0}}m 40 0 l {W + 40} 0 {W} {band // 2} 0 {band // 2}{{\\p0}}",
            # @handle slams in, slanted, neon glow, overshoot then settle
            f"Dialogue: 6,{_ts(t0 + 0.22)},{_ts(dur)},ViceHandle,,0,0,0,,{{\\an5\\pos({W // 2},{cy - 10})\\fax-0.12\\fad(120,0)"
            f"\\fscx140\\fscy140\\t(0,200,\\fscx96\\fscy96)\\t(200,320,\\fscx100\\fscy100)\\blur1}}{_esc(h)}",
            f"Dialogue: 6,{_ts(t0 + 0.75)},{_ts(dur)},ViceSub,,0,0,0,,{{\\an5\\pos({W // 2},{cy + 175})\\alpha&HFF&"
            f"\\t(0,260,\\alpha&H00&)}}FOLLOW FOR MORE GTA VI",
        ]
        # five wanted-level stars light up one after another
        r = 34
        star = _star(r, r * 0.45)
        gap = 2 * r + 16
        x0 = W // 2 - 2 * gap - r
        for k in range(5):
            st = t0 + 0.45 + k * 0.09
            ev.append(f"Dialogue: 6,{_ts(st)},{_ts(dur)},Fx,,0,0,0,,{{\\an7\\pos({x0 + k * gap},{cy + 82})\\p1\\1c{gold}"
                      f"\\3c&H000000&\\bord3\\shad0\\fscx40\\fscy40\\t(0,140,\\fscx115\\fscy115)\\t(140,220,\\fscx100\\fscy100)}}"
                      f"{star}{{\\p0}}")
    return ev
