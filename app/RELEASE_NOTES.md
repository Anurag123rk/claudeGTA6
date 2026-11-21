## Vice Desk 1.1.0: GTA 6 clip pipeline for Windows

**Download `ViceDesk.exe` below and double-click it.** No Python, no ffmpeg install, no login.

### What's new in 1.1.0
- **ffmpeg is built in.** Nothing extra to install.
- **First-launch model picker.** Choose your speech model (tiny / base / small / medium). It downloads once with live speed, progress and ETA, then the app carries on to the dashboard and works offline. Change or add models any time in Settings.
- **Fixed: Trend radar crash on Windows** (`UnicodeEncodeError: 'charmap' codec can't encode character`) when video titles contain emoji. Progress lines also arrive in real time now instead of in bursts.
- **Fixed: garbage in the URL box.** Pasted text that isn't a URL or an existing file is rejected with a clear message instead of failing mid-pipeline.

### Also in this app (since 1.0.0)
- No login and no cloud backend; the front page loads instantly.
- Live monitor for every task: step, stage, overall %, live log, download speed, ETA and a speed graph.
- One-click full pipeline: download → transcribe → score moments → cut 1080x1920 clips → rule check.
- Trend radar, live-stream finder, live recording with chat-spike clips, and a clip library with previews.

### First run
1. Windows SmartScreen may warn because the app is unsigned: click **More info → Run anyway**.
2. Pick a speech model (**small** is recommended) and wait for the download.
3. Paste a YouTube/Twitch VOD URL or a local video file and click **Run full pipeline**.

Clips, reports and jobs go to `Documents\ViceDesk`. Models are stored in `%LOCALAPPDATA%\ViceDesk\models`. You approve every post; nothing is uploaded.

Needs Windows 10/11 (64-bit) with the Edge WebView2 runtime, which ships with Windows 11 and current Windows 10. Without it, the app opens in your default browser instead.
