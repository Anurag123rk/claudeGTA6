"""Long-form guide studio: sets up a Claude Code project for automated, story-driven GTA 6 guides.

Vice Desk does not run this pipeline itself: it needs Claude Code plus your own ElevenLabs, Apify and YouTube API
accounts. create_project() lays out the folders, the status and rules files, a .env template for the keys and a
CLAUDE.md with the brief, so you open the folder in Claude Code and start the first run.
"""
import re
from pathlib import Path

DEFAULT_TOPICS = "map guides, mission walkthroughs, hidden locations, lore"
STAGES = {
    "research": "Niche study: outliers per duration band, first-minute shot lists, the component ranking.",
    "library": "Reusable components, each passed through the critic loop and tagged by the claim it shows.",
    "footage": "Official trailers and gameplay only, cut, graded and tagged (content, place, motion, text-safe areas).",
    "voice": "The locked voice, takes and word-timed transcripts.",
    "music": "Music beds with marked drops; effects levelled against the bed.",
    "build": "Specs, edit lists and renders. Fixes are edits to the list, never rebuilds.",
    "rounds": "Critic reports, judge rankings and costs per round.",
}

PROMPT = """<role>
you make long-form youtube guides for me in the gta 6 niche, from research to a finished render. you start from what already wins in the niche or from a concept of your own. you never grade your own work.
</role>

<brief>
- channel: {channel}. topics: {topics}
- claude code subagents for every ai step, elevenlabs for voice, music and transcripts, apify for downloads and x search, hyperframes and three.js for the build, ffmpeg for the master
- keys live in .env only. never read them, never write them anywhere
- i'm away. make the calls, show me early, keep going
</brief>

<setup>
- first run, check node, python, ffmpeg and hyperframes and install what's missing
- keep a status file (what ran, what's queued, what failed) and a rules file (every rule i've given you) in the project root so a fresh run resumes from them alone
- one folder per stage: research, library, footage, voice, music, build, rounds
</setup>

<study>
- search the niche by views, this year, per duration band. outlier score is a video's views divided by its channel's usual views. one video per channel
- take the top videos, one per channel, frame their first minute and transcribe their first twenty seconds. write down how they open, shot by shot
- list every on-screen component they use and rank the list by how many videos use each one. that list is what the library gets built from
</study>

<library>
- build it once, before any video. remake every component from the study through the critic loop until it passes, then tag it by the claim it shows, with inputs, a minimum read time and passed contrast and phone-size checks
- footage: apify pulls the official trailers and gameplay. cut, retime, grade and tag every shot with content, place, motion and where text can sit. nothing with logos, menus or artefacts gets in
- map moves as presets. one voice, auditioned once from five curated professional options and then locked. music beds with marked drops. effects levelled against the bed
- a facts file with a source on every line. you may only state what's in it
- every rule in the rules file as an automatic check that runs before any render
</library>

<topic>
- a topic is worth making when several unrelated channels have outliers on it
- or ideate your own: pull what players are talking about this week from x and pitch me three concepts with a reason each
- write three storylines as three different films. pick the one that is fully sourced and buildable from the library today. say why the others were dropped
- every fact tagged official, measured, in-game or unverified. only official and measured go on screen, with the source next to it
</topic>

<script_voice_music>
- one flowing paragraph that sounds spoken, hedged exactly as much as the source. no fragments and pauses
- voice first, then music, then picture. transcribe the take back to get exact word times. the last key word lands on the drop. cut on the beat grid
</script_voice_music>

<build>
- write a spec with exact values for every move, nothing vague
- the cold open gets the full critic loop. the chapters are footage-led with a map locator at the start of each and a component only for claims, comparisons and lists
- one agent per chapter, in parallel. each writes an edit list: clip, component, text, word. fixed code builds the project from the list. you never write html
- a beat with no matching component falls back to footage and voice and logs the gap. gaps get built properly between videos. fixes are edits to the list, never rebuilds
</build>

<critic_loop>
- three fresh critics per round: story, motion, tech. they see the render and the evidence, never the spec or the source
- a judge reads all three, checks their claims against the frames and ranks the fixes. a hard defect caps the score. pass means it holds its own next to the reference channels
- fix the top fault, re-render only what changed, new critics. show me by round two. my notes go into the rules file and outrank every critic
</critic_loop>

<publish>
- master to minus 14 lufs. title, description and chapters from the script. thumbnail from the payoff frame with at most three words
- upload through the youtube data api as unlisted and send me the link. i make it public
</publish>

<honesty>
no invented numbers, no invented geography, no third-party gameplay in the published cut, no creator names. if a fact can't be sourced it doesn't go on screen.
</honesty>

<first_run>
run the study and build the library first, then show me the component list and the gap log. then build the cold open of one guide, run the loop and show me the render, the critic reports and what it cost before touching the chapters.
</first_run>
"""

ENV_EXAMPLE = """# Copy to .env and fill in. Claude is told never to read or print these.
ELEVENLABS_API_KEY=
APIFY_TOKEN=
# YouTube Data API (upload as unlisted): OAuth client secret JSON downloaded from Google Cloud
YOUTUBE_CLIENT_SECRET_FILE=client_secret.json
"""

START = "Read CLAUDE.md, STATUS.md and RULES.md, then start the first run."


def slug(name):
    s = re.sub(r"[^a-z0-9]+", "-", (name or "").lower()).strip("-")
    return s[:40] or "my-channel"


def create_project(root, channel, topics=""):
    """Create (or refresh) a long-form project; never overwrites STATUS.md, RULES.md or .env."""
    channel = (channel or "").strip() or "My GTA 6 channel"
    topics = (topics or "").strip() or DEFAULT_TOPICS
    d = Path(root) / "longform" / slug(channel)
    d.mkdir(parents=True, exist_ok=True)
    prompt = PROMPT.format(channel=channel, topics=topics)
    (d / "CLAUDE.md").write_text(f"# {channel}: long-form GTA 6 guides\n\n{prompt}", encoding="utf-8")
    if not (d / "STATUS.md").exists():
        (d / "STATUS.md").write_text("# Status\n\n## Ran\n\n## Queued\n- first run: study, then library\n\n## Failed\n", encoding="utf-8")
    if not (d / "RULES.md").exists():
        (d / "RULES.md").write_text("# Rules (my notes outrank every critic)\n\n- keys live in .env only; never read or write them\n"
                                    "- only official and measured facts go on screen, with the source next to them\n"
                                    "- no third-party gameplay in the published cut, no creator names\n", encoding="utf-8")
    (d / ".env.example").write_text(ENV_EXAMPLE, encoding="utf-8")
    gi = d / ".gitignore"
    if not gi.exists():
        gi.write_text(".env\nfootage/raw/\n*.mp4\n*.wav\n", encoding="utf-8")
    for name, about in STAGES.items():
        (d / name).mkdir(exist_ok=True)
        readme = d / name / "README.md"
        if not readme.exists():
            readme.write_text(f"# {name}\n\n{about}\n", encoding="utf-8")
    return {"path": str(d), "prompt": prompt, "start": START, "channel": channel}
