#!/usr/bin/env python3
"""Scrape NYC City Council hearing transcripts that involve the administration.

Pulls verbatim stenographic hearing transcripts from the Council's Legistar Web
API and adds the ones that mention Mamdani to data/corpus.json as
`type: "hearing"`, `source: "council"`, `reliability: "official"`.

This is a deliberate broadening of scope: hearing transcripts are mostly the
words of *administration commissioners* (and council members), not the Mayor
himself. To keep the archive relevant to its subject, we only ingest a hearing
transcript whose text mentions "Mamdani" — so it surfaces administration
testimony about the Mayor's agenda without dumping unrelated council business.
The Mayor rarely testifies, so these items usually have no "Mayor's words"; the
mayor-only filter correctly skips them.

REQUIREMENTS:
  - LEGISTAR_TOKEN env var. The NYC Legistar API now requires a free token —
    request one at https://council.nyc.gov/legislation/api/ (emailed to you),
    then set it as a GitHub Actions secret. Without it this script is a no-op.
  - pdfminer.six (for PDF text extraction): pip install pdfminer.six

Run: LEGISTAR_TOKEN=... python3 scrape_council.py
"""

from __future__ import annotations

import json
import os
import re
import sys
import time
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import quote
from urllib.request import Request, urlopen

import scrape  # reuse parse_speakers / to_iso

ROOT = Path(__file__).parent
CORPUS = ROOT / "data" / "corpus.json"
API = "https://webapi.legistar.com/v1/nyc"
TOKEN = os.environ.get("LEGISTAR_TOKEN", "").strip()
UA = "Mozilla/5.0 (mamdani-transcript-archive; josh.greenman@gmail.com)"
SLEEP = 0.4
# Re-scan a trailing window each run so late-posted transcripts get picked up.
SCAN_FROM = "2026-01-01"
RELEVANCE = re.compile(r"\bmamdani\b", re.I)
TRANSCRIPT_NAME = re.compile(r"transcript", re.I)


def fetch(url: str) -> bytes:
    req = Request(url, headers={"User-Agent": UA})
    with urlopen(req, timeout=60) as r:
        return r.read()


def api_get(path: str, params: str = "") -> list | dict:
    sep = "&" if params else ""
    url = f"{API}/{path}?token={quote(TOKEN)}{sep}{params}"
    return json.loads(fetch(url).decode("utf-8"))


def list_events() -> list[dict]:
    flt = (f"$filter=EventDate+ge+datetime'{SCAN_FROM}'+and+"
           f"EventDate+lt+datetime'2027-01-01'&$orderby=EventDate+desc&$top=500")
    try:
        return api_get("events", flt)
    except (HTTPError, URLError, OSError) as e:
        print(f"  Legistar events listing failed: {e}", file=sys.stderr)
        return []


def event_transcript_attachments(event_id: int) -> list[dict]:
    """Return [{name, url}] for attachments on an event that look like transcripts."""
    try:
        items = api_get(f"events/{event_id}/eventitems", "Attachments=1")
    except (HTTPError, URLError, OSError) as e:
        print(f"  event {event_id} items failed: {e}", file=sys.stderr)
        return []
    out: list[dict] = []
    for it in items if isinstance(items, list) else []:
        # The expanded attachments array is named EventItemMatterAttachments in
        # current Legistar; older docs call it MatterAttachments. Accept either.
        atts = it.get("EventItemMatterAttachments") or it.get("MatterAttachments") or []
        for att in atts:
            name = att.get("MatterAttachmentName") or ""
            link = att.get("MatterAttachmentHyperlink") or ""
            if name and link and TRANSCRIPT_NAME.search(name):
                out.append({"name": name, "url": link})
    return out


def pdf_to_text(data: bytes) -> str:
    try:
        from io import BytesIO
        from pdfminer.high_level import extract_text
    except ImportError:
        print("  pdfminer.six not installed — cannot extract hearing PDFs.", file=sys.stderr)
        return ""
    try:
        return extract_text(BytesIO(data)) or ""
    except Exception as e:  # noqa: BLE001 — pdfminer raises a zoo of errors
        print(f"  PDF extract failed: {e}", file=sys.stderr)
        return ""


def build_item(event: dict, att: dict, text: str) -> dict:
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text).strip()
    iso = ""
    m = re.match(r"(\d{4}-\d{2}-\d{2})", event.get("EventDate", "") or "")
    if m:
        iso = m.group(1)
    committee = event.get("EventBodyName", "Council hearing")
    title = f"{committee} — {att['name']}"
    speakers = scrape.parse_speakers(text)
    for s in speakers:
        s["is_mayor"] = "mamdani" in s["speaker"].lower() and "mayor" in s["speaker"].lower()
    mayor_bits = [s["text"] for s in speakers if s["is_mayor"]]
    months = ["January", "February", "March", "April", "May", "June", "July",
              "August", "September", "October", "November", "December"]
    pretty = ""
    if iso:
        y, mo, d = iso.split("-")
        pretty = f"{months[int(mo) - 1]} {int(d):02d}, {y}"
    return {
        "link": f"/council/{event['EventId']}",
        "url": att["url"],
        "title": title,
        "date": pretty,
        "iso_date": iso,
        "type": "hearing",
        "source": "council",
        "reliability": "official",
        "text": text,
        "word_count": len(text.split()),
        "speakers": speakers,
        "mayor_quotes": [],
        "mayor_text": "\n\n".join(mayor_bits),
        "mayor_word_count": len("\n\n".join(mayor_bits).split()),
        "has_mayor_quotes": False,
        "committee": committee,
    }


def main() -> int:
    if not TOKEN:
        print("LEGISTAR_TOKEN not set — skipping Council hearings (no-op). "
              "Request a free token at https://council.nyc.gov/legislation/api/ "
              "and set it as a secret to enable this source.")
        return 0
    if not CORPUS.exists():
        print("corpus.json missing; run scrape.py first.", file=sys.stderr)
        return 1
    bundle = json.loads(CORPUS.read_text())
    items = bundle["items"]
    have = {it["link"] for it in items}

    events = list_events()
    print(f"Legistar: {len(events)} events since {SCAN_FROM}.")
    added = 0
    for ev in events:
        link = f"/council/{ev['EventId']}"
        if link in have:
            continue
        atts = event_transcript_attachments(ev["EventId"])
        time.sleep(SLEEP)
        for att in atts:
            try:
                pdf = fetch(att["url"])
            except (HTTPError, URLError, OSError) as e:
                print(f"  download failed {att['url']}: {e}", file=sys.stderr)
                continue
            text = pdf_to_text(pdf)
            if not RELEVANCE.search(text):
                continue  # not about the administration — out of scope
            item = build_item(ev, att, text)
            if item["word_count"] < 200:
                continue
            items.append(item)
            have.add(link)
            added += 1
            print(f"  + [council/official] {item['iso_date']} {item['title'][:70]} "
                  f"({item['word_count']}w)")
            break  # one transcript item per event
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
    bundle["council_last_run"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    CORPUS.write_text(json.dumps(bundle, ensure_ascii=False, indent=1))
    print(f"\nCouncil scrape done: +{added} hearing transcripts. Total {len(items)}.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
