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
import re
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).parent
CORPUS = ROOT / "data" / "corpus.json"
CHANNEL = "https://www.youtube.com/@NYCMayorsOffice/videos"
FROM_DATE = "20260101"  # YYYYMMDD format used by yt-dlp
DATE_PROXIMITY_DAYS = 3
JACCARD_THRESHOLD = 0.45
SLEEP_BETWEEN = 0.4

STOPWORDS = {
    "a", "an", "and", "as", "at", "be", "by", "for", "from", "in", "is",
    "it", "of", "on", "or", "the", "to", "with", "transcript", "icymi",
    "watch", "remarks", "as", "prepared", "delivered", "mayor", "mamdani",
    "zohran", "kwame", "today", "new", "york", "city", "nyc",
}


def list_videos() -> list[dict]:
    """Return [{id, title, upload_date(YYYYMMDD), duration}] from the channel.

    Uses two passes: flat-playlist to get IDs cheaply (no rate-limit risk),
    then per-video metadata fetch to get upload_date and duration. The flat
    listing alone returns NA for upload_date — only the per-video page does.
    """
    print(f"Listing channel video IDs…", file=sys.stderr)
    flat_cmd = [
        sys.executable, "-m", "yt_dlp",
        "--flat-playlist",
        "--print", "%(id)s|%(title)s",
        CHANNEL,
    ]
    try:
        flat_out = subprocess.check_output(flat_cmd, stderr=subprocess.DEVNULL, text=True, timeout=180)
    except subprocess.CalledProcessError as e:
        print(f"yt-dlp listing failed: {e}", file=sys.stderr)
        return []
    candidates: list[tuple[str, str]] = []  # (id, title)
    for line in flat_out.splitlines():
        if "|" not in line:
            continue
        vid, title = line.split("|", 1)
        if vid:
            candidates.append((vid, title))
    print(f"  channel has {len(candidates)} videos; fetching metadata…", file=sys.stderr)

    rows: list[dict] = []
    cmd = [
        sys.executable, "-m", "yt_dlp",
        "--no-download", "--no-warnings",
        "--dateafter", FROM_DATE,
        "--print", "%(upload_date)s|%(id)s|%(duration)s|%(title)s",
    ] + [f"https://www.youtube.com/watch?v={vid}" for vid, _ in candidates]
    try:
        out = subprocess.check_output(cmd, stderr=subprocess.DEVNULL, text=True, timeout=900)
    except subprocess.CalledProcessError as e:
        print(f"yt-dlp metadata fetch failed: {e}", file=sys.stderr)
        return []
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


def fetch_captions(video_id: str) -> tuple[str, list[dict], str | None]:
    """Return (plain_text, segments, source). source = "manual" | "auto" | None."""
    try:
        from youtube_transcript_api import YouTubeTranscriptApi  # noqa: WPS433
    except ImportError:
        print("youtube-transcript-api not installed; skipping caption fetch.", file=sys.stderr)
        return "", [], None
    api = YouTubeTranscriptApi()
    try:
        listing = api.list(video_id)
    except Exception as e:
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

    # Index existing video corpus entries to avoid duplication.
    existing_video_ids = {it.get("video_id") for it in items if it.get("type") == "video"}
    existing_video_links = {it.get("video_id"): it for it in items if it.get("type") == "video"}

    matched = 0
    added = 0
    failed = 0
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

    CORPUS.write_text(json.dumps(bundle, ensure_ascii=False, indent=1))
    print(f"\nMatched {matched} videos to existing items; added {added} new video items; {failed} failures.",
          file=sys.stderr)
    print("Type counts:", type_counts, file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
