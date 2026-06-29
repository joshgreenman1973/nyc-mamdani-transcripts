#!/usr/bin/env python3
"""Crawl NYC city-agency press releases (the "mega search" expansion).

City Hall (the Mayor's Office) is scraped by scrape.py. This adds the city
*agencies'* press releases. Agency newsrooms live on the old LiveSite CMS whose
listing feed resists headless scraping, but individual release URLs follow a
numeric, year-scoped id — and requesting /site/<slug>/news/<id>/x (any slug)
redirects to the canonical article. So we enumerate ids upward per agency until
a run of misses, following redirects to harvest each release. Agencies and their
id formats are configured in agencies.json.

Items are tagged source=<slug>, type="agency_release", reliability="release"
(a press release, not a verbatim transcript). Any quote attributed to Mayor
Mamdani is still extracted, so agency releases surface under "Only the Mayor's
words" — Mamdani's voice stays the center even as the corpus widens.

State (highest id seen per agency) is kept in the corpus so daily refreshes are
incremental and cheap. New items are appended at the END of the item list, which
preserves every existing item's array index and keeps the precomputed semantic
embeddings valid without a rebuild (agency releases are excluded from that index
anyway — see build_embeddings.mjs).

Run:
  python3 scrape_agencies.py                 # incremental (resume from state)
  AGENCY_BACKFILL=1 python3 scrape_agencies.py   # ignore state, full backfill
Input:  agencies.json, data/corpus.json
Output: data/corpus.json (modified in place)
"""

from __future__ import annotations

import json
import os
import re
import sys
import time
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

import scrape  # html_to_text, to_iso, extract_mayor_quotes
import scrape_nypd as sn  # _balanced_div, tables_to_text, _sentence_case

ROOT = Path(__file__).parent
CORPUS = ROOT / "data" / "corpus.json"
CONFIG = ROOT / "agencies.json"

BASE = "https://www.nyc.gov"
UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
      "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0 Safari/537.36")
FROM_ISO = "2026-01-01"
SLEEP = 1.2                 # gentle: the WAF returns HTTP 490 if hit too fast
GAP_LIMIT = 12              # stop an agency after this many consecutive misses
MIN_WORDS = 25              # skip thin "in the news" media-mention stubs (no body)
# Max release-id probes per run across all agencies. Large for local backfill;
# the daily cron sets a smaller budget so a run always finishes in time.
BUDGET = int(os.environ.get("AGENCY_BUDGET", "5000"))


def fetch_redirect(url: str):
    """GET url following redirects. Returns (final_url, html) or None on 404."""
    for attempt in range(5):
        try:
            req = Request(url, headers={"User-Agent": UA, "Accept": "text/html"})
            with urlopen(req, timeout=30) as r:
                return r.geturl(), r.read().decode("utf-8", "ignore")
        except HTTPError as e:
            if e.code == 404:
                return None
            # 490 = WAF rate-limit; 5xx = transient. Back off and retry.
            time.sleep(5 + attempt * 5)
        except (URLError, TimeoutError):
            time.sleep(3 + attempt * 2)
    return None


def parse_release(url: str, htmltext: str, source: str) -> dict | None:
    """Parse a LiveSite agency release into a corpus item (shared template)."""
    import re
    rm = re.search(r'<div[^>]*class="[^"]*\brichtext\b[^"]*"', htmltext, re.I)
    if not rm:
        return None
    inner = sn.tables_to_text(sn._balanced_div(htmltext, rm.start()))
    text = scrape.html_to_text(inner)

    mt = re.search(r'<h1[^>]*class="article-title"[^>]*>(.*?)</h1>', htmltext, re.S | re.I)
    import html as _html
    title = sn._sentence_case(_html.unescape(re.sub(r"<[^>]+>", "", mt.group(1)))) if mt else ""

    dm = re.search(r'class="date"[^>]*>\s*([A-Za-z]+\s+\d{1,2},\s+20\d\d)', htmltext)
    if not dm:
        dm = re.search(r"([A-Z][a-z]+\s+\d{1,2},\s+20\d\d)", text)
    date = dm.group(1).strip() if dm else ""
    iso = scrape.to_iso(date)
    if not iso or iso < FROM_ISO:
        return None
    if date and text.startswith(date):
        text = text[len(date):].lstrip()
    # Skip "in the news" media-mention stubs (a headline + external link, no body).
    if len(text.split()) < MIN_WORDS:
        return None

    link = url.split("nyc.gov", 1)[1] if "nyc.gov" in url else url
    mayor_quotes = scrape.extract_mayor_quotes(text)
    return {
        "link": link,
        "url": url,
        "title": title,
        "date": date,
        "iso_date": iso,
        "type": "agency_release",
        "text": text,
        "word_count": len(text.split()),
        "source": source,
        "reliability": "release",       # press release, NOT a verbatim transcript
        "is_press_release": True,
        "speakers": [],
        "mayor_quotes": mayor_quotes,
        "mayor_text": "\n\n".join(mayor_quotes),
        "mayor_word_count": len("\n\n".join(mayor_quotes).split()),
        "has_mayor_quotes": bool(mayor_quotes),
    }


# Some agency newsrooms use a different LiveSite template (`ls-col-body`) with
# slug URLs instead of numeric ids. The body sits between the date and the page
# footer with no clean wrapper, so we bound it by the date and a footer marker.
_LS_FOOTER = re.compile(
    r"(\#\#\#|Your government|Website feedback|Privacy policy|Terms of use|"
    r"About nyc\.gov content|©\s*City of New York|Was this information helpful|"
    r"nyc\.gov\s*home)", re.I)
_LS_DATE = re.compile(r"([A-Z][a-z]+ \d{1,2}, 20\d\d)")


def parse_release_ls(url: str, htmltext: str, source: str) -> dict | None:
    import html as _html
    m = re.search(r'<div[^>]*class="[^"]*ls-col-body[^"]*"', htmltext, re.I)
    if not m:
        return None
    inner = sn.tables_to_text(sn._balanced_div(htmltext, m.start()))
    text = scrape.html_to_text(inner)

    # Title: the <title> tag is the most uniform headline source here; strip the
    # trailing " - <Agency>" / " | City of New York" site suffix.
    tt = re.search(r"<title>(.*?)</title>", htmltext, re.S | re.I)
    title = _html.unescape(re.sub("<[^>]+>", "", tt.group(1))).strip() if tt else ""
    title = re.sub(r"\s*[|–-]\s*(City of New York|[A-Z][A-Za-z&'.\s]{1,40})$", "", title).strip()

    dm = _LS_DATE.search(text)
    date = dm.group(1) if dm else ""
    iso = scrape.to_iso(date)
    if not iso or iso < FROM_ISO:
        return None
    start = text.find(date)
    fm = _LS_FOOTER.search(text, start + len(date))
    body = text[start:(fm.start() if fm else len(text))].strip()
    body = re.sub(r"^[A-Z][a-z]+ \d{1,2}, 20\d\d\s*[—–-]?\s*", "", body).strip()
    if len(body.split()) < MIN_WORDS:
        return None

    link = url.split("nyc.gov", 1)[1] if "nyc.gov" in url else url
    mayor_quotes = scrape.extract_mayor_quotes(body)
    return {
        "link": link, "url": url, "title": title, "date": date, "iso_date": iso,
        "type": "agency_release", "text": body, "word_count": len(body.split()),
        "source": source, "reliability": "release", "is_press_release": True,
        "speakers": [], "mayor_quotes": mayor_quotes,
        "mayor_text": "\n\n".join(mayor_quotes),
        "mayor_word_count": len("\n\n".join(mayor_quotes).split()),
        "has_mayor_quotes": bool(mayor_quotes),
    }


_LS_NAV = re.compile(
    r"(/index\.page|/contact|/about\.page|press-releases\.page|recent-press-releases|"
    r"/news\.page|/faq|/help|find-a-partner|cultural-funding|/sheriff|public-reports|"
    r"frequently-asked)", re.I)


def parse_release_dot(url: str, htmltext: str, source: str) -> dict | None:
    """Parse a DOT-style legacy /html release (.shtml, `agency-content` body)."""
    import html as _html
    m = re.search(r'<div[^>]*class="[^"]*agency-content[^"]*"', htmltext, re.I)
    if not m:
        return None
    text = scrape.html_to_text(sn.tables_to_text(sn._balanced_div(htmltext, m.start())))
    st = (re.search(r'<h2[^>]*id="page_subtitle"[^>]*>(.*?)</h2>', htmltext, re.S | re.I)
          or re.search(r"<title>(.*?)</title>", htmltext, re.S | re.I))
    title = _html.unescape(re.sub("<[^>]+>", "", st.group(1))).strip() if st else ""
    title = re.sub(r"\s*\|\s*City of New York$", "", title).strip()
    dm = _LS_DATE.search(text)
    date = dm.group(1) if dm else ""
    iso = scrape.to_iso(date)
    if not iso or iso < FROM_ISO:
        return None
    # Body begins after the headline echo; ends at the "###" release marker.
    bstart = 0
    if title:
        i = text.find(title)
        if i >= 0:
            bstart = i + len(title)
    cut = text.find("###", bstart)
    body = text[bstart:(cut if cut > 0 else len(text))].strip()
    if len(body.split()) < MIN_WORDS:
        return None
    link = url.split("nyc.gov", 1)[1] if "nyc.gov" in url else url
    mayor_quotes = scrape.extract_mayor_quotes(body)
    return {
        "link": link, "url": url, "title": title, "date": date, "iso_date": iso,
        "type": "agency_release", "text": body, "word_count": len(body.split()),
        "source": source, "reliability": "release", "is_press_release": True,
        "speakers": [], "mayor_quotes": mayor_quotes,
        "mayor_text": "\n\n".join(mayor_quotes),
        "mayor_word_count": len("\n\n".join(mayor_quotes).split()),
        "has_mayor_quotes": bool(mayor_quotes),
    }


def crawl_html_agency(ag, items, have, probes, budget):
    """Legacy /html strategy: scrape a static index (.shtml) for release links."""
    slug, name = ag["slug"], ag.get("name", ag["slug"])
    res = fetch_redirect(BASE + ag["html_index"])
    probes += 1
    time.sleep(SLEEP)
    if not res:
        print(f"  [{slug}] {name}: index unreachable", file=sys.stderr)
        return 0, probes
    links = set(re.findall(ag["link_re"], res[1]))
    added = 0
    for rel in sorted(links):
        if probes >= budget:
            break
        url = BASE + ag.get("link_base", "/") + rel
        if url in have:
            continue
        r = fetch_redirect(url)
        probes += 1
        time.sleep(SLEEP)
        if not r or r[0] in have:
            continue
        try:
            item = parse_release_dot(r[0], r[1], slug)
        except Exception as e:  # noqa: BLE001
            print(f"  [{slug}] parse error {r[0]}: {e}", file=sys.stderr)
            continue
        if item and item["text"]:
            items.append(item)
            have.add(r[0])
            added += 1
    print(f"  [{slug}] {name}: +{added} (/html)", flush=True)
    return added, probes


def crawl_index_agency(ag, items, have, probes, budget):
    """Index strategy: scrape an agency's press-release index for release links,
    then fetch + parse each with the ls-col-body parser. Returns (added, probes)."""
    slug, name = ag["slug"], ag.get("name", ag["slug"])
    res = fetch_redirect(BASE + ag["index_url"])
    probes += 1
    time.sleep(SLEEP)
    if not res:
        print(f"  [{slug}] {name}: index unreachable", file=sys.stderr)
        return 0, probes
    links = set(re.findall(rf'/site/{slug}/[^"#\s]+?\.page', res[1]))
    rel = []
    for l in links:
        if l == ag["index_url"] or _LS_NAV.search(l):
            continue
        if ag.get("require_2026") and "2026" not in l:
            continue
        rel.append(l)
    added = 0
    for l in sorted(rel):
        if probes >= budget:
            break
        url = BASE + l
        if url in have:
            continue
        r = fetch_redirect(url)
        probes += 1
        time.sleep(SLEEP)
        if not r or r[0] in have:
            continue
        try:
            item = parse_release_ls(r[0], r[1], slug)
        except Exception as e:  # noqa: BLE001
            print(f"  [{slug}] parse error {r[0]}: {e}", file=sys.stderr)
            continue
        if item and item["text"]:
            items.append(item)
            have.add(r[0])
            added += 1
    print(f"  [{slug}] {name}: +{added} (index)", flush=True)
    return added, probes


def main() -> int:
    cfg = json.loads(CONFIG.read_text())
    agencies = cfg.get("agencies", [])
    data = json.loads(CORPUS.read_text())
    items = data["items"]
    have = {it.get("url") for it in items}
    state = data.get("agency_state", {})
    backfill = bool(os.environ.get("AGENCY_BACKFILL"))

    probes = 0
    added = 0
    for ag in agencies:
        slug, fmt, name = ag["slug"], ag["id_format"], ag.get("name", ag["slug"])
        prev_max = 0 if backfill else int(state.get(slug, 0))
        n = max(1, prev_max - 2)        # small overlap to catch late-posted gaps
        gap = 0
        agency_added = 0
        maxid = prev_max
        while gap < GAP_LIMIT and probes < BUDGET:
            rid = fmt.format(n)
            res = fetch_redirect(f"{BASE}/site/{slug}/news/{rid}/x")
            probes += 1
            time.sleep(SLEEP)
            if res is None:
                gap += 1
                n += 1
                continue
            gap = 0
            maxid = max(maxid, n)
            final_url, htmltext = res
            n += 1
            if not final_url or final_url.rstrip("/").endswith("/x") or final_url in have:
                continue
            try:
                item = parse_release(final_url, htmltext, slug)
            except Exception as e:  # noqa: BLE001 — one bad page can't kill the run
                print(f"  [{slug}] parse error {final_url}: {e}", file=sys.stderr)
                continue
            if item and item["text"]:
                items.append(item)          # append at end → indices stay stable
                have.add(final_url)
                added += 1
                agency_added += 1
        state[slug] = maxid
        print(f"  [{slug}] {name}: +{agency_added} (through id #{maxid})", flush=True)
        if probes >= BUDGET:
            print(f"  budget {BUDGET} reached — stopping; resume next run.", file=sys.stderr)
            break

    # Index-strategy agencies (slug-URL newsrooms on the ls-col-body template).
    for ag in cfg.get("index_agencies", []):
        if probes >= BUDGET:
            break
        ad, probes = crawl_index_agency(ag, items, have, probes, BUDGET)
        added += ad

    # Legacy /html agencies (static .shtml index + agency-content body).
    for ag in cfg.get("html_agencies", []):
        if probes >= BUDGET:
            break
        ad, probes = crawl_html_agency(ag, items, have, probes, BUDGET)
        added += ad

    # Always persist advanced state (so re-crawls resume) and recompute counts.
    data["agency_state"] = state
    data["total"] = len(items)
    type_counts: dict[str, int] = {}
    source_counts: dict[str, int] = {}
    for it in items:
        type_counts[it.get("type", "other")] = type_counts.get(it.get("type", "other"), 0) + 1
        source_counts[it.get("source", "nyc.gov")] = source_counts.get(it.get("source", "nyc.gov"), 0) + 1
    data["type_counts"] = type_counts
    data["source_counts"] = source_counts
    if added:
        data["agencies_last_run"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    CORPUS.write_text(json.dumps(data, ensure_ascii=False))

    print(f"Agency releases: added {added}, corpus now {len(items)} items.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
