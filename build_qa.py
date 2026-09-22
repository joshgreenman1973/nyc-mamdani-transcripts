#!/usr/bin/env python3
"""Build data/qa.json — every press question put to Mayor Mamdani at an
officially transcribed event, paired with the answers that followed.

Source: data/corpus.json (written by scrape.py). Stdlib only, no network.

Scope
-----
* Only items with reliability == "official" — transcripts the Mayor's Office
  publishes on nyc.gov. Outside transcripts (NPR, WNYC, C-SPAN) and YouTube
  auto-captions are left out.
* Event types that carry Q&A: press conferences, media appearances
  (interviews), and speeches/ceremonies that end in a press gaggle.

How an exchange is cut
----------------------
Official transcripts label reporters "Question:" (or "Livestream Question:")
at press events; in interviews the host appears under their surname. We walk
each transcript's speaker turns:

* A question turn opens an exchange. Consecutive question turns (crosstalk,
  "two questions" split across lines) are merged into one question.
* Every following non-question turn — the mayor, a deputy mayor, a
  commissioner — belongs to that exchange's answer, until the next question.
* Turns before the first question (opening remarks) are not exchanges.

Each exchange records who answered. The front end defaults to exchanges the
mayor answered himself and lets readers include ones handled only by other
officials.

Known limits (also in METHODOLOGY.md)
-------------------------------------
* Official transcripts do not name reporters or their outlets; they appear
  only as "Question." (We tried extracting self-identifications like "Jane
  Doe from the Daily News" — they occur in well under 1% of questions, too
  few to be worth a filter.)
* Who asked: "reporter" (a "Question:" at a press event), "host" (the
  interviewer on a broadcast) or "public" (callers, town-hall audience,
  other guests, and the non-journalist hosts of City Hall's own livestreams
  and forums, plus the viewer questions they relay). In interviews this is inferred — when one host clearly
  dominates, voices heard only once or twice are treated as callers/guests.
  It can misfire on shows with rotating co-hosts.
* A reporter's follow-up is its own exchange; the front end shows neighbouring
  exchanges from the same event for context.
"""
from __future__ import annotations

import ast
import json
import re
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parent
CORPUS = ROOT / "data" / "corpus.json"
TOPICS = ROOT / "data" / "topics.json"
OUT = ROOT / "data" / "qa.json"

QA_TYPES = {"press_conference", "media_appearance", "speech", "ceremony"}

QUESTION_RE = re.compile(r"^(livestream\s+)?(question|q|reporter)\b", re.I)
# Labels after which the transcript is no longer the event (appended release).
STOP_RE = re.compile(r"^(press release|###|media contact)", re.I)
# Non-press voices in broadcasts: audience members, jingles, list headings the
# scraper read as labels.
PUBLIC_RE = re.compile(r"^(attendee|audience member|caller|resident|student|participant)\b", re.I)
NOT_PERSON_RE = re.compile(r"\b(service|preparation|preparers|tax|jingle|everyone|all)\b", re.I)
# Labels that are neither side of an exchange.
NEUTRAL_RE = re.compile(r"^(crowd|audience|translation|translator|interpreter|unknown|"
                        r"unidentified|multiple speakers|crosstalk|video|music|"
                        r"moderator|announcer)\b", re.I)
# Titles that mark a government / institutional speaker (a responder, not a
# reporter) — matters in interviews, where any non-mayor voice would
# otherwise be read as the host.
OFFICIAL_RE = re.compile(
    r"\b(mayor|governor|commissioner|deputy|chancellor|council|counsel|comptroller|"
    r"advocate|borough president|director|chief|senator|assembly|secretary|"
    r"president|chair|administrator|sheriff|first lady|press secretary|"
    r"superintendent|executive|lieutenant|attorney general|speaker|dr\.?|"
    r"rabbi|reverend|pastor|imam|bishop|captain|inspector)\b",
    re.I,
)


def is_mayor(label: str) -> bool:
    n = label.strip().lower()
    return "mamdani" in n and "rama" not in n and "duwaji" not in n


def plausible_label(label: str) -> bool:
    """False for fragments the scraper mis-read as speaker labels, e.g.
    "Today, that crew is here" (a sentence that happened to end in a colon)."""
    words = label.replace("[", "").replace("]", "").split()
    if not words:
        return False
    if is_mayor(label) or QUESTION_RE.match(label) or NEUTRAL_RE.match(label):
        return True
    if OFFICIAL_RE.search(label) and len(words) <= 14:
        return True
    stop = {"of", "and", "the", "for", "de", "la", "van", "von", "da", "on", "&", "at", "to", "in"}
    content = [w for w in words if w.lower() not in stop]
    lower = [w for w in content if w[:1].islower()]
    if lower:
        return False
    # "Name, Title, Organization" labels run long; plain sentences don't
    # survive the all-capitalized test above.
    return len(words) <= (16 if "," in label else 6)


def load_speakers(item) -> list[dict]:
    sp = item.get("speakers") or []
    if isinstance(sp, str):
        sp = ast.literal_eval(sp) if sp.strip() else []
    # Fold mis-read labels back into the previous turn.
    turns: list[dict] = []
    for s in sp:
        label = (s.get("speaker") or "").strip()
        text = (s.get("text") or "").strip()
        if STOP_RE.match(label):
            break
        # "###" ends a City Hall release. Anything after it is not the event —
        # sometimes it's a forwarded email carrying a second copy of the whole
        # transcript, which would otherwise double every exchange.
        end = re.search(r"(?:^|\n)\s*###", text)
        if end:
            text = text[: end.start()].strip()
        if turns and not plausible_label(label):
            turns[-1]["text"] += f"\n\n{label}: {text}"
        elif text:
            turns.append({"speaker": label, "text": text})
        if end:
            break
    return turns


def moderators(turns) -> dict:
    """Untitled voices that carry an event's conversation with the mayor —
    3+ turns, at least 60% of them answered directly by him. Returns
    {label: turn count}. Catches broadcast hosts on items the scraper typed as
    press conferences ("Mayor Mamdani on Bloomberg TV") and the hosts of City
    Hall's own "Talk With the People" livestreams and forums."""
    seen = {}
    for i, t in enumerate(turns[:-1]):
        l = t["speaker"]
        if is_mayor(l) or QUESTION_RE.match(l) or PUBLIC_RE.match(l) or OFFICIAL_RE.search(l) or NEUTRAL_RE.match(l):
            continue
        n, m = seen.get(l, (0, 0))
        seen[l] = (n + 1, m + (1 if is_mayor(turns[i + 1]["speaker"]) else 0))
    return {l: n for l, (n, m) in seen.items() if n >= 3 and m / n >= 0.6}


# Titles of press-typed items that are really broadcast hits.
BROADCAST_TITLE_RE = re.compile(
    r"\b(live on|calls into)\b|\bon\b.*\b(tv|fm|am|wins|radio|network|fox|ny1|pix|wbls|wcbs|wfan|"
    r"bloomberg|weather channel|cnn|msnbc|ms now|cbs|nbc|abc|npr|wnyc|podcast)\b",
    re.I,
)


def role_of(label: str, item_type: str) -> str:
    """'mayor' | 'question' | 'official' | 'neutral'"""
    if is_mayor(label):
        return "mayor"
    if QUESTION_RE.match(label) or PUBLIC_RE.match(label):
        return "question"
    if NEUTRAL_RE.match(label) or NOT_PERSON_RE.search(label):
        return "neutral"
    if item_type == "interview":
        # In an interview every non-mayor, non-official voice is the host
        # (or a caller) putting something to the mayor.
        return "official" if OFFICIAL_RE.search(label) else "question"
    return "official"


def surname(label: str) -> str:
    return label.replace("[", "").replace("]", "").split()[-1].lower()


def asker_kinds(turns, roles, kind: str) -> dict:
    """Map each questioner label to 'reporter' | 'host' | 'public'.

    Press events: "Question" = a reporter. Interviews: the host(s) are the
    voices that carry the conversation; when one host clearly dominates
    (10+ turns), voices heard only once or twice, and "Question" labels, are
    callers, audience members or other guests."""
    labels = [t["speaker"] for t, r in zip(turns, roles) if r == "question"]
    out = {}
    if kind == "press":
        for l in labels:
            out[l] = ("public" if PUBLIC_RE.match(l) else
                      "reporter" if QUESTION_RE.match(l) else "host")
        return out
    groups = Counter(surname(l) for l in labels if not QUESTION_RE.match(l) and not PUBLIC_RE.match(l))
    dominant = max(groups.values()) if groups else 0
    for l in labels:
        if PUBLIC_RE.match(l):
            out[l] = "public"
        elif QUESTION_RE.match(l):
            out[l] = "public" if dominant >= 10 else "host"
        elif dominant >= 10 and groups[surname(l)] <= 2:
            out[l] = "public"
        else:
            out[l] = "host"
    return out


def clean(text: str) -> str:
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    text = re.sub(r"[ \t  ]+", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def display_speaker(label: str) -> str:
    if is_mayor(label):
        return "Mayor Mamdani"
    return label


# ---- program name for interviews ---------------------------------------
PROGRAM_RE = re.compile(
    r"(?:appears?|joins?|joined|interviewed|interview|speaks?|sits? down|live)\s+"
    r"(?:on|with|in)\s+(?:the\s+)?(.+?)(?:\s+(?:to|for|about|and)\s+|$)",
    re.I,
)


def program_name(title: str) -> str | None:
    t = re.sub(r"^Transcript:\s*", "", title).strip()
    m = PROGRAM_RE.search(t)
    if not m:
        return None
    name = m.group(1).strip(" .,:;\"“”'’")
    name = re.sub(r"[’']s\s+[\"“].*$", "", name)
    return name[:80] or None


# ---- topic tagging -------------------------------------------------------
# The Trends view's lexicon (data/topics.json), matched the way
# build_topics.mjs matches it, plus two Q&A-only themes that dominate press
# questions but aren't policy areas in the Trends chart.
EXTRA_TOPICS = [
    {"id": "mideast", "label": "Israel, Gaza & antisemitism",
     "terms": ["Israel", "Israeli", "Gaza", "Palestine", "Palestinian", "Palestinians",
               "antisemitism", "antisemitic", "Zionist", "Zionism", "Hamas", "Netanyahu",
               "October 7", "intifada", "genocide", "synagogue", "Jewish"]},
    {"id": "politics", "label": "Politics & elections",
     "terms": ["DSA", "Democratic Socialists", "primary", "election", "elections",
               "endorse", "endorsement", "endorsed", "campaign", "Cuomo", "Adams",
               "Democratic Party", "Republicans", "reelection", "poll", "polls"]},
]
CASE_SENSITIVE = {"ICE", "DOE", "DOJ", "MTA", "DSA", "SNAP"}


def compile_term(term: str):
    pat = r"\s+".join(re.escape(w) for w in term.split())
    flags = 0 if term in CASE_SENSITIVE else re.I
    return re.compile(r"(?<![\w-])(?:" + pat + r")(?![\w-])", flags)


def load_taxonomy():
    try:
        tax = json.loads(TOPICS.read_text()).get("taxonomy", [])
    except Exception:
        tax = []
    tax = [dict(x) for x in tax] + EXTRA_TOPICS
    for x in tax:
        x["res"] = [compile_term(t) for t in x["terms"]]
    return tax


def topic_ids(taxo, q: str, a: str) -> list[str]:
    """Every theme the question names applies. Themes the answer dwells on
    (3+ hits, or 2+ different terms) fill in, up to two in all."""
    named, dwelt = [], []
    for t in taxo:
        qh = sum(len(r.findall(q)) for r in t["res"])
        ah = [len(r.findall(a)) for r in t["res"]]
        a_hits, a_terms = sum(ah), sum(1 for h in ah if h)
        if qh:
            named.append((qh * 3 + a_hits, t["id"]))
        elif a_hits >= 3 or a_terms >= 2:
            dwelt.append((a_hits, t["id"]))
    named.sort(reverse=True)
    dwelt.sort(reverse=True)
    out = [tid for _, tid in named]
    out += [tid for _, tid in dwelt[: max(0, 2 - len(out))]]
    return out


def taxonomy_meta(taxo):
    palette = {"mideast": "#6B7A8F", "politics": "#B8860B"}
    return [{"id": t["id"], "label": t["label"], "color": t.get("color") or palette.get(t["id"], "#888")}
            for t in taxo]


def main() -> None:
    corpus = json.loads(CORPUS.read_text())
    items = corpus["items"]
    taxo = load_taxonomy()

    events = []
    exchanges = []
    counts = Counter()

    for item in items:
        if item.get("type") not in QA_TYPES or item.get("reliability") != "official":
            continue
        turns = load_speakers(item)
        if not turns:
            continue
        itype = item["type"]
        # Some "media appearances" are joint press briefings where reporters
        # are labeled "Question" — treat those as press events.
        n_qlabels = sum(1 for t in turns if QUESTION_RE.match(t["speaker"]))
        host_like = [t["speaker"] for t in turns if not is_mayor(t["speaker"])
                     and not QUESTION_RE.match(t["speaker"]) and not OFFICIAL_RE.search(t["speaker"])
                     and not NEUTRAL_RE.match(t["speaker"]) and not NOT_PERSON_RE.search(t["speaker"])
                     and not PUBLIC_RE.match(t["speaker"])]
        # Three or more "Question:" turns means reporters in the room — a joint
        # briefing, even if an untitled speaker (a parade organizer) also spoke.
        if itype == "media_appearance" and n_qlabels < 3 and (host_like or not n_qlabels):
            kind = "interview"
        else:
            kind = "press"
        roles = [role_of(t["speaker"], kind) for t in turns]
        override = {}
        if kind == "press":
            mods = moderators(turns)
            if mods:
                roles = ["question" if t["speaker"] in mods else r for t, r in zip(turns, roles)]
                n_q = sum(1 for t in turns if QUESTION_RE.match(t["speaker"]))
                if BROADCAST_TITLE_RE.search(item["title"]):
                    # A radio/TV hit: the voice is the interviewer.
                    kind = "interview"
                    override = {l: "host" for l in mods}
                    override.update({t["speaker"]: "public" for t in turns if QUESTION_RE.match(t["speaker"])})
                else:
                    for l, n in mods.items():
                        # A named reporter at a presser full of "Question:"
                        # turns is still a reporter. Otherwise it's a City
                        # Hall livestream host or a forum moderator — not press
                        # — and the "Livestream Question" turns they relay come
                        # from the public.
                        override[l] = "reporter" if n_q > n else "public"
                    if "public" in override.values():
                        kind = "forum"
                        override.update({t["speaker"]: "public" for t in turns if QUESTION_RE.match(t["speaker"])})
        if "question" not in roles or "mayor" not in roles:
            continue

        ev_id = len(events)
        ev_ex = []
        cur = None
        for t, r in zip(turns, roles):
            if r == "question":
                if cur is not None and not cur["a"]:
                    # still collecting the question (crosstalk / split lines)
                    cur["q"].append({"s": t["speaker"], "t": clean(t["text"])})
                    continue
                # On air, a host's "Right." or "Absolutely." mid-answer is an
                # interjection, not a new question: keep it inside the answer.
                txt = clean(t["text"])
                if (kind != "press" and cur is not None and cur["a"] and "?" not in txt
                        and len(txt.split()) <= 6):
                    cur["a"].append({"s": t["speaker"], "t": txt, "m": 0, "i": 1})
                    continue
                cur = {"q": [{"s": t["speaker"], "t": clean(t["text"])}], "a": []}
                ev_ex.append(cur)
            elif cur is not None:
                if r == "neutral" and not t["text"].strip():
                    continue
                cur["a"].append({"s": display_speaker(t["speaker"]), "t": clean(t["text"]),
                                 "m": 1 if r == "mayor" else 0})
        # Drop question blocks that are pure crosstalk markers.
        ev_ex = [e for e in ev_ex if any(len(re.sub(r"\[.*?\]", "", q["t"]).strip()) > 3 for q in e["q"])]
        if not ev_ex:
            continue

        kinds = asker_kinds(turns, roles, kind)
        kinds.update(override)
        prog = program_name(item["title"]) if kind == "interview" else None
        title = re.sub(r"^Transcript:\s*", "", item["title"]).strip()
        events.append({
            "id": ev_id,
            "date": item["iso_date"],
            "title": title,
            "type": itype,
            "kind": kind,
            "url": item["url"],
            "program": prog,
        })
        n = len(ev_ex)
        for i, e in enumerate(ev_ex):
            qtext = "\n\n".join(q["t"] for q in e["q"])
            atext_m = "\n\n".join(a["t"] for a in e["a"] if a["m"])
            atext = "\n\n".join(a["t"] for a in e["a"])
            answered = ("mayor" if any(a["m"] for a in e["a"])
                        else "others" if any(not a.get("i") for a in e["a"]) else "none")
            asker = e["q"][0]["s"]
            live = bool(re.match(r"livestream", asker, re.I))
            # A host often introduces a caller in the same breath; if any
            # voice in the question block is a caller/guest, the question is
            # theirs.
            ks = [kinds.get(q["s"], "reporter") for q in e["q"]]
            who = "public" if "public" in ks else ks[0]
            ex = {
                "id": f"{item['iso_date']}-{ev_id}-{i + 1}",
                "e": ev_id,
                "n": i + 1,
                "of": n,
                "q": ([{"s": q["s"], "t": q["t"]} for q in e["q"]] if kind == "interview"
                      else [{"t": q["t"]} for q in e["q"]]),
                "w": who,
                "a": e["a"],
                "by": answered,
                "tp": topic_ids(taxo, qtext, atext_m or atext),
            }
            if live:
                ex["live"] = 1
            exchanges.append(ex)
            counts[answered] += 1
            counts["who:" + who] += 1

    events_by_id = {e["id"]: e for e in events}
    exchanges.sort(key=lambda x: (events_by_id[x["e"]]["date"], x["e"], x["n"]), reverse=True)

    out = {
        "generated_at": corpus.get("generated_at"),
        "method": ("Question/answer exchanges cut from official nyc.gov transcripts. "
                   "A question turn opens an exchange; every following turn belongs to it "
                   "until the next question. See build_qa.py and METHODOLOGY.md#press-qa."),
        "counts": {
            "events": len(events),
            "exchanges": len(exchanges),
            "answered_by_mayor": counts["mayor"],
            "answered_by_others_only": counts["others"],
            "no_answer_recorded": counts["none"],
            "from_reporters": counts["who:reporter"],
            "from_hosts": counts["who:host"],
            "from_public": counts["who:public"],
        },
        "topics": taxonomy_meta(taxo),
        "events": events,
        "exchanges": exchanges,
    }
    OUT.write_text(json.dumps(out, ensure_ascii=False, separators=(",", ":")))
    print(f"qa.json: {len(events)} events, {len(exchanges)} exchanges "
          f"({counts['mayor']} answered by the mayor, {counts['others']} by others only, "
          f"{counts['none']} no answer) — {OUT.stat().st_size / 1e6:.1f} MB")


if __name__ == "__main__":
    main()
