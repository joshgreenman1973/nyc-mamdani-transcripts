#!/usr/bin/env python3
"""Extract specific, checkable commitments from the corpus with Claude.

Each eligible item is sent to the model once; the answer is cached in
data/commitments_raw.jsonl keyed by item id, so a re-run only pays for new
items. build_commitments.py then verifies every quote word for word against
the source text and writes the page data.

Modes:
  --pilot N         run N sample items synchronously, print results + cost
  --batch           submit every unprocessed item as one Message Batch (50% off)
  --collect         download a finished batch into the raw cache
  --incremental     run unprocessed items synchronously (the daily refresh)

Needs ANTHROPIC_API_KEY. See METHODOLOGY.md#commitments.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import random
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import anthropic

ROOT = Path(__file__).resolve().parent
CORPUS = ROOT / "data" / "corpus.json"
RAW = ROOT / "data" / "commitments_raw.jsonl"
BATCH_STATE = ROOT / "data" / "commitments_batch.json"

MODEL = "claude-sonnet-5-5"
EFFORT = "medium"
MAX_TOKENS = 16000

# Spoken items: only the mayor's own turns count. Written items: the whole
# text is the administration's (quotes from outsiders are excluded by prompt).
SPOKEN = {"press_conference", "media_appearance", "speech", "ceremony"}
WRITTEN = {"statement", "other", "executive_order", "op_ed"}
# Left out on purpose: agency_release (agency, not City Hall), crime_briefing
# (statistics), video (captions are not split by speaker, so the mayor's words
# can't be told from anyone else's).

TOPICS = ["housing", "transit", "safety", "immigration", "childcare",
          "affordability", "labor", "health", "federal", "albany", "budget",
          "climate", "government", "other"]
KINDS = ["program or service", "construction or capital", "rule or policy",
         "staffing", "funding", "report or review", "legislation", "other"]

SYSTEM = f"""You read one item from the public record of New York City Mayor Zohran Mamdani's administration and list the commitments in it. The item is a transcript of the mayor's own remarks, a City Hall press release, a mayoral statement or an executive order.

A commitment is a statement that the city will do a specific thing in the future, specific enough that someone could later check whether it happened. It needs a concrete deliverable (a program launches, a rule takes effect, a facility opens, a number of homes, hires, miles, seats or dollars, a report is issued, a proposal is withdrawn). A date, number or named place makes it stronger but is not required, as long as a person could later verify whether it happened.

Include:
- Promises with a deadline ("by June," "this fall," "within 90 days," "by 2030").
- Quantified targets ("200,000 homes," "hire 500 counselors").
- Executive-order directives that require an agency to act or report by a date.
- Announced projects with a stated start or completion date.
- The forward-looking part of an announcement ("the first site opened today; two more will open next spring" yields the two sites).

Exclude:
- Goals, values and aspirations with no checkable deliverable ("make the city affordable," "fight for working families").
- Anything already done at the time of the item, including rules or orders that take effect immediately on signing. Do include anything such an order requires to happen later (a report due in 90 days, a retrofit by 2029).
- Promises by anyone outside the administration: council members, advocates, union leaders, reporters, callers, state or federal officials. In transcripts you are given only the mayor's own words.
- Outcomes that depend on another government acting, unless the city commits to its own step ("we will send the plan to Albany by March" counts; "if Albany passes it, buses will be free" does not).
- Hypotheticals, questions, and descriptions of other people's plans.
- Event listings, office hours, festival dates, routine service notices and enrollment reminders.

List each commitment once per item, using its clearest passage. Most items contain none or a few. Do not pad.

Fields:
- quote: the passage that states the commitment, copied EXACTLY from the text in its original language: same words, spelling, capitalization and punctuation, one or two consecutive sentences. No ellipses, brackets, translation, edits or added words. If you cannot copy an exact passage, leave the commitment out.
- summary: plain English (even when the quote is not in English), 25 words or fewer, saying who will do what and by when. Name the agency or say "the city." No praise words.
- due: the deadline as YYYY, YYYY-MM or YYYY-MM-DD, or null if no time is given. Resolve relative phrases against the item's date: "by the end of the year" in an item dated 2026-03-04 is 2026-12; "within 90 days" is the item date plus 90 days; a season means its last month (spring 06, summer 09, fall 12, winter 03 of the following year); "next year" is the following year.
- due_text: the time phrase as written in the text, or null.
- due_basis: "stated" if the text gives the date, month or year itself; "computed" if you resolved a relative phrase; "none" if due is null.
- agency: the lead city agency if named, else null.
- topic: one of {", ".join(TOPICS)}.
- kind: one of {", ".join(KINDS)}."""

SCHEMA = {
    "type": "object",
    "properties": {
        "commitments": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "quote": {"type": "string"},
                    "summary": {"type": "string"},
                    "due": {"type": ["string", "null"]},
                    "due_text": {"type": ["string", "null"]},
                    "due_basis": {"type": "string", "enum": ["stated", "computed", "none"]},
                    "agency": {"type": ["string", "null"]},
                    "topic": {"type": "string", "enum": TOPICS},
                    "kind": {"type": "string", "enum": KINDS},
                },
                "required": ["quote", "summary", "due", "due_text", "due_basis",
                             "agency", "topic", "kind"],
                "additionalProperties": False,
            },
        }
    },
    "required": ["commitments"],
    "additionalProperties": False,
}

# $ per million tokens, Sonnet 5.5 (Batch API is half).
PRICE_IN, PRICE_OUT, PRICE_CACHE_READ, PRICE_CACHE_WRITE = 2.00, 10.00, 0.20, 2.50


def item_id(item: dict) -> str:
    key = item.get("url") or item.get("link") or (item.get("title", "") + item.get("iso_date", ""))
    return hashlib.sha1(key.encode()).hexdigest()[:12]


def source_text(item: dict) -> str:
    """The text the model reads and the quote verifier checks against."""
    if item["type"] in SPOKEN:
        return item.get("mayor_text") or ""
    return item.get("text") or ""


def eligible(item: dict) -> bool:
    if item.get("reliability") == "auto":
        return False
    if item["type"] not in SPOKEN | WRITTEN:
        return False
    return len(source_text(item).split()) >= 40


def load_corpus() -> list[dict]:
    return json.loads(CORPUS.read_text())["items"]


def load_raw() -> dict[str, dict]:
    done = {}
    if RAW.exists():
        for line in RAW.read_text().splitlines():
            if line.strip():
                rec = json.loads(line)
                done[rec["id"]] = rec
    return done


def append_raw(records: list[dict]) -> None:
    with RAW.open("a") as f:
        for rec in records:
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")


def params_for(item: dict) -> dict:
    label = {"press_conference": "press conference transcript (mayor's turns only)",
             "media_appearance": "interview transcript (mayor's turns only)",
             "speech": "speech transcript (mayor's turns only)",
             "ceremony": "ceremony transcript (mayor's turns only)",
             "statement": "mayoral statement",
             "other": "City Hall press release",
             "executive_order": "executive order",
             "op_ed": "op-ed by the mayor"}[item["type"]]
    header = (f"Item date: {item['iso_date']}\nItem type: {label}\n"
              f"Title: {item.get('title', '')}\n\nText:\n")
    return {
        "model": MODEL,
        "max_tokens": MAX_TOKENS,
        "system": [{"type": "text", "text": SYSTEM, "cache_control": {"type": "ephemeral"}}],
        "messages": [{"role": "user", "content": header + source_text(item)}],
        "output_config": {"effort": EFFORT, "format": {"type": "json_schema", "schema": SCHEMA}},
    }


def record_from_message(item: dict, msg, batch: bool) -> dict:
    rec = {
        "id": item_id(item),
        "url": item.get("url"),
        "iso_date": item["iso_date"],
        "model": MODEL,
        "extracted_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "batch": batch,
        "stop_reason": msg.stop_reason,
        "usage": {
            "input": msg.usage.input_tokens,
            "output": msg.usage.output_tokens,
            "cache_read": getattr(msg.usage, "cache_read_input_tokens", 0) or 0,
            "cache_write": getattr(msg.usage, "cache_creation_input_tokens", 0) or 0,
        },
    }
    if msg.stop_reason != "end_turn":
        rec["commitments"] = None
        rec["error"] = f"stop_reason={msg.stop_reason}"
        return rec
    text = next((b.text for b in msg.content if b.type == "text"), "")
    try:
        rec["commitments"] = json.loads(text)["commitments"]
    except (ValueError, KeyError) as e:
        rec["commitments"] = None
        rec["error"] = f"unparseable: {e}"
    return rec


def cost(records: list[dict], batch: bool) -> float:
    total = 0.0
    for r in records:
        u = r["usage"]
        total += (u["input"] * PRICE_IN + u["output"] * PRICE_OUT
                  + u["cache_read"] * PRICE_CACHE_READ + u["cache_write"] * PRICE_CACHE_WRITE) / 1e6
    return total / 2 if batch else total


def run_sync(client, items: list[dict], save: bool) -> list[dict]:
    out = []
    for n, item in enumerate(items, 1):
        msg = client.messages.create(**params_for(item))
        rec = record_from_message(item, msg, batch=False)
        out.append(rec)
        found = len(rec["commitments"] or [])
        print(f"[{n}/{len(items)}] {item['iso_date']} {item['type']:17} {found} found  "
              f"in={rec['usage']['input']} out={rec['usage']['output']}  {item['title'][:60]}",
              file=sys.stderr)
        if save:
            append_raw([rec])
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument("--pilot", type=int)
    g.add_argument("--batch", action="store_true")
    g.add_argument("--collect", action="store_true")
    g.add_argument("--incremental", action="store_true")
    ap.add_argument("--max-items", type=int, default=60,
                    help="cap for --incremental so a scraper glitch can't run up a bill")
    args = ap.parse_args()

    if not os.environ.get("ANTHROPIC_API_KEY"):
        print("ANTHROPIC_API_KEY not set; skipping commitment extraction.", file=sys.stderr)
        return 0 if args.incremental else 1
    client = anthropic.Anthropic()

    corpus = [i for i in load_corpus() if eligible(i)]
    done = load_raw()
    todo = [i for i in corpus if item_id(i) not in done]
    print(f"{len(corpus)} eligible items, {len(done)} already extracted, {len(todo)} to do",
          file=sys.stderr)

    if args.pilot:
        rng = random.Random(7)
        by_type: dict[str, list] = {}
        for i in todo:
            by_type.setdefault(i["type"], []).append(i)
        sample = []
        while len(sample) < args.pilot and any(by_type.values()):
            for t in sorted(by_type):
                if by_type[t] and len(sample) < args.pilot:
                    sample.append(by_type[t].pop(rng.randrange(len(by_type[t]))))
        recs = run_sync(client, sample, save=False)
        print(json.dumps(recs, indent=1, ensure_ascii=False))
        c = cost(recs, batch=False)
        words = sum(len(source_text(i).split()) for i in sample)
        all_words = sum(len(source_text(i).split()) for i in todo)
        print(f"\npilot: ${c:.4f} for {len(sample)} items ({words} words); "
              f"at batch price the {len(todo)} remaining items (~{all_words} words) "
              f"project to ~${c / 2 * all_words / max(words, 1):.2f}", file=sys.stderr)
        return 0

    if args.batch:
        if BATCH_STATE.exists() and json.loads(BATCH_STATE.read_text()).get("status") != "collected":
            print("A batch is already pending; run --collect first.", file=sys.stderr)
            return 1
        reqs = [{"custom_id": item_id(i), "params": params_for(i)} for i in todo]
        if not reqs:
            print("Nothing to do.", file=sys.stderr)
            return 0
        b = client.messages.batches.create(requests=reqs)
        BATCH_STATE.write_text(json.dumps({"batch_id": b.id, "count": len(reqs),
                                           "submitted_at": datetime.now(timezone.utc).isoformat(),
                                           "status": "submitted"}, indent=1) + "\n")
        print(f"Submitted batch {b.id} with {len(reqs)} requests.", file=sys.stderr)
        return 0

    if args.collect:
        state = json.loads(BATCH_STATE.read_text())
        b = client.messages.batches.retrieve(state["batch_id"])
        if b.processing_status != "ended":
            print(f"Batch {b.id} still {b.processing_status}: {b.request_counts}", file=sys.stderr)
            return 2
        by_id = {item_id(i): i for i in corpus}
        recs, failed = [], []
        for r in client.messages.batches.results(b.id):
            item = by_id.get(r.custom_id)
            if item is None:
                continue
            if r.result.type == "succeeded":
                recs.append(record_from_message(item, r.result.message, batch=True))
            else:
                failed.append(r.custom_id)
        recs = [r for r in recs if r["id"] not in done]
        append_raw(recs)
        state.update(status="collected", collected=len(recs), failed=failed,
                     cost_usd=round(cost(recs, batch=True), 4))
        BATCH_STATE.write_text(json.dumps(state, indent=1) + "\n")
        print(f"Collected {len(recs)} results, {len(failed)} failed; "
              f"cost ${state['cost_usd']:.2f}", file=sys.stderr)
        return 0

    if args.incremental:
        if len(todo) > args.max_items:
            print(f"{len(todo)} items exceed --max-items {args.max_items}; doing the newest "
                  f"{args.max_items}. Run --batch for a backlog.", file=sys.stderr)
            todo = sorted(todo, key=lambda i: i["iso_date"], reverse=True)[: args.max_items]
        recs = run_sync(client, todo, save=True)
        print(f"incremental: {len(recs)} items, ${cost(recs, batch=False):.4f}", file=sys.stderr)
        return 0
    return 0


if __name__ == "__main__":
    sys.exit(main())
