## Vice Desk 2.0.6: Windows, macOS, Linux and Android

| Platform | Download | Install |
|---|---|---|
| **Windows 10/11** | `ViceDesk.exe` | Double-click. If SmartScreen warns: **More info → Run anyway** (unsigned). |
| **macOS 12+ (Apple silicon)** | `ViceDesk-2.0.6-mac-arm64.dmg` | Open the .dmg and drag **Vice Desk** to Applications. First launch: right-click → **Open** (unsigned). If macOS says it is damaged, run `xattr -cr "/Applications/Vice Desk.app"` once. |
| **Linux (x86-64)** | `ViceDesk-2.0.6-linux-x86_64` | `chmod +x ViceDesk-2.0.6-linux-x86_64 && ./ViceDesk-2.0.6-linux-x86_64`; it opens in your browser. |
| **Android 10+ (64-bit ARM phones)** | `ViceDesk-2.0.6.apk` | Open the file on your phone and allow **Install unknown apps** for your browser or file manager when asked. |

### New in 2.0.6
- **Context intro.** For the first 3 seconds, a pill under the hook says what the video is about. It's written from the video's title (emoji, hashtags and "| Episode 3" style tails removed, plus "via <channel>"), or you can type your own.
- **Animated end card with your @account.** For the last 2.5 seconds the frame dims, your @account pops in, an accent underline grows and "Follow for more" fades up. Captions stop before it starts. The clip options ask for your @account once and remember it everywhere.
- **Background colour palette.** For the blur layout, choose Blurred video, Tinted blur (blur with a colour wash) or Solid colour, with 8 swatches: Vice pink, Sunset, Gold, Mint, Ocean, Neon purple, Night and Snow. The colour also becomes the accent of the intro and end card.
- **Bundled Inter font.** Captions, hooks and cards now use Inter (SIL Open Font License) on every platform, so clips look the same everywhere and text renders even on phones with unusual system fonts.

### New in 2.0.5
- **Retry button.** Every failed or stopped task gets **↻ Retry**, which runs it again with the same settings and continues from where it stopped: a finished download is reused, a partial one resumes, the transcript and moments are kept, and clips already cut with the same settings are skipped. Clips are now written under a temporary name, so a stopped encode can never pass for a finished clip.

### Fixed in 2.0.4
- **Downloads keep going when you switch apps (Android).** While a task runs, Vice Desk shows a progress notification and keeps the CPU and Wi-Fi awake, so Android no longer freezes the download. The keep-alive is released when the last task finishes. Allow notifications when asked to see the progress; the work continues either way.
- **A cut-off download is never reused.** Videos download to a temporary file and only become `source.mp4` once they are complete and readable. A damaged leftover from an earlier run is detected and downloaded again, which fixes "Invalid data found when processing input". Network drops are retried up to 3 times and resume where they stopped, and audio extraction is crash-safe too.
- Reading video info is retried when the network is briefly unavailable ("Failed to resolve www.youtube.com").

### New in 2.0.3
- **Choose before you clip.** "Clip it" in Find videos opens an options sheet: number of clips, layout, platform, webcam position, captions, hook, punch-in and clean audio. It remembers your last choices, and "More options…" opens the full Pipeline form.
- **Crop for each platform.** Every clip form (Quick start, Pipeline, the options sheet and the per-moment Cut buttons) has a Platform choice:
  - TikTok, Reels and Shorts: 9:16, 1080×1920
  - YouTube and X: 16:9, 1920×1080
  - Instagram feed: 4:5, 1080×1350
  - Square: 1:1, 1080×1080

  The rule check expects the matching size.
- **Facecam and Reaction on Android.** These crashed with `No module named 'cv2'`, because the phone app can't detect the webcam automatically. Pick the webcam position (top left, top right, bottom left or bottom right) instead. On a phone it defaults to top right. If automatic detection isn't available, the clip falls back to blur instead of failing.
- Fixed: facecam clips came out 1080×1918 (2 px short) and failed the rule check.

### Fixed in 2.0.2 (Android)
- **ffmpeg "CANNOT LINK EXECUTABLE … too small to be an ELF executable".** ffmpeg's libraries were unpacked with their version links (`libavdevice.so.61 → libavdevice.so.61.3.100`) saved as tiny text files, and a few runtime libraries it needs (libc++_shared, libcrypto, libexpat) were missing. Both are fixed, and the build now refuses to publish an APK where ffmpeg can't find any of its 81 libraries.
- On Android, the "ffmpeg is missing" banner no longer suggests `apt`/`brew`; it shows the actual error.
- **Uninstall the previous Vice Desk before installing.** Each build is signed with a new key, so Android won't update over it.

### Fixed in 2.0.1 (Android)
- **"ffmpeg is not installed" when downloading.** The phone app shipped a generic Linux ffmpeg that cannot run inside an Android app. It now uses Android builds of ffmpeg, ffprobe and QuickJS (from youtubedl-android, the same binaries the Seal and YTDLnis apps use). This ffmpeg includes libass, so the hook box renders on phones too, using Android's system fonts.
- **Uninstall the old Vice Desk first.** This build is signed with a different key, so Android won't install it over 2.0.0. Your clips saved to the gallery stay.
- The app tests its tools at startup. If one can't run on your phone, the Setup card shows the exact error, and the pipeline stops before downloading instead of failing halfway.

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
- Captions: the speech engine (faster-whisper) has no Android build, so phone clips are cut **without captions**. Moments are still scored on loudness, YouTube "most replayed" and chat activity. Use a desktop app for captioned clips.
- Live recording is desktop-only for now.
- Keep the app open while a long video downloads or encodes. The screen stays on, but Android may pause apps in the background.
- Built for 64-bit ARM phones (almost every phone since 2019).

### From 1.x
- ffmpeg is built in. The first launch of the Windows app lets you pick a speech model (tiny/base/small/medium) and downloads it with a live speed readout.
- No login and no cloud backend. The live monitor shows progress, a log and download speed for every task.
- Emoji in video titles no longer crash the trend radar; invalid links and paths are rejected with a clear message.

You approve every post; nothing is uploaded automatically.
