#!/usr/bin/env python3
"""Build data/commitments.json from the model's extractions.

Reads data/commitments_raw.jsonl (written by extract_commitments.py) and keeps
a commitment only if its quote is found word for word in the item it came
from. Matching ignores case, curly-vs-straight quotes, dash style and runs of
whitespace, nothing else; the page shows the passage as it appears in the
source, not as the model copied it. Everything that fails is listed in
data/commitments_rejected.json so it can be audited.

Stdlib only. See METHODOLOGY.md#commitments.
"""
from __future__ import annotations

import json
import re
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

from extract_commitments import (CORPUS, MODEL, RAW, eligible, item_id,
                                 source_text)

ROOT = Path(__file__).resolve().parent
OUT = ROOT / "data" / "commitments.json"
REJECTED = ROOT / "data" / "commitments_rejected.json"
GROUPS = ROOT / "data" / "commitments_groups.json"

TOPIC_LABELS = {
    "housing": "Housing & rent", "transit": "Transit & buses", "safety": "Public safety",
    "immigration": "Immigration", "childcare": "Child care & schools",
    "affordability": "Cost of living", "labor": "Jobs & labor", "health": "Health & food",
    "federal": "Federal & Trump", "albany": "Albany & the state", "budget": "Budget & taxes",
    "climate": "Climate & environment", "government": "City government", "other": "Other",
}

NO_DATE = re.compile(r"[;,.]?\s*\(?(no (date|deadline|timeline|timeframe) (was |is )?(given|stated|specified|set))\)?\.?",
                     re.I)
DUE_RE = re.compile(r"^\d{4}(-\d{2}(-\d{2})?)?$")

FOLD = {}
for ch in "‘’‚‛′`":
    FOLD[ch] = "'"
for ch in "“”„″":
    FOLD[ch] = '"'
for ch in "‐‑‒–—―−":
    FOLD[ch] = "-"
for ch in "     \t\r\n":
    FOLD[ch] = " "


def fold(text: str) -> tuple[str, list[int]]:
    """Normalize text and keep, for every output char, its index in the input."""
    out, idx = [], []
    for i, ch in enumerate(text):
        if ch == "…":
            rep = "..."
        elif ch in ("​", "﻿"):
            continue
        else:
            rep = FOLD.get(ch, ch).lower()
        for r in rep:
            if r == " " and (not out or out[-1] == " "):
                continue
            out.append(r)
            idx.append(i)
    return "".join(out), idx


def find_quote(quote: str, text: str) -> str | None:
    """Return the source passage matching quote, or None."""
    ftext, idx = fold(text)
    q, _ = fold(quote.strip())
    q = q.strip()
    candidates = [q, q.rstrip(".,;:!? "), q.strip("\"' ")]
    for c in candidates:
        if len(c) < 20:
            continue
        pos = ftext.find(c)
        if pos >= 0:
            start, end = idx[pos], idx[pos + len(c) - 1] + 1
            return text[start:end].strip()
    return None


def main() -> int:
    items = {item_id(i): i for i in json.loads(CORPUS.read_text())["items"] if eligible(i)}
    raws = [json.loads(l) for l in RAW.read_text().splitlines() if l.strip()]

    kept, rejected = [], []
    errors = 0
    for rec in raws:
        item = items.get(rec["id"])
        if item is None:
            continue
        if rec.get("commitments") is None:
            errors += 1
            continue
        text = source_text(item)
        for n, c in enumerate(rec["commitments"]):
            passage = find_quote(c["quote"], text)
            if passage is None:
                rejected.append({"item": rec["id"], "url": item.get("url"),
                                 "quote": c["quote"], "summary": c["summary"]})
                continue
            # A worked-out deadline must point at a phrase in the source.
            basis = c["due_basis"]
            if basis == "computed" and not c["due_text"]:
                basis = "none"
            kept.append({
                "id": f"{rec['id']}-{n}",
                "quote": passage,
                "summary": NO_DATE.sub("", c["summary"]).strip(),
                "due": c["due"] if basis != "none" and DUE_RE.match(c["due"] or "") else None,
                "due_text": c["due_text"],
                "due_basis": basis,
                "agency": c["agency"],
                "topic": c["topic"],
                "kind": c["kind"],
                "item": {
                    "id": rec["id"],
                    "title": item.get("title", ""),
                    "date": item["iso_date"],
                    "type": item["type"],
                    "url": item.get("url"),
                    "source": item.get("source"),
                    "reliability": item.get("reliability"),
                },
            })

    # Optional grouping of repeated promises (see group_commitments in
    # extract_commitments.py): {commitment id: group id}.
    g = json.loads(GROUPS.read_text()) if GROUPS.exists() else {}
    groups, routine = g.get("groups", {}), set(g.get("routine", []))
    for c in kept:
        c["group"] = groups.get(c["id"], c["id"])
        c["routine"] = c["group"] in routine

    kept.sort(key=lambda c: (c["item"]["date"], c["id"]), reverse=True)
    n_groups = len({c["group"] for c in kept})
    out = {
        "generated_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "model": MODEL,
        "counts": {
            "items_read": len([r for r in raws if r["id"] in items]),
            "items_errored": errors,
            "items_with_commitments": len({c["item"]["id"] for c in kept}),
            "extracted": len(kept) + len(rejected),
            "verified": len(kept),
            "rejected": len(rejected),
            "distinct": n_groups,
            "distinct_routine": len({c["group"] for c in kept if c["routine"]}),
        },
        "topics": [{"id": k, "label": v, "count": n} for k, v in TOPIC_LABELS.items()
                   if (n := sum(1 for c in kept if c["topic"] == k))],
        "kinds": Counter(c["kind"] for c in kept).most_common(),
        "commitments": kept,
    }
    OUT.write_text(json.dumps(out, ensure_ascii=False, separators=(",", ":")) + "\n")
    REJECTED.write_text(json.dumps(rejected, ensure_ascii=False, indent=1) + "\n")
    print(f"{len(kept)} verified, {len(rejected)} rejected, {errors} items errored, "
          f"{n_groups} distinct -> {OUT.name}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
