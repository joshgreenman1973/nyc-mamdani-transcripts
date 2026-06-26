#!/usr/bin/env python3
"""Scrape NYPD newsroom crime-statistics briefings.

The NYPD holds a monthly (and quarterly / year-end) crime-statistics briefing.
Only the ones the Mayor personally attends get a verbatim transcript on the
Mayor's Office site (those are already in the corpus via scrape.py). For the
rest there is NO public transcript — the NYPD's own briefing videos carry no
captions. What the NYPD *does* publish for every briefing is a press release on
its newsroom: a statistical write-up plus attributed quotes from Police
Commissioner Jessica Tisch (and sometimes the Mayor).

So this scraper ingests those press releases, clearly labelled as what they are:

    source      = "nypd"
    type        = "crime_briefing"
    reliability = "release"        # a press release, NOT a verbatim transcript
    is_press_release = True

The newsroom listing is a JavaScript widget backed by a session-gated service
that can't be fetched headless, so — exactly like scrape_external.py's handling
of bot-gated C-SPAN — the briefing URLs are seeded from a human-editable file,
`nypd_sources.json`. Add next month's release there as it's published.

Items are appended to the END of the corpus item list and are deliberately left
out of the semantic-search embeddings (see build_embeddings.mjs); appending
preserves every existing item's array index, so the precomputed embeddings stay
valid without a rebuild. The daily-refresh workflow rebuilds them anyway.

Run: python3 scrape_nypd.py
Input:  nypd_sources.json, data/corpus.json
Output: data/corpus.json (modified in place)
"""

from __future__ import annotations

import html
import json
import re
import sys
import time
from pathlib import Path
from urllib.request import Request, urlopen

import scrape  # reuse html_to_text, to_iso, extract_mayor_quotes, derive_mayor_text

ROOT = Path(__file__).parent
CORPUS = ROOT / "data" / "corpus.json"
SEED = ROOT / "nypd_sources.json"

# The /site/nypd pages block non-browser user agents, so use a real one.
UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
      "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0 Safari/537.36")
FROM_ISO = "2026-01-01"  # archive scope: nothing before the administration began
SLEEP = 1.5              # be gentle — the site returns HTTP 490 if hit too fast

# Acronyms to keep upper-cased when normalising an ALL-CAPS headline.
ACRONYMS = {"NYPD", "NYC", "FDNY", "MTA", "DOC", "CCRB", "DA", "US", "CompStat"}
# Words that should stay capitalised mid-sentence (month names, proper nouns).
CAPITALIZE = {
    "january", "february", "march", "april", "may", "june", "july", "august",
    "september", "october", "november", "december",
}

# Quote attributed to Commissioner Tisch, either order.
TISCH_AFTER_RE = re.compile(
    r"[“\"]([^“”\"]{30,1200})[”\"]\s*[,.]?\s*"
    r"said\s+(?:NYPD\s+)?(?:Police\s+)?Commissioner\s+(?:Jessica\s+(?:S\.?\s+)?)?Tisch",
    re.IGNORECASE,
)
TISCH_BEFORE_RE = re.compile(
    r"(?:NYPD\s+)?(?:Police\s+)?Commissioner\s+(?:Jessica\s+(?:S\.?\s+)?)?Tisch\s+said[,]?\s*"
    r"[“\"]([^“”\"]{30,1200})[”\"]",
    re.IGNORECASE,
)


def fetch(url: str) -> str:
    last = None
    for attempt in range(4):
        try:
            req = Request(url, headers={"User-Agent": UA, "Accept": "text/html"})
            with urlopen(req, timeout=30) as r:
                return r.read().decode("utf-8", "ignore")
        except Exception as e:  # noqa: BLE001 — network is best-effort
            last = e
            time.sleep(2 + attempt * 2)
    raise RuntimeError(f"fetch failed for {url}: {last}")


def _balanced_div(htmltext: str, open_idx: int) -> str:
    """Return the inner HTML of the <div> whose opening tag starts at open_idx."""
    i = htmltext.find(">", open_idx) + 1
    depth = 1
    body_start = i
    tag_re = re.compile(r"<(/?)div\b", re.IGNORECASE)
    for m in tag_re.finditer(htmltext, i):
        depth += -1 if m.group(1) else 1
        if depth == 0:
            return htmltext[body_start:m.start()]
    return htmltext[body_start:]


def _sentence_case(title: str) -> str:
    """Normalise an ALL-CAPS NYPD headline to readable sentence case.

    Faithful to the source wording and punctuation — only the letter case is
    changed, and known acronyms are preserved.
    """
    title = re.sub(r"\s+", " ", title).strip()
    if not (title.isupper() or title == title.upper()):
        return title  # already mixed case — leave it alone
    words = title.split(" ")
    out = []
    for idx, w in enumerate(words):
        stripped = re.sub(r"[^A-Za-z]", "", w)
        if stripped.upper() in {a.upper() for a in ACRONYMS}:
            canon = next(a for a in ACRONYMS if a.upper() == stripped.upper())
            out.append(w.replace(stripped, canon))
        elif stripped.lower() in CAPITALIZE:
            out.append(w.lower().replace(stripped.lower(), stripped.lower().capitalize()))
        elif idx == 0:
            out.append(w.capitalize())
        else:
            out.append(w.lower())
    return " ".join(out)


def parse_release(url: str, htmltext: str) -> dict | None:
    # Title
    mt = re.search(r'<h1[^>]*class="article-title"[^>]*>(.*?)</h1>', htmltext, re.S | re.I)
    if not mt:
        mt = re.search(r"<title>(.*?)</title>", htmltext, re.S | re.I)
    title = _sentence_case(html.unescape(re.sub(r"<[^>]+>", "", mt.group(1))).split("|")[0]) if mt else ""

    # Body: the press-release content lives in <div class="richtext">.
    rm = re.search(r'<div[^>]*class="[^"]*\brichtext\b[^"]*"', htmltext, re.I)
    if not rm:
        return None
    inner = _balanced_div(htmltext, rm.start())
    text = scrape.html_to_text(inner)

    # Date: a <span class="date">Month DD, YYYY</span> leads the body.
    dm = re.search(r'class="date"[^>]*>\s*([A-Za-z]+\s+\d{1,2},\s+20\d\d)', htmltext)
    if not dm:
        dm = re.search(r"([A-Z][a-z]+\s+\d{1,2},\s+20\d\d)", text)
    date = dm.group(1).strip() if dm else ""
    iso = scrape.to_iso(date)
    if not iso or iso < FROM_ISO:
        return None

    # Drop the date line itself out of the body text.
    if date and text.startswith(date):
        text = text[len(date):].lstrip()

    # The NYPD link path (for "Read NYPD release").
    link = url.split("nyc.gov", 1)[1] if "nyc.gov" in url else url

    mayor_quotes = scrape.extract_mayor_quotes(text)
    tisch_quotes = _extract_tisch_quotes(text)

    item = {
        "link": link,
        "url": url,
        "title": title,
        "date": date,
        "iso_date": iso,
        "type": "crime_briefing",
        "text": text,
        "word_count": len(text.split()),
        "source": "nypd",
        "reliability": "release",       # press release, NOT a verbatim transcript
        "is_press_release": True,
        "speakers": [],                  # press releases have no speaker turns
        "mayor_quotes": mayor_quotes,
        "mayor_text": "\n\n".join(mayor_quotes),
        "mayor_word_count": len("\n\n".join(mayor_quotes).split()),
        "has_mayor_quotes": bool(mayor_quotes),
        "commissioner_quotes": tisch_quotes,
    }
    return item


def _extract_tisch_quotes(text: str) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for rx in (TISCH_AFTER_RE, TISCH_BEFORE_RE):
        for m in rx.finditer(text):
            q = re.sub(r"\s+", " ", m.group(1)).strip()
            if q not in seen:
                seen.add(q)
                out.append(q)
    return out


def main() -> int:
    if not SEED.exists():
        print(f"no seed file {SEED}", file=sys.stderr)
        return 0
    seed = json.loads(SEED.read_text())
    releases = seed.get("releases", [])

    data = json.loads(CORPUS.read_text())
    items = data["items"]
    have = {it.get("url") for it in items}

    added = 0
    for entry in releases:
        url = entry.get("url")
        if not url or url in have:
            continue
        try:
            item = parse_release(url, fetch(url))
        except Exception as e:  # noqa: BLE001 — one bad URL shouldn't kill the run
            print(f"  skip {url}: {e}", file=sys.stderr)
            time.sleep(SLEEP)
            continue
        if not item or not item["text"]:
            print(f"  skip {url}: no body parsed", file=sys.stderr)
            time.sleep(SLEEP)
            continue
        items.append(item)          # append at END to preserve existing indices
        have.add(url)
        added += 1
        print(f"  + {item['iso_date']} crime_briefing  {item['title'][:70]}")
        time.sleep(SLEEP)

    if added:
        # Refresh the summary counters.
        data["total"] = len(items)
        type_counts: dict[str, int] = {}
        source_counts: dict[str, int] = {}
        for it in items:
            type_counts[it.get("type", "other")] = type_counts.get(it.get("type", "other"), 0) + 1
            source_counts[it.get("source", "nyc.gov")] = source_counts.get(it.get("source", "nyc.gov"), 0) + 1
        data["type_counts"] = type_counts
        data["source_counts"] = source_counts
        data["nypd_last_run"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
        CORPUS.write_text(json.dumps(data, ensure_ascii=False))

    print(f"NYPD crime briefings: added {added}, corpus now {len(items)} items.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
