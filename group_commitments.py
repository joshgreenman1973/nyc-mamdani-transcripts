#!/usr/bin/env python3
"""Group repeated commitments and mark routine ones.

The mayor makes the same promise many times. For each theme, the model gets
the verified commitments (id, date, summary, due date) and returns groups of
ids that promise the same deliverable, and marks each group as routine or
not (routine items are hidden by default on the page, not deleted). Every id
must come back exactly once;
anything missing or duplicated is put in a group of its own, so a bad answer
can only leave repeats unmerged, never drop a commitment.

Output: data/commitments_groups.json, {"groups": {commitment id: group id},
"routine": [group ids]}. A theme is
re-sent only when its set of commitments changes. Run build_commitments.py
before and after (it reads the groups file). Needs ANTHROPIC_API_KEY.
"""
from __future__ import annotations

import hashlib
import json
import os
import sys
from pathlib import Path

import anthropic

ROOT = Path(__file__).resolve().parent
LEDGER = ROOT / "data" / "commitments.json"
GROUPS = ROOT / "data" / "commitments_groups.json"
CACHE = ROOT / "data" / "commitments_groups_cache.json"

MODEL = "claude-sonnet-5-5"

SYSTEM = """You are given commitments made by New York City Mayor Zohran Mamdani's administration, all on one theme. Each line has an id, the date it was said, a one-sentence summary and its stated deadline.

Group together the ids that promise the same deliverable: the same program, project, rule, facility or numeric target, even when worded differently, said on different dates or given different deadlines. Do not group commitments that are only related (two different bus routes, two different housing sites, a pilot and its later expansion with a different scope). When unsure, keep them apart.

Return every id exactly once. A commitment with no match is a group of one.

Then mark each group routine (true) or not (false). Routine means short-term operations or logistics that nobody would track as a policy promise: steps during a specific storm, heat wave or emergency; parades, celebrations, festivals and other events; application windows and enrollment deadlines; procedural steps such as a rule's comment period; promises to share information or follow up later; one-day giveaways. Not routine: programs and services, rules and policies, capital projects, numeric targets, funding, staffing, legislation, reports and reviews an order requires, and anything with a deadline weeks or more away that someone could check. When unsure, mark it not routine."""

SCHEMA = {
    "type": "object",
    "properties": {
        "groups": {"type": "array", "items": {
            "type": "object",
            "properties": {
                "ids": {"type": "array", "items": {"type": "string"}},
                "routine": {"type": "boolean"},
            },
            "required": ["ids", "routine"],
            "additionalProperties": False,
        }},
    },
    "required": ["groups"],
    "additionalProperties": False,
}


def main() -> int:
    if not os.environ.get("ANTHROPIC_API_KEY"):
        print("ANTHROPIC_API_KEY not set; skipping grouping.", file=sys.stderr)
        return 0
    client = anthropic.Anthropic()
    ledger = json.loads(LEDGER.read_text())["commitments"]
    cache = json.loads(CACHE.read_text()) if CACHE.exists() else {}
    groups: dict[str, str] = {}
    routine: set[str] = set()
    spent = 0.0

    by_topic: dict[str, list] = {}
    for c in ledger:
        by_topic.setdefault(c["topic"], []).append(c)

    for topic, items in sorted(by_topic.items()):
        items.sort(key=lambda c: (c["item"]["date"], c["id"]))
        ids = [c["id"] for c in items]
        key = hashlib.sha1(json.dumps(ids).encode()).hexdigest()
        if cache.get(topic, {}).get("key") == key:
            topic_groups = cache[topic]["groups"]
            topic_routine = cache[topic]["routine"]
        else:
            lines = "\n".join(f'{c["id"]} | {c["item"]["date"]} | {c["summary"]} | due: {c["due"] or "none"}'
                              for c in items)
            with client.messages.stream(
                model=MODEL,
                max_tokens=32000,
                system=SYSTEM,
                messages=[{"role": "user", "content": f"Theme: {topic}\n\n{lines}"}],
                output_config={"effort": "medium", "format": {"type": "json_schema", "schema": SCHEMA}},
            ) as stream:
                msg = stream.get_final_message()
            spent += (msg.usage.input_tokens * 2 + msg.usage.output_tokens * 10) / 1e6
            raw = []
            if msg.stop_reason == "end_turn":
                text = next((b.text for b in msg.content if b.type == "text"), "")
                raw = json.loads(text).get("groups", [])
            else:
                print(f"  {topic}: stop_reason={msg.stop_reason}; leaving ungrouped", file=sys.stderr)
            # Enforce: each id exactly once; unknown ids ignored.
            valid, seen, topic_groups, topic_routine = set(ids), set(), [], []
            for g in raw:
                members = [i for i in g["ids"] if i in valid and i not in seen]
                seen.update(members)
                if members:
                    topic_groups.append(members)
                    if g["routine"]:
                        topic_routine.append(sorted(members)[0])
            topic_groups += [[i] for i in ids if i not in seen]
            cache[topic] = {"key": key, "groups": topic_groups, "routine": topic_routine}
            merged = sum(1 for g in topic_groups if len(g) > 1)
            print(f"  {topic}: {len(ids)} commitments -> {len(topic_groups)} groups ({merged} merged, "
                  f"{len(topic_routine)} routine)", file=sys.stderr)
        for g in topic_groups:
            lead = sorted(g)[0]
            for i in g:
                groups[i] = lead
        routine.update(topic_routine)

    GROUPS.write_text(json.dumps({"groups": groups, "routine": sorted(routine)},
                                 indent=0, sort_keys=True) + "\n")
    CACHE.write_text(json.dumps(cache, indent=0) + "\n")
    print(f"grouping: {len(groups)} commitments, {len(set(groups.values()))} distinct, "
          f"{len(routine)} routine, ~${spent:.3f}",
          file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
