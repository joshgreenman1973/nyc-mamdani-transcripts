#!/usr/bin/env python3
"""Scrape Mayor Mamdani transcripts from sources OTHER than nyc.gov / YouTube.

Adds, idempotently, to data/corpus.json:
  - NPR     : npr.org/transcripts/<id>          reliability "verified"
  - WNYC    : Brian Lehrer "Ask the Mayor" etc. reliability "verified"
  - C-SPAN  : closed-caption transcripts         reliability "auto"
  - Podcast : <podcast:transcript> tags, if any  reliability per tag

Discovery on these sources can't be fully automated — their search pages are
JavaScript-rendered and bot-gated — so the backbone is a curated seed list in
external_sources.json. WNYC is additionally auto-discovered from the Brian
Lehrer Show RSS feed (any episode whose title mentions Mamdani / "Ask the
Mayor"). Podcast feeds are scanned passively: we only ingest an episode if it
actually publishes a machine-readable transcript.

Every fetch failure is LOUD: a blocked/empty response is treated as a hard
failure and skipped, never written as an empty transcript. Run after scrape.py
(and scrape_youtube.py); it reads and rewrites corpus.json in place.

Run: python3 scrape_external.py
"""

from __future__ import annotations

import html
import json
import re
import sys
import time
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

import scrape  # reuse classify / parse_speakers / html_to_text / to_iso

ROOT = Path(__file__).parent
CORPUS = ROOT / "data" / "corpus.json"
REGISTRY = ROOT / "external_sources.json"
UA = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 " \
     "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"
SLEEP = 1.0          # be polite; C-SPAN soft-blocks fast bursts
CSPAN_SLEEP = 8.0    # C-SPAN/CloudFront throttles aggressively

MONTHS = ["January", "February", "March", "April", "May", "June", "July",
          "August", "September", "October", "November", "December"]


# --- fetch -------------------------------------------------------------------

def fetch(url: str, referer: str | None = None) -> bytes:
    headers = {"User-Agent": UA, "Accept-Language": "en-US,en;q=0.9"}
    if referer:
        headers["Referer"] = referer
    req = Request(url, headers=headers)
    with urlopen(req, timeout=45) as r:
        if r.status not in (200, None):
            raise URLError(f"HTTP {r.status}")
        return r.read()


def pretty_date(iso: str) -> str:
    m = re.match(r"(\d{4})-(\d{2})-(\d{2})", iso or "")
    if not m:
        return ""
    y, mo, d = int(m.group(1)), int(m.group(2)), int(m.group(3))
    return f"{MONTHS[mo - 1]} {d:02d}, {y}"


def find_date(page: str) -> str:
    """Best-effort publish date: JSON-LD first, then a visible 'Month D, YYYY'."""
    m = re.search(r'"datePublished"\s*:\s*"(\d{4})-(\d{2})-(\d{2})', page)
    if m:
        return f"{m.group(1)}-{m.group(2)}-{m.group(3)}"
    m = re.search(r"([A-Z][a-z]+ \d{1,2}, 20\d\d)", page)
    return scrape.to_iso(m.group(1)) if m else ""


def page_title(page: str) -> str:
    m = re.search(r'<meta[^>]+property=["\']og:title["\'][^>]+content=["\']([^"\']+)', page)
    if m:
        return html.unescape(m.group(1)).strip()
    m = re.search(r"<title>(.*?)</title>", page, re.I | re.S)
    return html.unescape(re.sub(r"\s+", " ", m.group(1))).strip() if m else ""


# --- mayor-aware enrichment (lenient: any "…Mamdani…" speaker) ---------------

def _is_mayor(name: str) -> bool:
    return "mamdani" in name.strip().lower()


def enrich_external(item: dict) -> dict:
    """Parse speaker turns and isolate the Mayor's words where possible.

    These are interviews, so the Mayor is the subject. When speaker turns can't
    cleanly isolate him, fall back to the full text for `mayor_text` — the same
    convention the YouTube video items use — so the item still surfaces under
    the "Only the Mayor's words" filter.
    """
    text = item.get("text", "")
    speakers = scrape.parse_speakers(text)
    for s in speakers:
        s["is_mayor"] = _is_mayor(s["speaker"])
    item["speakers"] = speakers
    mayor_bits = [s["text"] for s in speakers if s["is_mayor"]]
    if mayor_bits:
        item["mayor_text"] = "\n\n".join(mayor_bits)
    elif speakers:
        # Turns parsed cleanly but the Mayor isn't among them — he didn't speak
        # here. Don't pretend the whole segment is his words.
        item["mayor_text"] = ""
    else:
        # No speaker labels at all (e.g. a raw caption blob): attribution is
        # unknown, so treat the full text as his — same as YouTube video items.
        item["mayor_text"] = text
    item["mayor_quotes"] = []
    item["has_mayor_quotes"] = False
    item["word_count"] = len(text.split())
    item["mayor_word_count"] = len(item["mayor_text"].split())
    return item


def make_item(*, link, url, title, iso_date, text, source, reliability,
              extra=None) -> dict:
    item = {
        "link": link,
        "url": url,
        "title": title,
        "date": pretty_date(iso_date),
        "iso_date": iso_date,
        "type": scrape.classify(title) or "media_appearance",
        "source": source,
        "reliability": reliability,
        "text": text,
    }
    # Interviews on outside outlets are media appearances even when the title
    # doesn't trip the classifier's patterns.
    if item["type"] in ("other", "ceremony"):
        item["type"] = "media_appearance"
    if extra:
        item.update(extra)
    return enrich_external(item)


# --- NPR ---------------------------------------------------------------------

def scrape_npr(story_id: str) -> dict | None:
    url = f"https://www.npr.org/transcripts/{story_id}"
    try:
        page = fetch(url).decode("utf-8", "replace")
    except (HTTPError, URLError, OSError) as e:
        print(f"  NPR {story_id}: fetch failed: {e}", file=sys.stderr)
        return None
    m = re.search(r'<div[^>]*class="[^"]*transcript storytext[^"]*"[^>]*>(.*?)</div>\s*(?:<div|<p class="user-actions)',
                  page, re.S)
    if not m:
        # Fall back to the first storytext block.
        m = re.search(r'class="[^"]*transcript storytext[^"]*"[^>]*>(.*)', page, re.S)
        if not m:
            print(f"  NPR {story_id}: no transcript block found", file=sys.stderr)
            return None
    block = m.group(1)
    # NPR uses unclosed <p> tags as separators.
    parts = re.split(r"<p[^>]*>", block)
    turns: list[str] = []
    for p in parts:
        t = scrape.html_to_text(p)
        if not t:
            continue
        low = t.lower()
        if low.startswith(("copyright", "[music", "new episodes of")) or "npr.org" in low and len(t) < 120:
            continue
        if "transcripts are created" in low or "accuracy and availability may vary" in low:
            continue
        turns.append(t)
    text = "\n\n".join(turns).strip()
    if len(text.split()) < 60:
        print(f"  NPR {story_id}: transcript too short ({len(text.split())}w) — skipping", file=sys.stderr)
        return None
    title = page_title(page) or f"NPR interview {story_id}"
    title = re.sub(r"\s*[:|]\s*NPR\b.*$", "", title).strip()
    iso = find_date(page)
    return make_item(link=f"/npr/{story_id}", url=url, title=title, iso_date=iso,
                     text=text, source="npr", reliability="verified")


# --- WNYC --------------------------------------------------------------------

WNYC_MARKER = "New York Public Radio transcripts are created"


def _wnyc_extract(page: str) -> str:
    idx = page.find(WNYC_MARKER)
    if idx == -1:
        return ""
    window = page[max(0, idx - 60000): idx]
    # The transcript lives as escaped HTML inside a serialized JSON payload.
    try:
        decoded = window.encode("utf-8", "replace").decode("unicode_escape")
    except (UnicodeDecodeError, UnicodeEncodeError):
        decoded = window
    # Keep only from the last clear paragraph start so we drop JSON scaffolding.
    decoded = re.sub(r"\\/", "/", decoded)
    text = scrape.html_to_text(decoded)
    # Put each speaker label ("Brian Lehrer:", "Zohran Mamdani:", "Liz Kim:") at
    # the start of its own paragraph so scrape.parse_speakers can split turns.
    text = re.sub(r"(?<=[.?!\"”\s])((?:[A-Z][a-z'’]+ ){0,2}[A-Z][a-z'’]+):\s",
                  r"\n\n\1: ", text)
    # Trim everything before the first speaker label if one exists.
    m = re.search(r"\n\n([A-Z][\w .'-]{1,60}:\s)", "\n\n" + text)
    if m:
        text = text[m.start():].strip()
    return text.strip()


def scrape_wnyc(episode_uuid: str) -> dict | None:
    candidates = [
        f"https://www.wnyc.org/browse/shows/episode/simplecast/{episode_uuid}",
        f"https://www.wnycstudios.org/browse/shows/episode/simplecast/{episode_uuid}",
    ]
    page = ""
    used = candidates[0]
    for url in candidates:
        try:
            page = fetch(url).decode("utf-8", "replace")
            used = url
            if WNYC_MARKER in page:
                break
        except (HTTPError, URLError, OSError) as e:
            print(f"  WNYC {episode_uuid}: {url} failed: {e}", file=sys.stderr)
    if WNYC_MARKER not in page:
        print(f"  WNYC {episode_uuid}: no transcript on page yet — skipping", file=sys.stderr)
        return None
    text = _wnyc_extract(page)
    if len(text.split()) < 80:
        print(f"  WNYC {episode_uuid}: extracted text too short — skipping", file=sys.stderr)
        return None
    title = page_title(page) or "WNYC — The Brian Lehrer Show"
    iso = find_date(page)
    return make_item(link=f"/wnyc/{episode_uuid}", url=used, title=title,
                     iso_date=iso, text=text, source="wnyc", reliability="verified")


def discover_wnyc_episodes() -> list[str]:
    """Find Brian Lehrer episodes mentioning Mamdani from the show RSS feed."""
    feed_url = "https://feeds.simplecast.com/C8a1jmw4"  # The Brian Lehrer Show
    uuids: list[str] = []
    try:
        xml = fetch(feed_url).decode("utf-8", "replace")
    except (HTTPError, URLError, OSError) as e:
        print(f"  WNYC feed discovery failed: {e}", file=sys.stderr)
        return uuids
    items = re.findall(r"<item>(.*?)</item>", xml, re.S)
    for it in items:
        title = (re.search(r"<title>(.*?)</title>", it, re.S) or [None, ""])[1]
        title_l = html.unescape(title).lower()
        if "mamdani" not in title_l and "ask the mayor" not in title_l:
            continue
        # Simplecast episode UUID appears in the enclosure / guid / link.
        m = re.search(r"simplecast\.com/episodes/([0-9a-f-]{36})", it) \
            or re.search(r"/episode/simplecast/([0-9a-f-]{36})", it)
        if m:
            uuids.append(m.group(1))
    return uuids


# --- C-SPAN ------------------------------------------------------------------

def scrape_cspan(program_id: str, seed_title: str = "", seed_iso: str = "") -> dict | None:
    ref = f"https://www.c-span.org/program/{program_id}"
    svc = (f"https://www.c-span.org/common/services/transcript/"
           f"?videoId={program_id}&videoType=program&transcriptType=cc&transcriptQuery=")
    try:
        raw = fetch(svc, referer=ref)
    except (HTTPError, URLError, OSError) as e:
        print(f"  C-SPAN {program_id}: transcript fetch failed (blocked?): {e}", file=sys.stderr)
        return None
    body = raw.decode("utf-8", "replace").strip()
    if not body:
        print(f"  C-SPAN {program_id}: EMPTY body — treated as block, skipping", file=sys.stderr)
        return None
    try:
        data = json.loads(body)
    except json.JSONDecodeError:
        print(f"  C-SPAN {program_id}: non-JSON body — treated as block, skipping", file=sys.stderr)
        return None
    parts = data.get("parts") or []
    if not parts:
        print(f"  C-SPAN {program_id}: no caption parts (not captioned yet, or blocked)", file=sys.stderr)
        return None
    turns: list[str] = []
    last_speaker = None
    for p in parts:
        txt = (p.get("text") or "").strip()
        if not txt:
            continue
        spk = (p.get("speakername") or "").strip()
        if spk and spk != last_speaker:
            turns.append(f"{spk}: {txt}")
            last_speaker = spk
        else:
            turns.append(txt)
    text = "\n\n".join(turns).strip()
    if len(text.split()) < 60:
        print(f"  C-SPAN {program_id}: transcript too short — skipping", file=sys.stderr)
        return None
    # Prefer seed-provided title/date — the program page is bot-gated and
    # fetching it risks a block and yields only a generic "C-SPAN.org" title.
    # Only scrape the page when the seed didn't supply both.
    title, iso = seed_title, seed_iso
    if not (seed_title and seed_iso):
        try:
            time.sleep(CSPAN_SLEEP)
            page = fetch(ref).decode("utf-8", "replace")
            scraped = page_title(page)
            if scraped and "c-span.org" not in scraped.lower():
                title = title or scraped
            iso = iso or find_date(page)
        except (HTTPError, URLError, OSError):
            pass
    title = title or f"C-SPAN program {program_id}"
    return make_item(link=f"/cspan/{program_id}", url=ref, title=title,
                     iso_date=iso, text=text, source="cspan", reliability="auto")


# --- Podcast (<podcast:transcript> tags) -------------------------------------

def scrape_podcast_feed(feed_url: str, match: str) -> list[dict]:
    out: list[dict] = []
    try:
        xml = fetch(feed_url).decode("utf-8", "replace")
    except (HTTPError, URLError, OSError) as e:
        print(f"  podcast feed {feed_url}: fetch failed: {e}", file=sys.stderr)
        return out
    items = re.findall(r"<item>(.*?)</item>", xml, re.S)
    match_l = (match or "mamdani").lower()
    for it in items:
        blob = html.unescape(it).lower()
        if match_l not in blob:
            continue
        tr = re.search(r'<podcast:transcript[^>]*\burl="([^"]+)"[^>]*(?:\btype="([^"]+)")?', it)
        title = scrape.html_to_text((re.search(r"<title>(.*?)</title>", it, re.S) or [None, ""])[1]) or "Podcast episode"
        if not tr:
            print(f"  podcast: '{title[:60]}' mentions Mamdani but has no transcript tag — skipped", file=sys.stderr)
            continue
        turl, ttype = tr.group(1), (tr.group(2) or "")
        try:
            doc = fetch(turl).decode("utf-8", "replace")
        except (HTTPError, URLError, OSError) as e:
            print(f"  podcast transcript {turl}: fetch failed: {e}", file=sys.stderr)
            continue
        text = parse_transcript_doc(doc, ttype)
        if len(text.split()) < 60:
            continue
        guid = (re.search(r"<guid[^>]*>(.*?)</guid>", it, re.S) or [None, turl])[1]
        slug = re.sub(r"[^a-z0-9]+", "-", html.unescape(guid).lower()).strip("-")[:60]
        pub = re.search(r"<pubDate>(.*?)</pubDate>", it)
        iso = parse_rfc822(pub.group(1)) if pub else ""
        out.append(make_item(link=f"/podcast/{slug}", url=turl, title=title,
                             iso_date=iso, text=text, source="podcast",
                             reliability="verified"))
    return out


def parse_transcript_doc(doc: str, ttype: str) -> str:
    t = ttype.lower()
    if "json" in t:
        try:
            data = json.loads(doc)
            segs = data.get("segments") or data.get("results") or []
            return " ".join(s.get("body") or s.get("text") or "" for s in segs).strip()
        except json.JSONDecodeError:
            return ""
    if "vtt" in t or "srt" in t or doc.lstrip().startswith("WEBVTT"):
        lines = []
        for ln in doc.splitlines():
            ln = ln.strip()
            if not ln or ln == "WEBVTT" or "-->" in ln or ln.isdigit():
                continue
            lines.append(ln)
        return scrape.html_to_text(" ".join(lines))
    return scrape.html_to_text(doc)


def parse_rfc822(s: str) -> str:
    try:
        from email.utils import parsedate_to_datetime
        return parsedate_to_datetime(s).date().isoformat()
    except (TypeError, ValueError):
        return ""


# --- main --------------------------------------------------------------------

def main() -> int:
    if not CORPUS.exists():
        print("corpus.json missing; run scrape.py first.", file=sys.stderr)
        return 1
    bundle = json.loads(CORPUS.read_text())
    items = bundle["items"]
    by_link = {it["link"]: it for it in items}

    reg = json.loads(REGISTRY.read_text()) if REGISTRY.exists() else {}
    added = 0

    def ingest(item: dict | None, seed: dict | None = None) -> None:
        nonlocal added
        if not item:
            return
        # Seed fallbacks for date/title the page didn't yield.
        if seed:
            if seed.get("date") and not item.get("iso_date"):
                item["iso_date"] = seed["date"]
                item["date"] = pretty_date(seed["date"])
            if seed.get("title") and (not item.get("title") or "c-span" in item["title"].lower()):
                item["title"] = seed["title"]
        # This is a "since took office" archive — drop anything from before
        # Jan 1, 2026 (e.g. campaign-era interviews) when the date is known.
        if item.get("iso_date") and item["iso_date"] < "2026-01-01":
            print(f"  - skip (pre-2026, out of scope): {item['title'][:70]}", file=sys.stderr)
            return
        if item["link"] in by_link:
            # Refresh in place (title/date may improve) but don't double-count.
            idx = items.index(by_link[item["link"]])
            items[idx] = item
            by_link[item["link"]] = item
            return
        items.append(item)
        by_link[item["link"]] = item
        added += 1
        print(f"  + [{item['source']}/{item['reliability']}] "
              f"{item['iso_date'] or '????-??-??'} {item['title'][:70]} ({item['word_count']}w)")

    # NPR
    for e in reg.get("npr", []):
        ingest(scrape_npr(e["id"]), e)
        time.sleep(SLEEP)

    # WNYC: seeds + auto-discovery from the Brian Lehrer feed.
    seen_uuid: set[str] = set()
    for e in reg.get("wnyc", []):
        seen_uuid.add(e["id"])
        ingest(scrape_wnyc(e["id"]), e)
        time.sleep(SLEEP)
    for uuid in discover_wnyc_episodes():
        if uuid in seen_uuid:
            continue
        seen_uuid.add(uuid)
        ingest(scrape_wnyc(uuid))
        time.sleep(SLEEP)

    # C-SPAN (slow + block-prone; non-fatal per item).
    for e in reg.get("cspan", []):
        ingest(scrape_cspan(str(e["id"]), e.get("title", ""), e.get("date", "")), e)
        time.sleep(CSPAN_SLEEP)

    # Podcasts: only those that publish a real transcript.
    for e in reg.get("podcast", []):
        for item in scrape_podcast_feed(e["id"], e.get("match", "mamdani")):
            ingest(item)
        time.sleep(SLEEP)

    items.sort(key=lambda x: x.get("iso_date", ""), reverse=True)
    type_counts: dict[str, int] = {}
    source_counts: dict[str, int] = {}
    for it in items:
        type_counts[it["type"]] = type_counts.get(it["type"], 0) + 1
        source_counts[it.get("source", "nyc.gov")] = source_counts.get(it.get("source", "nyc.gov"), 0) + 1
    bundle["items"] = items
    bundle["total"] = len(items)
    bundle["type_counts"] = type_counts
    bundle["source_counts"] = source_counts
    bundle["external_last_run"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    CORPUS.write_text(json.dumps(bundle, ensure_ascii=False, indent=1))
    print(f"\nExternal scrape done: +{added} new items. Total {len(items)}.")
    print("Source counts:", source_counts)
    return 0


if __name__ == "__main__":
    sys.exit(main())
