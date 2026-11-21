## Vice Desk: GTA 6 clip pipeline for Windows

**Download `ViceDesk.exe` below and double-click it.** No Python, no install, no login.

### What's new
- **One-file Windows app (GUI).** Replaces the old web control room and its "download as zip" archive.
- **No login.** The Internet Identity sign-in and the cloud backend are gone. Everything runs on your PC.
- **Front page loads instantly.** The dashboard no longer waits on a remote backend, so it can't hang on loading.
- **Live monitor.** Every task shows step, stage and overall %, with the live log beside it.
- **Download speed.** Live MB/s, downloaded/total, ETA and a speed graph for video downloads, the speech-model download and the ffmpeg installer, plus a network meter in the sidebar.
- **Pipeline fixes**
  - Downloads report progress instead of running silently.
  - A failed speech-model download no longer kills the run: moments are scored on loudness, "most replayed" and chat, and clips are cut without captions.
  - `cut.py` no longer crashes when a job has no transcript, and gives a clear error for an unknown pick number.
  - Live recordings stop cleanly from the GUI and still cut pending spikes.
  - Encoding shows real progress.
  - The full pipeline skips one bad moment (e.g. no facecam) instead of failing the batch.

### First run
1. Windows SmartScreen may warn because the app is unsigned: click **More info → Run anyway**.
2. On the dashboard, click **Install ffmpeg** (one time, ~100 MB, with a live speed readout).
3. Paste a YouTube/Twitch VOD URL or a local video file and click **Run full pipeline**.

The first transcription downloads the speech model (~460 MB for "small", configurable in Settings).
Clips, reports and jobs go to `Documents\ViceDesk`. You approve every post; nothing is uploaded.

Needs Windows 10/11 (64-bit) with the Edge WebView2 runtime, which ships with Windows 11 and current Windows 10. Without it, the app opens in your default browser instead.
