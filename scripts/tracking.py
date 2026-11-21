"""Follow the action for smart vertical crops: no OpenCV, only ffmpeg + numpy (so it also runs on Android).

track_centers(video, s0, e0, aspect) samples the moment at 6 fps in low-res greyscale, measures where things move
(static HUD, counters and the webcam box do not move, so they are ignored), finds the crop window with the most
action in every frame, and smooths that into a calm camera path: averaged over ~1.5 s, pan speed limited, with a
gentle pull to the centre when nothing is happening. crop_x_expr() turns the path into an ffmpeg expression in t.
"""
import subprocess
import numpy as np

from common import tool

FPS = 6
SW, SH = 192, 108  # analysis frame (aspect distortion does not matter: only horizontal fractions are used)


def _frames(video, s0, e0):
    cmd = [tool("ffmpeg"), "-v", "error", "-ss", f"{s0:.2f}", "-to", f"{e0:.2f}", "-i", str(video),
           "-vf", f"fps={FPS},scale={SW}:{SH},format=gray", "-f", "rawvideo", "-"]
    raw = subprocess.run(cmd, capture_output=True).stdout
    n = len(raw) // (SW * SH)
    if n < 3:
        return None
    return np.frombuffer(raw[: n * SW * SH], dtype=np.uint8).reshape(n, SH, SW).astype(np.float32)


def _smooth(a, k):
    k = max(1, int(k))
    if k == 1 or len(a) < 2:
        return a
    pad = np.pad(a, (k // 2, k - 1 - k // 2), mode="edge")
    return np.convolve(pad, np.ones(k) / k, mode="valid")


def track_centers(video, s0, e0, win_frac, exclude=None, max_speed=0.22):
    """Horizontal centre of the action (0..1) per sample, or None if the clip cannot be analysed.

    win_frac: crop window width as a fraction of the source width (e.g. 9:16 of a 16:9 frame = 0.316).
    exclude:  (x, y, w, h) fractions to ignore, e.g. the webcam box.
    max_speed: largest pan per second, as a fraction of the frame width.
    """
    if win_frac >= 0.98:
        return None
    f = _frames(video, s0, e0)
    if f is None:
        return None
    diff = np.abs(f[1:] - f[:-1])
    diff[diff < 10] = 0  # compression noise
    if exclude:
        x, y, w, h = exclude
        diff[:, int(y * SH):int((y + h) * SH) + 1, int(x * SW):int((x + w) * SW) + 1] = 0
    col = diff.sum(axis=1)  # motion per column, per sample
    # temporal smoothing: the camera should react to sustained action, not single flashes
    k_t = int(FPS * 1.5)
    col = np.stack([_smooth(col[:, i], k_t) for i in range(SW)], axis=1)
    win = max(2, int(round(win_frac * SW)))
    kernel = np.ones(win)
    energy = np.stack([np.convolve(row, kernel, mode="valid") for row in col])  # (n, SW - win + 1)
    centers = (np.arange(energy.shape[1]) + win / 2) / SW
    prior = 1 - np.abs(centers - 0.5) * 1.6  # prefer the middle when the action is spread out
    energy = energy + prior[None, :] * (energy.mean(axis=1, keepdims=True) * 0.35 + 1e-6)
    path = centers[np.argmax(energy, axis=1)]
    path = _smooth(path, FPS)  # ~1 s
    # limit pan speed for a steady, filmed look
    step = max_speed / FPS
    out = [path[0]]
    for c in path[1:]:
        out.append(out[-1] + float(np.clip(c - out[-1], -step, step)))
    half = win_frac / 2
    out = np.clip(np.array(out), half, 1 - half)
    return [(i / FPS, float(c)) for i, c in enumerate(out)]


def crop_x_expr(path, every=0.5):
    """ffmpeg expression for the crop's x (in pixels) following path [(t, centre_frac)], linear between keyframes."""
    if not path:
        return "(iw-ow)/2"
    keys, last = [], -1e9
    for t, c in path:
        if t - last >= every:
            keys.append((t, c)); last = t
    if keys[-1] != path[-1]:
        keys.append(path[-1])
    keys = keys[:90]
    expr = f"{keys[-1][1]:.4f}"
    for (t0, c0), (t1, c1) in reversed(list(zip(keys, keys[1:]))):
        expr = f"if(lt(t,{t1:.2f}),{c0:.4f}+({c1 - c0:.4f})*(t-{t0:.2f})/{max(t1 - t0, 0.01):.2f},{expr})"
    expr = f"if(lt(t,{keys[0][0]:.2f}),{keys[0][1]:.4f},{expr})"
    return f"max(0,min(iw-ow,({expr})*iw-ow/2))"
