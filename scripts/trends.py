"""Trend radar: recent GTA 6 videos on YouTube ranked by views per hour.

Fast path: ONE request to the YouTube results page (sorted by upload date) gives title, views, approximate
upload time, duration and channel for every result. Then the top --deep videos (default 8) are opened in
parallel to read exact numbers and YouTube's "most replayed" heatmap. --deep 0 skips that step.

usage: python trends.py [--query "gta 6"] [--hours 24] [--limit 30] [--deep 8] [--out trends.md]
"""
import argparse, sys, time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from urllib.parse import quote_plus
sys.path.insert(0, str(Path(__file__).parent))
from common import progress, stage, ytdl_info, ytdl_search

UPLOAD_DATE_SORT = "&sp=CAI%253D"  # YouTube search sorted by upload date


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--query", default="gta 6"); ap.add_argument("--hours", type=float, default=24)
    ap.add_argument("--limit", type=int, default=30); ap.add_argument("--deep", type=int, default=8)
    ap.add_argument("--out", default="trends.md")
    a = ap.parse_args()
    t0 = time.time()
    stage(1, 2, "Searching YouTube")
    try:
        entries = ytdl_search(f"https://www.youtube.com/results?search_query={quote_plus(a.query)}{UPLOAD_DATE_SORT}", a.limit)
    except Exception as e:
        sys.exit(f"YouTube search failed: {str(e).replace('ERROR: ', '')[:300]}")
    print(f"search: {len(entries)} results in {time.time() - t0:.1f}s", flush=True)

    now = time.time(); rows = []; skipped = 0
    for e in entries:
        url = e.get("url") or ""
        if "/shorts/" in url or e.get("live_status") in ("is_live", "is_upcoming"):
            continue
        ts = e.get("timestamp")
        if not ts:
            skipped += 1
            continue
        age = max(0.25, (now - ts) / 3600)
        if age > a.hours:
            continue
        v = e.get("view_count") or 0
        rows.append({"vph": v / age, "views": v, "age": age, "dur": e.get("duration") or 0, "channel": e.get("channel") or "",
                     "title": e.get("title") or "", "url": url, "heat": None})
    rows.sort(key=lambda r: -r["vph"])

    deep = rows[: max(0, a.deep)]
    stage(2, 2, f"Checking 'most replayed' on the top {len(deep)}" if deep else "Done")
    if deep:
        with ThreadPoolExecutor(8) as ex:
            futs = {ex.submit(ytdl_info, r["url"]): r for r in deep}
            for k, f in enumerate(as_completed(futs), 1):
                r = futs[f]
                try:
                    i = f.result()
                    r["heat"] = bool(i.get("heatmap"))
                    t = i.get("timestamp") or i.get("release_timestamp")
                    if t:
                        r["age"] = max(0.25, (now - t) / 3600)
                    r["views"] = i.get("view_count") or r["views"]
                    r["vph"] = r["views"] / r["age"]
                except BaseException as ex_:  # one slow/blocked video must not sink the list
                    print(f"skip details for {r['url']}: {str(ex_)[:120]}", flush=True)
                progress(k, len(deep), "videos checked")
        rows.sort(key=lambda r: -r["vph"])

    md = [f"# Trend radar: \"{a.query}\", last {a.hours:.0f} h ({time.strftime('%Y-%m-%d %H:%M UTC', time.gmtime())})", "",
          "Ages from YouTube's \"x hours ago\" text are approximate; the top results are checked exactly.", "",
          "| # | views/h | views | age h | min | channel | title | most replayed |", "|---|---|---|---|---|---|---|---|"]
    for k, r in enumerate(rows, 1):
        heat = "" if r["heat"] is None else ("yes" if r["heat"] else "no")
        title = r["title"][:70].replace("|", "/").replace("[", "(").replace("]", ")")
        md.append(f"| {k} | {r['vph']:,.0f} | {r['views']:,} | {r['age']:.1f} | {r['dur'] / 60:.0f} | {r['channel'].replace('|', '/')} "
                  f"| [{title}]({r['url']}) | {heat} |")
    if not rows:
        md.append(f"\nNo videos from the last {a.hours:.0f} h in the first {len(entries)} results"
                  + (f" ({skipped} had no upload time)" if skipped else "") + ". Try more hours or another query.")
    Path(a.out).write_text("\n".join(md) + "\n", encoding="utf-8")
    print("\n".join(md[:16]))
    print(f"... {len(rows)} videos -> {a.out} in {time.time() - t0:.1f}s")


if __name__ == "__main__":
    main()
