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
# Override with COUNCIL_SCAN_FROM (YYYY-MM-DD) — handy for quick test runs.
SCAN_FROM = os.environ.get("COUNCIL_SCAN_FROM", "2026-01-01")
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
    """Return [{id, name, url}] for transcript attachments on an event.

    Excludes "Stated Meeting" transcripts — those are the Council's own
    legislative voting sessions (council members, not administration testimony),
    and they're cross-linked to every committee's matter, so they'd flood the
    archive with dozens of copies of one document.
    """
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
            aid = att.get("MatterAttachmentId")
            if not (name and link and aid and TRANSCRIPT_NAME.search(name)):
                continue
            if "stated meeting" in name.lower():
                continue
            out.append({"id": aid, "name": name, "url": link})
    return out


def _ensure_pdfminer():
    """Import pdfminer's extract_text, installing pdfminer.six on the fly if
    needed. Self-installing avoids requiring a workflow-file edit (which needs an
    OAuth `workflow` scope we don't have) just to add a pip dependency."""
    try:
        from pdfminer.high_level import extract_text
        return extract_text
    except ImportError:
        pass
    try:
        import subprocess
        print("  installing pdfminer.six …", file=sys.stderr)
        subprocess.run([sys.executable, "-m", "pip", "install", "--quiet", "pdfminer.six"],
                       check=False, timeout=300)
        from pdfminer.high_level import extract_text
        return extract_text
    except Exception as e:  # noqa: BLE001
        print(f"  pdfminer.six unavailable — cannot extract hearing PDFs: {e}", file=sys.stderr)
        return None


def pdf_to_text(data: bytes) -> str:
    extract_text = _ensure_pdfminer()
    if extract_text is None:
        return ""
    try:
        from io import BytesIO
        return extract_text(BytesIO(data)) or ""
    except Exception as e:  # noqa: BLE001 — pdfminer raises a zoo of errors
        print(f"  PDF extract failed: {e}", file=sys.stderr)
        return ""


# Administration testimony: a commissioner (or deputy) appears AND someone
# testifies. This targets oversight hearings where the Mayor's agencies are
# questioned — what we actually want — and excludes bill markups, land-use
# items, and procedural hearings with no agency witness.
COMMISSIONER_RE = re.compile(r"\bcommissioner\b", re.I)
TESTIFY_RE = re.compile(r"\btestif(?:y|ies|ied|ying|ony)\b", re.I)
MONTHS = ["January", "February", "March", "April", "May", "June", "July",
          "August", "September", "October", "November", "December"]


def has_admin_testimony(text: str) -> bool:
    return len(COMMISSIONER_RE.findall(text)) >= 5 and bool(TESTIFY_RE.search(text))


def _sig(text: str) -> str:
    """Content signature for dedup: word count + hash of normalized text.
    Catches the same hearing uploaded under several committees as distinct files."""
    import hashlib
    norm = re.sub(r"\s+", " ", text).strip().lower()
    return f"{len(norm.split())}:{hashlib.sha1(norm.encode('utf-8', 'replace')).hexdigest()}"


# Hearing transcripts run 30k–90k words. Storing them whole (plus speaker splits)
# bloats the browser-downloaded corpus.json into the tens of MB. We store a
# substantial opening excerpt — which holds the witnesses' prepared testimony and
# the early Q&A, i.e. the administration's actual answers — and link the full
# verbatim PDF for the rest.
EXCERPT_WORDS = 6000


def build_item(aid, committee: str, iso: str, name: str, url: str, text: str) -> dict:
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text).strip()
    full_words = len(text.split())
    is_excerpt = full_words > EXCERPT_WORDS
    if is_excerpt:
        text = " ".join(text.split()[:EXCERPT_WORDS])
    title = f"{committee} — {name}"
    pretty = ""
    if iso:
        y, mo, d = iso.split("-")
        pretty = f"{MONTHS[int(mo) - 1]} {int(d):02d}, {y}"
    return {
        "link": f"/council/{aid}",
        "url": url,
        "title": title,
        "date": pretty,
        "iso_date": iso,
        "type": "hearing",
        "source": "council",
        "reliability": "official",
        "text": text,
        "word_count": len(text.split()),
        "full_word_count": full_words,
        "is_excerpt": is_excerpt,
        # The Mayor doesn't testify at these; keep them out of "Mayor's words"
        # and skip the speaker split (it would re-duplicate the excerpt text).
        "speakers": [],
        "mayor_quotes": [],
        "mayor_text": "",
        "mayor_word_count": 0,
        "has_mayor_quotes": False,
        "committee": committee,
    }


# Cap new hearings per run so a first run can't dump hundreds at once; if hit,
# we log it (no silent truncation) and the next run picks up where this left off.
MAX_NEW_PER_RUN = 40


def main() -> int:
    if not TOKEN:
        msg = ("LEGISTAR_TOKEN not set — Council hearings not scraped. "
               "Request a free token at https://council.nyc.gov/legislation/api/ "
               "and set it as a secret to enable this source.")
        # Locally this is a fine no-op: most runs of scrape.py don't want it.
        # In CI it is a broken source pretending to be a quiet one. The secret
        # was set in June but never passed into the workflow step, so this
        # printed a cheerful skip twice a day for three months while the last
        # hearing in the corpus stayed at 2026-05-13. A scraper that cannot
        # distinguish "nothing new" from "not running" has to go red.
        if os.environ.get("GITHUB_ACTIONS"):
            print(f"::error::{msg}", file=sys.stderr)
            return 1
        print(msg)
        return 0
    if not CORPUS.exists():
        print("corpus.json missing; run scrape.py first.", file=sys.stderr)
        return 1
    bundle = json.loads(CORPUS.read_text())
    items = bundle["items"]
    have = {it["link"] for it in items}

    events = list_events()
    print(f"Legistar: {len(events)} events since {SCAN_FROM}.")

    # Pass 1: map each transcript FILE to the distinct events that reference it.
    # A genuine single-committee hearing transcript is referenced by exactly one
    # event; files cross-linked to many events are omnibus/stated documents.
    file_refs: dict = {}
    for ev in events:
        for att in event_transcript_attachments(ev["EventId"]):
            ref = file_refs.setdefault(att["id"], {"name": att["name"], "url": att["url"], "events": {}})
            iso = (re.match(r"(\d{4}-\d{2}-\d{2})", ev.get("EventDate", "") or "") or [None, ""])[1]
            ref["events"][ev["EventId"]] = (ev.get("EventBodyName", "Council hearing"), iso)
        time.sleep(SLEEP)

    single = [(aid, r) for aid, r in file_refs.items() if len(r["events"]) == 1]
    multi = len(file_refs) - len(single)
    # Newest hearings first, so the per-run cap keeps the most recent.
    single.sort(key=lambda kr: next(iter(kr[1]["events"].values()))[1], reverse=True)
    print(f"  {len(file_refs)} transcript files; {len(single)} single-committee, "
          f"{multi} cross-linked (skipped).")

    # Content signatures of transcripts already in the corpus, so a joint hearing
    # uploaded separately under each committee (identical text, different file id)
    # isn't ingested twice.
    seen_sig = {_sig(it.get("text", "")) for it in items if it.get("source") == "council"}

    # Pass 2: download each unique single-committee transcript once, keep those
    # with administration testimony and not a content-duplicate.
    added = 0
    capped = False
    for aid, ref in single:
        link = f"/council/{aid}"
        if link in have:
            continue
        if added >= MAX_NEW_PER_RUN:
            capped = True
            break
        committee, iso = next(iter(ref["events"].values()))
        try:
            pdf = fetch(ref["url"])
        except (HTTPError, URLError, OSError) as e:
            print(f"  download failed {ref['url']}: {e}", file=sys.stderr)
            continue
        time.sleep(SLEEP)
        text = pdf_to_text(pdf)
        if len(text.split()) < 200:
            continue
        if not has_admin_testimony(text):
            continue  # no agency commissioner testimony — not our target
        sig = _sig(text)
        if sig in seen_sig:
            print(f"  ~ dup (joint hearing already kept): {committee[:40]}", file=sys.stderr)
            continue
        seen_sig.add(sig)
        item = build_item(aid, committee, iso, ref["name"], ref["url"], text)
        items.append(item)
        have.add(link)
        added += 1
        print(f"  + [council/official] {item['iso_date'] or '????-??-??'} "
              f"{item['title'][:70]} ({item['word_count']}w)")
    if capped:
        print(f"  (hit per-run cap of {MAX_NEW_PER_RUN}; remaining hearings ingest next run.)")

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
