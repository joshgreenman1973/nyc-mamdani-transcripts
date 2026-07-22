#!/usr/bin/env python3
"""Scrape the NYC Mayor's Office YouTube channel.

Two-track approach:

1. For videos that correspond to an event already in the nyc.gov corpus
   (matched by similar title + close date), attach a `youtube_url` field to
   that existing item — we get the cleaner human-typed transcript from
   nyc.gov and a "Watch on YouTube" link from here. We do NOT pull captions
   for these.

2. For videos with no nyc.gov twin (produced shorts, social-media clips,
   "Cardi B and the Mayor", etc.), fetch the auto-generated captions and add
   them as new corpus items with `type: "video"`.

Run: python3 scrape_youtube.py
Input/Output: data/corpus.json (modified in place)
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import time
from html import unescape
from pathlib import Path

ROOT = Path(__file__).parent
CORPUS = ROOT / "data" / "corpus.json"
CHANNEL_BASE = "https://www.youtube.com/@NYCMayorsOffice"
# YouTube splits a channel across tabs and /videos holds none of the others.
# Livestreams are where the press conferences land, so omitting /streams was
# hiding the majority of the channel.
CHANNEL_TABS = ("videos", "streams", "shorts")
# The channel's Atom feed: the 15 most recent uploads with their publish dates.
# Plain XML, no bot-gating, and it works from datacenter IPs where yt-dlp's
# metadata fetch gets blocked — so this is what keeps the daily run honest.
CHANNEL_ID = "UClnI1zhyzv_BPb-VSHEtniw"
CHANNEL_FEED = f"https://www.youtube.com/feeds/videos.xml?channel_id={CHANNEL_ID}"
FROM_DATE = "20260101"  # YYYYMMDD format used by yt-dlp
DATE_PROXIMITY_DAYS = 3
JACCARD_THRESHOLD = 0.45
SLEEP_BETWEEN = 0.4
# How long to wait before retrying once when YouTube throttles caption fetches.
BLOCKED_BACKOFF = 30

STOPWORDS = {
    "a", "an", "and", "as", "at", "be", "by", "for", "from", "in", "is",
    "it", "of", "on", "or", "the", "to", "with", "transcript", "icymi",
    "watch", "remarks", "as", "prepared", "delivered", "mayor", "mamdani",
    "zohran", "kwame", "today", "new", "york", "city", "nyc",
}


def fetch_feed_videos() -> list[dict]:
    """Recent uploads from the channel's Atom feed.

    yt-dlp's per-video metadata fetch is blocked from datacenter IPs (it works
    locally and fails on CI), which is how three months of video went missing.
    This feed is served as plain XML to anyone, so it's the backstop that keeps
    new uploads flowing even when the richer fetch is unavailable. It only
    carries the latest 15 — enough for a daily run, not for a backfill.
    """
    import urllib.request

    try:
        req = urllib.request.Request(CHANNEL_FEED, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=60) as resp:
            xml = resp.read().decode("utf-8", "replace")
    except Exception as e:
        print(f"  channel feed fetch failed: {e}", file=sys.stderr)
        return []
    rows: list[dict] = []
    for entry in re.findall(r"<entry>(.*?)</entry>", xml, re.S):
        vid = re.search(r"<yt:videoId>(.*?)</yt:videoId>", entry)
        title = re.search(r"<title>(.*?)</title>", entry, re.S)
        pub = re.search(r"<published>(\d{4})-(\d{2})-(\d{2})", entry)
        if not (vid and title and pub):
            continue
        upload_date = pub.group(1) + pub.group(2) + pub.group(3)
        if upload_date < FROM_DATE:
            continue
        rows.append({
            "id": vid.group(1),
            "title": unescape(title.group(1)).replace("\n", " ").strip(),
            "upload_date": upload_date,
            "duration": 0,  # not in the feed; cosmetic only
        })
    return rows


def list_videos() -> list[dict]:
    """Return [{id, title, upload_date(YYYYMMDD), duration}] from the channel.

    Uses two passes: flat-playlist to get IDs cheaply (no rate-limit risk),
    then per-video metadata fetch to get upload_date and duration. The flat
    listing alone returns NA for upload_date — only the per-video page does.
    """
    print(f"Listing channel video IDs…", file=sys.stderr)
    candidates: list[tuple[str, str]] = []  # (id, title)
    seen_ids: set[str] = set()
    tabs_ok = 0
    for tab in CHANNEL_TABS:
        flat_cmd = [
            sys.executable, "-m", "yt_dlp",
            "--flat-playlist",
            "--print", "%(id)s|%(title)s",
            f"{CHANNEL_BASE}/{tab}",
        ]
        try:
            flat_out = subprocess.check_output(flat_cmd, stderr=subprocess.DEVNULL,
                                               text=True, timeout=300)
        except (subprocess.CalledProcessError, subprocess.TimeoutExpired) as e:
            # An empty or missing tab is normal; a broken one shouldn't cost us
            # the tabs that did work.
            print(f"  /{tab} listing failed: {e}", file=sys.stderr)
            continue
        tabs_ok += 1
        n_before = len(candidates)
        for line in flat_out.splitlines():
            if "|" not in line:
                continue
            vid, title = line.split("|", 1)
            if vid and vid not in seen_ids:
                seen_ids.add(vid)
                candidates.append((vid, title))
        print(f"  /{tab}: {len(candidates) - n_before} new", file=sys.stderr)
    if not tabs_ok:
        print("Every channel tab listing failed.", file=sys.stderr)
        return []
    print(f"  channel has {len(candidates)} videos; fetching metadata…", file=sys.stderr)

    # yt-dlp's per-video metadata fetch is blocked from datacenter IPs, where it
    # doesn't just error — it hangs on every URL until the timeout, then raises
    # and takes the whole run down BEFORE the feed fallback below can run. On CI
    # we therefore skip it entirely and rely on the Atom feed (recent uploads,
    # correctly dated, un-gated). The full-channel backfill runs locally, from a
    # residential IP, where yt-dlp works.
    on_ci = os.environ.get("GITHUB_ACTIONS") == "true"
    out = ""
    if on_ci:
        print("  CI environment: skipping IP-blocked yt-dlp metadata fetch; "
              "using the channel feed for recent uploads.", file=sys.stderr)
    else:
        cmd = [
            sys.executable, "-m", "yt_dlp",
            "--no-download", "--no-warnings",
            # YouTube rejects yt-dlp's default player-client rotation, which made
            # every video error out. Name the clients explicitly.
            "--extractor-args", "youtube:player_client=web,android",
            # One unplayable video must not sink the whole batch: keep going and
            # use whatever lines did print (yt-dlp still exits non-zero).
            "--ignore-errors",
            "--dateafter", FROM_DATE,
            "--print", "%(upload_date)s|%(id)s|%(duration)s|%(title)s",
        ] + [f"https://www.youtube.com/watch?v={vid}" for vid, _ in candidates]
        try:
            proc = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                  text=True, timeout=600)
            out = proc.stdout or ""
            if proc.returncode != 0:
                print(f"  yt-dlp exited {proc.returncode}; using the {len(out.splitlines())} "
                      f"lines it did return.", file=sys.stderr)
                # Keep the reason visible. This was swallowed by DEVNULL, which
                # is why a blocked run looked identical to a healthy one.
                for line in (proc.stderr or "").splitlines()[:5]:
                    print(f"    yt-dlp: {line[:200]}", file=sys.stderr)
        except subprocess.TimeoutExpired:
            # Non-fatal: fall through to the feed rather than crash the run.
            print("  yt-dlp metadata fetch timed out; falling back to the "
                  "channel feed.", file=sys.stderr)
    rows: list[dict] = []
    for line in out.splitlines():
        if line.count("|") < 3:
            continue
        upload_date, vid, duration, title = line.split("|", 3)
        if not upload_date or upload_date == "NA":
            continue
        if upload_date < FROM_DATE:
            continue
        try:
            dur = int(duration) if duration and duration != "NA" else 0
        except ValueError:
            dur = 0
        rows.append({"id": vid, "title": title, "upload_date": upload_date, "duration": dur})

    # Merge the Atom feed's recent uploads. When yt-dlp is blocked this is the
    # only thing standing between a new video and another silent gap; when
    # yt-dlp works it adds nothing, since those ids are already present.
    known = {r["id"] for r in rows}
    from_feed = [r for r in fetch_feed_videos() if r["id"] not in known]
    if from_feed:
        print(f"  channel feed contributed {len(from_feed)} video(s) yt-dlp "
              f"didn't return.", file=sys.stderr)
        rows.extend(from_feed)
    return rows


def normalize_words(title: str) -> set[str]:
    s = title.lower()
    s = re.sub(r"^(transcript|icymi|watch)\s*[:\-—]\s*", "", s)
    s = re.sub(r"[^\w\s]", " ", s)
    words = {w for w in s.split() if w and w not in STOPWORDS and len(w) > 1}
    return words


def jaccard(a: set, b: set) -> float:
    if not a or not b:
        return 0.0
    return len(a & b) / len(a | b)


def date_diff_days(yyyymmdd: str, iso: str) -> int:
    if not iso:
        return 999
    try:
        a = (int(yyyymmdd[:4]), int(yyyymmdd[4:6]), int(yyyymmdd[6:8]))
        b = (int(iso[:4]), int(iso[5:7]), int(iso[8:10]))
    except ValueError:
        return 999
    # crude — days within a calendar year
    from datetime import date as _date
    return abs((_date(*a) - _date(*b)).days)


def find_match(video: dict, items: list[dict]) -> tuple[dict, float] | tuple[None, float]:
    v_words = normalize_words(video["title"])
    if not v_words:
        return None, 0.0
    best, best_score = None, 0.0
    for item in items:
        # Only consider event-style items where a video would be relevant.
        if item.get("type") in ("executive_order", "designation_letter"):
            continue
        diff = date_diff_days(video["upload_date"], item.get("iso_date", ""))
        if diff > DATE_PROXIMITY_DAYS:
            continue
        i_words = normalize_words(item.get("title", ""))
        j = jaccard(v_words, i_words)
        if j > best_score:
            best_score, best = j, item
    if best_score >= JACCARD_THRESHOLD:
        return best, best_score
    return None, best_score


def is_rate_limited(exc: Exception) -> bool:
    """True when YouTube is throttling us rather than lacking captions.

    These two look identical at the call site but mean opposite things: a
    throttled video still has a transcript and must be retried, while a
    caption-less one never will.
    """
    name = type(exc).__name__
    return name in ("IpBlocked", "TooManyRequests", "RequestBlocked")


def fetch_captions(video_id: str) -> tuple[str, list[dict], str | None]:
    """Return (plain_text, segments, source).

    source = "manual" | "auto" | None (no captions) | "blocked" (throttled —
    caller should back off and let the next run retry).
    """
    try:
        from youtube_transcript_api import YouTubeTranscriptApi  # noqa: WPS433
    except ImportError:
        print("youtube-transcript-api not installed; skipping caption fetch.", file=sys.stderr)
        return "", [], None
    api = YouTubeTranscriptApi()
    try:
        listing = api.list(video_id)
    except Exception as e:
        if is_rate_limited(e):
            return "", [], "blocked"
        print(f"  caption listing failed for {video_id}: {e}", file=sys.stderr)
        return "", [], None
    track = None
    source = None
    # Prefer manual English; fall back to auto English.
    try:
        track = listing.find_manually_created_transcript(["en", "en-US"])
        source = "manual"
    except Exception:
        try:
            track = listing.find_generated_transcript(["en", "en-US"])
            source = "auto"
        except Exception:
            return "", [], None
    try:
        fetched = track.fetch()
    except Exception as e:
        if is_rate_limited(e):
            return "", [], "blocked"
        print(f"  caption fetch failed for {video_id}: {e}", file=sys.stderr)
        return "", [], None
    snippets = fetched.snippets if hasattr(fetched, "snippets") else list(fetched)
    segments: list[dict] = []
    pieces: list[str] = []
    for s in snippets:
        text = getattr(s, "text", None)
        start = getattr(s, "start", None)
        if not text:
            continue
        text = text.replace("\n", " ").strip()
        segments.append({"t": round(float(start or 0), 2), "text": text})
        pieces.append(text)
    plain = " ".join(pieces)
    plain = re.sub(r"\s+", " ", plain).strip()
    return plain, segments, source


def yyyymmdd_to_iso(s: str) -> str:
    if len(s) != 8:
        return ""
    return f"{s[:4]}-{s[4:6]}-{s[6:8]}"


def date_pretty(s: str) -> str:
    if len(s) != 8:
        return ""
    months = ["January", "February", "March", "April", "May", "June", "July",
              "August", "September", "October", "November", "December"]
    y, m, d = int(s[:4]), int(s[4:6]), int(s[6:8])
    return f"{months[m - 1]} {d:02d}, {y}"


def main() -> int:
    if not CORPUS.exists():
        print(f"corpus.json missing at {CORPUS}; run scrape.py first.", file=sys.stderr)
        return 1
    bundle = json.loads(CORPUS.read_text())
    items = bundle["items"]

    videos = list_videos()
    print(f"Found {len(videos)} channel videos since {FROM_DATE}.", file=sys.stderr)
    if not videos:
        # The channel always has videos since FROM_DATE, so zero means the
        # fetch broke, not that there's nothing new. Fail loudly — this
        # returned 0 silently for three months while CI reported success.
        print("No videos resolved — treating as a fetch failure, not an empty "
              "channel. Corpus left unchanged.", file=sys.stderr)
        return 1

    # Index existing video corpus entries to avoid duplication.
    existing_video_ids = {it.get("video_id") for it in items if it.get("type") == "video"}
    existing_video_links = {it.get("video_id"): it for it in items if it.get("type") == "video"}

    matched = 0
    added = 0
    failed = 0
    blocked = 0
    for i, v in enumerate(videos, 1):
        if v["id"] in existing_video_ids:
            # Already added as a video corpus item — leave it.
            continue
        match, score = find_match(v, items)
        watch_url = f"https://www.youtube.com/watch?v={v['id']}"
        if match is not None:
            # Attach to existing item (idempotent).
            match["youtube_url"] = watch_url
            match["youtube_video_id"] = v["id"]
            match["youtube_duration"] = v["duration"]
            matched += 1
            if matched <= 5 or i % 10 == 0:
                print(f"  [{i}/{len(videos)}] match (j={score:.2f}): {v['title'][:60]}\n"
                      f"     ↔ {match['title'][:60]}", file=sys.stderr)
        else:
            # Fetch captions and add as a new video corpus item.
            text, segments, source = fetch_captions(v["id"])
            time.sleep(SLEEP_BETWEEN)
            if source == "blocked":
                # Throttled, not caption-less. Retry once after a pause; if
                # we're still blocked, stop — hammering only extends the block,
                # and these videos are picked up on the next run.
                print(f"  [{i}/{len(videos)}] rate-limited; pausing {BLOCKED_BACKOFF}s…",
                      file=sys.stderr)
                time.sleep(BLOCKED_BACKOFF)
                text, segments, source = fetch_captions(v["id"])
                if source == "blocked":
                    blocked += 1
                    print(f"  Still rate-limited by YouTube — stopping caption fetches. "
                          f"{len(videos) - i} video(s) left for the next run.", file=sys.stderr)
                    break
            if not text:
                failed += 1
                print(f"  [{i}/{len(videos)}] no captions: {v['title'][:80]}", file=sys.stderr)
                continue
            iso = yyyymmdd_to_iso(v["upload_date"])
            new_item = {
                "link": f"/youtube/{v['id']}",
                "url": watch_url,
                "youtube_url": watch_url,
                "youtube_video_id": v["id"],
                "youtube_duration": v["duration"],
                "title": v["title"],
                "date": date_pretty(v["upload_date"]),
                "iso_date": iso,
                "type": "video",
                "source": "youtube",
                # Manual captions are human-typed; auto are machine-generated.
                "reliability": "verified" if source == "manual" else "auto",
                "text": text,
                "word_count": len(text.split()),
                "speakers": [],
                "mayor_quotes": [],
                "mayor_text": text,  # we don't know who's speaking; treat as on-channel content
                "mayor_word_count": len(text.split()),
                "has_mayor_quotes": False,
                "caption_source": source,
                "video_segments": segments,
            }
            items.append(new_item)
            added += 1
            print(f"  [{i}/{len(videos)}] added video ({source}, {len(text.split())}w): {v['title'][:80]}", file=sys.stderr)

    # Re-sort and refresh metadata.
    items.sort(key=lambda x: x.get("iso_date", ""), reverse=True)
    type_counts: dict[str, int] = {}
    for it in items:
        type_counts[it["type"]] = type_counts.get(it["type"], 0) + 1
    bundle["items"] = items
    bundle["total"] = len(items)
    bundle["type_counts"] = type_counts
    bundle["youtube_last_run"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())

    # Reconcile: every listed channel video should now be accounted for, either
    # as its own corpus item or attached to an nyc.gov item. Anything left over
    # is a video we are silently missing — name it rather than let it vanish.
    covered = {it.get("youtube_video_id") for it in items if it.get("youtube_video_id")}
    unaccounted = [v for v in videos if v["id"] not in covered]
    bundle["youtube_coverage"] = {
        "channel_videos": len(videos),
        "covered": len(videos) - len(unaccounted),
        "unaccounted": [{"id": v["id"], "title": v["title"], "date": v["upload_date"]}
                        for v in unaccounted],
    }

    CORPUS.write_text(json.dumps(bundle, ensure_ascii=False, indent=1))
    print(f"\nMatched {matched} videos to existing items; added {added} new video items; {failed} failures.",
          file=sys.stderr)
    print(f"Coverage: {len(videos) - len(unaccounted)}/{len(videos)} channel videos in the corpus.",
          file=sys.stderr)
    for v in unaccounted:
        print(f"  UNACCOUNTED {v['id']} ({v['upload_date']}): {v['title'][:70]}", file=sys.stderr)
    print("Type counts:", type_counts, file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
