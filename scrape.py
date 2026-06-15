#!/usr/bin/env python3
"""Scrape Mayor Mamdani's on-the-record news from nyc.gov.

Source: https://www.nyc.gov/mayors-office/news/
API: /bin/nyc/articlesearch.json (paginated listing) + each article's
.model.json (full body).

Run: python3 scrape.py
Output: data/corpus.json
"""

from __future__ import annotations

import html
import json
import re
import sys
import time
from pathlib import Path
from urllib.parse import urlencode
from urllib.request import Request, urlopen

ROOT = Path(__file__).parent
DATA = ROOT / "data"
DATA.mkdir(exist_ok=True)
CORPUS = DATA / "corpus.json"

BASE = "https://www.nyc.gov"
LISTING = BASE + "/bin/nyc/articlesearch.json"
PATHS = "/content/nycgov/mayors-office/en/news"
FROM_DATE = "2026-01-01"  # Mamdani took office
PAGE_SIZE = 100
UA = "Mozilla/5.0 (mamdani-transcript-archive; josh.greenman@gmail.com)"
SLEEP = 0.25


def fetch(url: str) -> bytes:
    req = Request(url, headers={"User-Agent": UA})
    with urlopen(req, timeout=30) as r:
        return r.read()


def fetch_json(url: str) -> dict:
    return json.loads(fetch(url).decode("utf-8"))


def list_articles() -> list[dict]:
    out: list[dict] = []
    page = 1
    while True:
        qs = urlencode({
            "pageSize": PAGE_SIZE,
            "currentPage": page,
            "paths": PATHS,
            "fromDate": FROM_DATE,
        })
        d = fetch_json(f"{LISTING}?{qs}")
        out.extend(d["results"])
        total_pages = d["totalPages"]
        print(f"  listing page {page}/{total_pages}: +{len(d['results'])} (total so far {len(out)})")
        if page >= total_pages:
            break
        page += 1
        time.sleep(SLEEP)
    return out


# --- text extraction ---------------------------------------------------------

TAG_RE = re.compile(r"<[^>]+>")
WS_RE = re.compile(r"[ \t]+")
NL_RE = re.compile(r"\n{3,}")


def html_to_text(s: str) -> str:
    # Replace block tags with newlines so paragraph breaks survive.
    s = re.sub(r"<\s*/(p|div|li|h[1-6]|br)\s*>", "\n", s, flags=re.I)
    s = re.sub(r"<\s*br\s*/?>", "\n", s, flags=re.I)
    s = TAG_RE.sub("", s)
    s = html.unescape(s)
    s = WS_RE.sub(" ", s)
    s = NL_RE.sub("\n\n", s)
    return s.strip()


def collect_text(node, parts: list[str]) -> None:
    """Walk the AEM model tree, collecting every richtext-component body."""
    if isinstance(node, dict):
        # AEM rich-text components have ":type":"nycgov/components/text" and
        # field "text". Other components may have a "text" too — the union is
        # what we want.
        t = node.get("text")
        if isinstance(t, str) and len(t.strip()) > 0:
            parts.append(t)
        for v in node.values():
            if isinstance(v, (dict, list)):
                collect_text(v, parts)
    elif isinstance(node, list):
        for x in node:
            collect_text(x, parts)


def model_url_from_link(link: str) -> str:
    # Listing gives "/mayors-office/news/2026/05/some-slug.html"
    # Model JSON is under the AEM content tree.
    assert link.startswith("/mayors-office/news/")
    p = link[len("/mayors-office/news/"):]
    if p.endswith(".html"):
        p = p[: -len(".html")]
    return f"{BASE}/content/nycgov/mayors-office/en/news/{p}.model.json"


# --- classification ----------------------------------------------------------

SPEECH_PATTERNS = [
    "remarks as prepared",
    "remarks as delivered",
    "prepared remarks",
    "delivers remarks",
    "delivers major remarks",
    "delivers address",
    "delivers major address",
    "delivers speech",
    "delivers keynote",
    "delivers his first",
    "deliver remarks",  # "Joins X to Deliver Remarks"
    "100 day address",
    "100-day address",
    "state of the city",
    "inaugural address",
    "inauguration speech",
    "commencement",
    "eulogy",
    "delivers eulogy",
]

MEDIA_PATTERNS = [
    "appears on",
    "appears live on",
    "hosts town hall",
    "joins ",  # often "Joins host on …" — but can also be "Joins Sharpton to Deliver Remarks" — speech check runs first
    "interview",
]

PRESSER_PATTERNS = [
    "holds press conference",
    "holds media availability",
    "press conference",
    "media availability",
    "press briefing",
]

CEREMONY_PATTERNS = [
    "attends ",
    "hosts ",
    "ceremony",
    "swearing-in",
    "wreath laying",
    "memorial",
    "ribbon cutting",
    "ribbon-cutting",
    "groundbreaking",
]


def _contains_any(s: str, patterns: list[str]) -> bool:
    return any(p in s for p in patterns)


def classify(title: str) -> str:
    """Return one of:
        speech | press_conference | media_appearance | ceremony | statement |
        executive_order | designation_letter | other
    """
    t = title.strip().lower()
    # Strip leading "Transcript:" or "ICYMI:" so the rest of the title drives
    # classification — many of his speeches are published as "Transcript: …
    # Delivers Remarks at …". Track whether the prefix was there: any
    # "Transcript:" item is, by definition, a record of him speaking, so we
    # use that as a fallback for items the more specific rules don't match.
    is_transcript = False
    for prefix in ("transcript:", "transcript ", "icymi:", "watch:"):
        if t.startswith(prefix):
            t = t[len(prefix):].strip()
            is_transcript = True
            break

    if "executive order" in t:
        return "executive_order"
    if "designation letter" in t:
        return "designation_letter"
    if (
        t.startswith("statement from")
        or t.startswith("statement by")
        or "mamdani statement" in t
        or "statement from mayor" in t
    ):
        return "statement"
    # Speech check before press/media — "Joins Bernie to Deliver Remarks" is a
    # speech, not a media hit.
    if _contains_any(t, SPEECH_PATTERNS):
        return "speech"
    if _contains_any(t, PRESSER_PATTERNS):
        return "press_conference"
    if _contains_any(t, MEDIA_PATTERNS):
        return "media_appearance"
    if _contains_any(t, CEREMONY_PATTERNS):
        return "ceremony"
    # Catch-all: any "Transcript:" item is the Mayor speaking — treat as a
    # press conference if no more specific rule matched.
    if is_transcript:
        return "press_conference"
    return "other"


# --- speaker parsing & quote extraction --------------------------------------

# A speaker line starts a paragraph (after \n\n or at text start) and follows
# the pattern "Speaker Name:". The label must NOT contain sentence-ending
# punctuation — that filters out things like "...4 a.m. Imagine that:" which
# would otherwise be wrongly read as a sub-speaker. Honorific dots like "Dr."
# fall out of the corpus this way; the cost is acceptable since the official
# transcripts use forms like "Police Commissioner Tisch", not "Dr. Tisch".
SPEAKER_PARA_RE = re.compile(
    r"(?:^|\n\n)([A-Z][\w ,‘’'—\-\[\](){}/&]{1,80}):\s+",
    re.UNICODE,
)

# Mamdani-attribution patterns. Either order:
#  "...quote...," said Mayor (Zohran Kwame) Mamdani
#  Mayor Mamdani said, "...quote..."
QUOTE_AFTER_RE = re.compile(
    r"[“\"]([^“”\"]{30,1200})[”\"]\s*[,\.]?\s*"
    r"said\s+(?:New York City\s+)?Mayor\s+(?:Zohran(?:\s+Kwame)?\s+)?Mamdani",
    re.IGNORECASE,
)
QUOTE_BEFORE_RE = re.compile(
    r"Mayor\s+(?:Zohran(?:\s+Kwame)?\s+)?Mamdani\s+said[,]?\s*"
    r"[“\"]([^“”\"]{30,1200})[”\"]",
    re.IGNORECASE,
)


def _is_mayor_speaker(name: str) -> bool:
    n = name.strip().lower()
    return "mamdani" in n and (
        n.startswith("mayor")
        or n.startswith("zohran")
        or n.startswith("nyc mayor")
        or n.startswith("new york city mayor")
    )


def parse_speakers(text: str) -> list[dict]:
    """Split a transcript into speaker turns. Returns [{speaker, text, is_mayor}].

    Returns an empty list when the transcript doesn't have parseable speaker
    labels (which means the caller should treat the full text as ambiguous).
    """
    if not text:
        return []
    # Normalize line endings — the AEM extraction can leave \n\r\n mixes.
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    matches = list(SPEAKER_PARA_RE.finditer(text))
    if len(matches) < 2:
        return []
    segments: list[dict] = []
    for i, m in enumerate(matches):
        speaker = m.group(1).strip()
        body_start = m.end()
        body_end = matches[i + 1].start() if i + 1 < len(matches) else len(text)
        body = text[body_start:body_end].strip()
        if not body:
            continue
        segments.append(
            {
                "speaker": speaker,
                "text": body,
                "is_mayor": _is_mayor_speaker(speaker),
            }
        )
    return segments


def extract_mayor_quotes(text: str) -> list[str]:
    """Pull out every block of text directly attributed to the Mayor."""
    if not text:
        return []
    seen: set[str] = set()
    out: list[str] = []
    for rx in (QUOTE_AFTER_RE, QUOTE_BEFORE_RE):
        for m in rx.finditer(text):
            q = m.group(1).strip()
            # Collapse internal whitespace.
            q = re.sub(r"\s+", " ", q)
            if q in seen:
                continue
            seen.add(q)
            out.append(q)
    return out


def derive_mayor_text(item: dict) -> str:
    """Return the substring of an item that's specifically the Mayor's words."""
    speakers = item.get("speakers") or []
    if speakers:
        mayor_bits = [s["text"] for s in speakers if s.get("is_mayor")]
        if mayor_bits:
            return "\n\n".join(mayor_bits)
    quotes = item.get("mayor_quotes") or []
    if quotes:
        return "\n\n".join(quotes)
    # For speeches, prepared remarks, statements, and ceremonies the entire
    # text is Mamdani's own words.
    if item.get("type") in ("speech", "statement", "ceremony"):
        return item.get("text", "")
    # Fallback: empty (we don't know what was his)
    return ""


# --- date parsing ------------------------------------------------------------

MONTHS = {m: i for i, m in enumerate(
    ["January", "February", "March", "April", "May", "June",
     "July", "August", "September", "October", "November", "December"], start=1)}


def to_iso(date_str: str) -> str:
    # "May 01, 2026" -> "2026-05-01"
    m = re.match(r"([A-Za-z]+)\s+(\d{1,2}),\s+(\d{4})", date_str.strip())
    if not m:
        return ""
    mon = MONTHS.get(m.group(1), 0)
    return f"{m.group(3)}-{mon:02d}-{int(m.group(2)):02d}"


# --- main --------------------------------------------------------------------

def enrich(item: dict) -> dict:
    """Add derived fields: speakers, mayor_quotes, mayor_text."""
    text = item.get("text", "")
    typ = item.get("type", "")
    # Speaker parsing applies to event transcripts.
    if typ in ("press_conference", "media_appearance", "speech", "ceremony"):
        item["speakers"] = parse_speakers(text)
    else:
        item["speakers"] = []
    # Quote extraction applies to staff-written press releases.
    if typ == "other":
        item["mayor_quotes"] = extract_mayor_quotes(text)
    else:
        item["mayor_quotes"] = []
    item["mayor_text"] = derive_mayor_text(item)
    item["mayor_word_count"] = len(item["mayor_text"].split())
    item["has_mayor_quotes"] = bool(item.get("mayor_quotes"))
    # Provenance: everything this scraper produces is an official, self-published
    # transcript from the Mayor's Office. External scrapers stamp their own.
    item.setdefault("source", "nyc.gov")
    item.setdefault("reliability", "official")
    return item


def load_existing() -> dict[str, dict]:
    if not CORPUS.exists():
        return {}
    data = json.loads(CORPUS.read_text())
    return {item["link"]: item for item in data.get("items", [])}


def main() -> int:
    print(f"Listing articles from {FROM_DATE}…")
    articles = list_articles()
    print(f"Found {len(articles)} articles total.")

    existing = load_existing()
    print(f"Have {len(existing)} cached.")

    out: list[dict] = []
    new_count = 0
    for i, a in enumerate(articles, 1):
        link = a["link"]
        if link in existing and existing[link].get("text"):
            cached = dict(existing[link])
            # Re-classify and re-derive every run so improvements to the rules
            # apply without re-downloading. (Title is in the cached entry.)
            cached["type"] = classify(cached.get("title", ""))
            cached = enrich(cached)
            out.append(cached)
            continue
        try:
            model = fetch_json(model_url_from_link(link))
        except Exception as e:
            print(f"  [{i}/{len(articles)}] FAIL {link}: {e}", file=sys.stderr)
            continue
        parts: list[str] = []
        collect_text(model, parts)
        text_html = "\n\n".join(parts)
        text = html_to_text(text_html)
        title = a["title"]
        item = {
            "link": link,
            "url": BASE + link,
            "title": title,
            "date": a.get("articleDate", ""),
            "iso_date": to_iso(a.get("articleDate", "")),
            "type": classify(title),
            "text": text,
            "word_count": len(text.split()),
            "source": "nyc.gov",
            "reliability": "official",
        }
        item = enrich(item)
        out.append(item)
        new_count += 1
        if i % 10 == 0 or new_count <= 5:
            print(f"  [{i}/{len(articles)}] {item['iso_date']} {item['type']:18s} {title[:80]}")
        time.sleep(SLEEP)

    # Preserve any non-nyc.gov items appended by the other scrapers — YouTube
    # videos (`/youtube/<id>`) and external/Council transcripts (`/cspan/…`,
    # `/npr/…`, `/wnyc/…`, `/podcast/…`, `/council/…`). They don't appear in the
    # nyc.gov listing, so anything whose link isn't a Mayor's-Office article and
    # isn't already in `out` is carried forward untouched.
    seen_links = {it["link"] for it in out}
    for link, it in existing.items():
        if link in seen_links:
            continue
        if not link.startswith("/mayors-office/"):
            # Backfill provenance on legacy items captured before the
            # source/reliability schema existed (mainly older YouTube videos).
            if "source" not in it or "reliability" not in it:
                if it.get("type") == "video" or link.startswith("/youtube/"):
                    it.setdefault("source", "youtube")
                    it.setdefault("reliability",
                                  "verified" if it.get("caption_source") == "manual" else "auto")
                else:
                    it.setdefault("source", "nyc.gov")
                    it.setdefault("reliability", "official")
            out.append(it)

    # Sort newest first.
    out.sort(key=lambda x: x.get("iso_date", ""), reverse=True)

    type_counts: dict[str, int] = {}
    for it in out:
        type_counts[it["type"]] = type_counts.get(it["type"], 0) + 1

    bundle = {
        "generated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "from_date": FROM_DATE,
        "source": "https://www.nyc.gov/mayors-office/news/",
        "total": len(out),
        "type_counts": type_counts,
        "items": out,
    }
    CORPUS.write_text(json.dumps(bundle, ensure_ascii=False, indent=1))
    print(f"\nWrote {CORPUS} — {len(out)} items ({new_count} newly fetched).")
    print("Type counts:", type_counts)
    return 0


if __name__ == "__main__":
    sys.exit(main())
