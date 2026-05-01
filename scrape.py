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
            # Re-classify each run so improvements to the rules apply without
            # re-downloading. (Title is already in the cached entry.)
            cached["type"] = classify(cached.get("title", ""))
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
        }
        out.append(item)
        new_count += 1
        if i % 10 == 0 or new_count <= 5:
            print(f"  [{i}/{len(articles)}] {item['iso_date']} {item['type']:18s} {title[:80]}")
        time.sleep(SLEEP)

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
