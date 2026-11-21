## Vice Desk 2.0.0: Windows app + Android app

| Platform | Download | Install |
|---|---|---|
| **Windows 10/11** | `ViceDesk.exe` | Double-click. If SmartScreen warns: **More info → Run anyway** (unsigned). |
| **macOS 12+ (Apple silicon)** | `ViceDesk-2.0.0-mac-arm64.dmg` | Open the .dmg and drag **Vice Desk** to Applications. First launch: right-click → **Open** (unsigned). If macOS says it is damaged, run `xattr -cr "/Applications/Vice Desk.app"` once. |
| **Linux (x86-64)** | `ViceDesk-2.0.0-linux-x86_64` | `chmod +x ViceDesk-2.0.0-linux-x86_64 && ./ViceDesk-2.0.0-linux-x86_64`; it opens in your browser. |
| **Android 10+ (64-bit ARM phones)** | `ViceDesk-2.0.0.apk` | Open the file on your phone and allow **Install unknown apps** for your browser or file manager when asked. |

### New in 2.0.0
- **Clip studio steps** ("VOD → find the reaction → cut → punch in → caption → ship"):
  - **Punch-in:** an automatic zoom on the peak moment of each clip (on by default).
  - **Clean audio:** reduces mic and background noise with ffmpeg's denoiser, before loudness normalisation.
  - **Smooth 60 fps:** motion-interpolated output, optional and slow.
  - **Editable subtitles:** every clip gets `clip_N.srt` and `clip_N.ass` next to it, so you can fine-tune the edit in Kdenlive, Shotcut or OpenCut.
- **Desktop apps for macOS and Linux**, alongside Windows, with ffmpeg and the YouTube JS runtime built in.
- **Android app.** The same clip pipeline runs on your phone: find trending videos, paste or share a link (Share → Vice Desk from the YouTube or Twitch app), download with live speed, find the best moments, cut 1080x1920 clips and rule-check them. Then **Share** a clip straight to TikTok, Instagram or YouTube, or **Save** it to your gallery (Movies/ViceDesk). You can also pick a video already on your phone.
- **Video search is much faster and works again.** Trend radar used to start a separate download process for every one of the 30 results. Now it reads the whole YouTube results page in **one request**, then checks "most replayed" for only the top 8, in parallel (untick the box to skip even that). The live-stream finder also uses one request.
- **YouTube downloads are reliable again.** YouTube now requires a JavaScript runtime. The Windows app bundles Deno and the Android app bundles QuickJS, so you don't need to install anything.
- Downloads run inside the app instead of as separate processes: faster start, same live speed/ETA readout.

### Android notes
- Captions: the speech engine (faster-whisper) has no Android build, so phone clips are cut **without captions**. Moments are still scored on loudness, YouTube "most replayed" and chat activity. Use the Windows app for captioned clips.
- Live recording is Windows-only for now.
- Keep the app open while a long video downloads or encodes. The screen stays on, but Android may pause apps in the background.
- Built for 64-bit ARM phones (almost every phone since 2019).

### From 1.x
- ffmpeg is built in. The first launch of the Windows app lets you pick a speech model (tiny/base/small/medium) and downloads it with a live speed readout.
- No login and no cloud backend. The live monitor shows progress, a log and download speed for every task.
- Emoji in video titles no longer crash the trend radar; invalid links and paths are rejected with a clear message.

You approve every post; nothing is uploaded automatically.
