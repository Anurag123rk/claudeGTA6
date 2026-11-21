## Vice Desk 2.2.7: Windows, macOS, Linux and Android

| Platform | Download | Install |
|---|---|---|
| **Windows 10/11** | `ViceDesk.exe` | Double-click. If SmartScreen warns: **More info → Run anyway** (unsigned). |
| **macOS 12+ (Apple silicon)** | `ViceDesk-2.2.7-mac-arm64.dmg` | Open the .dmg and drag **Vice Desk** to Applications. First launch: right-click → **Open** (unsigned). If macOS says it is damaged, run `xattr -cr "/Applications/Vice Desk.app"` once. |
| **Linux (x86-64)** | `ViceDesk-2.2.7-linux-x86_64` | `chmod +x ViceDesk-2.2.7-linux-x86_64 && ./ViceDesk-2.2.7-linux-x86_64`; it opens in your browser. |
| **Android 10+ (64-bit ARM phones)** | `ViceDesk-2.2.7.apk` | Open the file on your phone and allow **Install unknown apps** for your browser or file manager when asked. |

### Fixed in 2.2.7
- **Long-form footage got stuck on "official video 2 of 2"** with the bar refilling over and over. The search picked up Rockstar's *channel* link as a video and started downloading the whole channel. Only real video links are used now, channel/playlist links you paste are skipped with a note, and a download never pulls more than one video.
- **No voice-over on Android** ("No audio was received"). When the Microsoft voice fails, it now tries a second Microsoft voice and then really falls back to the phone's built-in voice (the 2.2.6 fallback didn't recognise it was on Android).

### Fixed in 2.2.6
- **Android long-form had no voice-over** ("free voice unavailable here (No module named 'edge_tts')"). The free Microsoft voice is now included in the Android app.
- **New: the phone's own voice.** If the Microsoft voice can't be reached, Android uses the phone's built-in text-to-speech instead: offline, free, no key. You can also pick **Phone's built-in voice** directly under Voice. For a nicer voice, install or update *Speech Recognition & Synthesis by Google* and choose a voice in Android Settings → Text-to-speech.

### Fixed in 2.2.5
- **Long-form "Official footage" looked stuck** (e.g. "475.4 KB of 475.4 KB (file 3)"). YouTube sends video in many small pieces; progress now shows "piece 12 of 180" and the file counter only moves on when a whole file is finished.
- Long-form now downloads only as much official footage as the narration needs (a few minutes per video, not whole trailers), so this step is much faster on phones. The log shows "official video 1 of 2 … done: 84 MB" as each one finishes.
- A half-downloaded footage file from an interrupted run is thrown away and fetched again instead of breaking the build.
- The final "Title, description, thumbnail" step no longer fails trying to take the thumbnail from a web link; it uses the downloaded footage.

### Fixed in 2.2.4
- **YouTube "HTTP Error 403: Forbidden" during downloads** (seen in long-form footage on phones). When YouTube refuses one way of downloading, Vice Desk now tries other player routes (TV/Safari, Android VR, mobile web) before giving up, and cleans up the half-downloaded pieces. This applies to clip and long-form downloads alike.
- Long-form footage now downloads at the same phone-friendly quality as clips (720p on phones), which is lighter and less often refused.
- If YouTube refuses every route, the error says so plainly and offers **Fix: sign in to YouTube**; it isn't retried pointlessly.

### Fixed in 2.2.3
- **Long-form: "could not parse the model's JSON reply" with OpenRouter, Qwen and other reasoning models.** These models write their thinking first (`<think>…</think>`) and sometimes produce slightly broken JSON (trailing commas, curly quotes, comments). Vice Desk now removes the thinking, finds the real answer among any examples, and repairs common mistakes. If it still can't read the reply, it asks the model once to reformat its own answer. Retry resumes from the failed stage.

### Fixed in 2.2.2
- **New clips showed the previous output.** Re-cut clips keep their file name, and the app's web view kept showing the cached older video. Clip previews and the player now always load the newest file.
- **Clearer clip names.** A finished pipeline lists **Clip 1, Clip 2…** in order. The library shows each clip's moment, time range and creation time, newest first, with a **new** badge on fresh clips.
- The log no longer fills with "ResourceWarning: unclosed file" after encoding.

### Fixed in 2.2.1 (Android)
- **"Requested format is not available" on YouTube videos.** The phone app was missing yt-dlp's YouTube challenge solver (yt-dlp-ejs). Without it, YouTube hides every downloadable format. It's included now, and the build refuses to publish an APK without it.
- The Setup card shows **YouTube challenge solver: ready**, so a missing solver is visible straight away.
- This error is no longer retried pointlessly; it explains what to check instead (solver, sign-in, region lock).

### New in 2.2.0
- **Pick your AI for long-form guides: Claude, ChatGPT, Gemini, OpenRouter, or a local model** (any OpenAI-compatible server, such as Ollama on your PC). Open **Long-form → AI model**, choose a provider, then:
  1. Tap **Get API key** to sign in to that provider and create a key.
  2. Paste the key, tap **Load models**, pick a model and tap **Test**.

  Keys stay on your device and are only sent to that provider. ChatGPT Plus and Claude Pro subscriptions can't be used by other apps; these providers only allow API keys, which are billed per use.
- **Make a long-form guide right in the app, on phone or PC.** With your chosen model, Vice Desk:
  1. finds the outliers in the niche (views ÷ the channel's usual views, one video per channel)
  2. picks the strongest concept, or invents its own
  3. writes a chaptered script with every claim tagged official, measured, in-game or unverified (only official or measured claims are stated as fact)
  4. runs three blind critics (story, honesty, pacing) and a judge, then revises
  5. voices it (ElevenLabs with your key, otherwise a free voice on desktop)
  6. builds a 1080p rough cut from official footage only (your URLs or Rockstar Games' own trailers), with GTA VI chapter cards and captions, mastered to −14 LUFS
  7. writes the title, a description with chapter timestamps and sources, and a thumbnail

  Every stage is saved, so **Retry** continues without paying for finished AI steps again. For the full studio (component library, multi-round critics, YouTube upload), the Claude Code project is still on the same page.
- Claude defaults to Claude Opus 5.5. A request Claude's safety filter declines is retried automatically on Anthropic's recommended fallback model.

### New in 2.1.0
- **Fix for "Sign in to confirm you're not a bot".** YouTube blocks anonymous downloads from many connections, mobile data especially. The fix is a signed-in session's cookies. Open **Settings → YouTube sign-in**:
  - **Phone:** tap **Sign in to YouTube**, sign in (a spare Google account is safest), then tap **Save**. The cookies stay on the phone.
  - **Desktop:** pick your browser (Firefox is most reliable), or paste a cookies.txt.

  Then press **Retry** on the failed task; the error itself now has a **Fix** button that takes you there. Bot checks are no longer retried, so the app doesn't hammer YouTube.
- **Crop · follows the action** (the new default layout): a true 9:16 crop (no blur bars) that tracks where the action is. Static HUD and overlays are ignored, and the pan is smoothed and speed-limited. Pick a webcam position and the webcam goes on top with tracked gameplay below; Facecam clips track too. The punch-in zooms on the tracked action.
- **GTA VI card style** (default; "Clean" is still available):
  - **Context card:** moved lower. A sunset stripe and "GTA VI · WHAT YOU'RE WATCHING" tag, then the title in slanted heavy type with a neon glow, sliding in.
  - **End card:** pink and orange stripes sweep in, your @account slams in with a glow, five wanted-level stars light up one by one, then "FOLLOW FOR MORE GTA VI".
- **Choose your mode at start:** Short clips, or **Long-form guides**. Long-form sets up a Claude Code project for story-driven GTA 6 guides: research → fact-checked script → ElevenLabs voice → official footage via Apify → spec-built edit → blind critic loop → unlisted YouTube upload. You get the stage folders, status and rules files, an .env template for your keys, and the full brief as CLAUDE.md with a Copy button. It runs in Claude Code on a computer, with your own ElevenLabs, Apify and YouTube accounts.
- **Android:** the app no longer slides under the status bar, notch or camera cutout, or the keyboard, on any phone.
- **Fixed:** finding moments crashed on videos shorter than 30 seconds.

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
