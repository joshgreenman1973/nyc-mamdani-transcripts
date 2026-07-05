#!/usr/bin/env python3
"""Parse Mayor Mamdani public-schedule advisory emails into structured JSON.

Source: the daily "PUBLIC SCHEDULE FOR MAYOR ZOHRAN KWAME MAMDANI" advisories
sent by NYCMayorsPressOffice@updates.cityhall.nyc.gov (govDelivery). These are
HTML-only emails; this script strips the markup, isolates the itemized
"Press Schedule" block, and extracts one record per public event with its
time, title, location, press-access status, whether the mayor takes questions,
and whether it is streamed.

Input: raw Gmail get_thread JSON files (each {id, messages:[{subject,date,
htmlBody,...}]}). Output: data/schedule.json.

NOTE: "FOR PLANNING PURPOSES ONLY" — these are announced plans, not
attendance-confirmed logs. See METHODOLOGY.md.
"""
import json, re, html, sys, glob, os

def clean_html(hb: str) -> str:
    t = re.sub(r'<(script|style)[^>]*>.*?</\1>', ' ', hb, flags=re.S | re.I)
    t = re.sub(r'(?i)</(p|div|tr|li|h[1-6])>', '\n', t)
    t = re.sub(r'(?i)<br[^>]*>', '\n', t)
    t = re.sub(r'(?i)</(td|th)>', ' ', t)
    t = re.sub(r'<[^>]+>', '', t)
    t = html.unescape(t)
    t = re.sub(r'[ \t ]+', ' ', t)
    t = '\n'.join(line.strip() for line in t.splitlines())
    t = re.sub(r'\n{3,}', '\n\n', t).strip()
    return t

def fix_times(s: str) -> str:
    # The email wraps characters in spans, so times arrive spaced out like
    # "1 2 : 0 0 P M". Rejoin digits/colons and AM/PM markers.
    s = re.sub(r'(\d)\s*:\s*(\d)', r'\1:\2', s)          # "1 : 0" -> "1:0"
    # "1 2:" -> "12:" only at a token boundary, so station names like "NY1 9:05"
    # aren't glued into "NY19:05".
    s = re.sub(r'(?<![A-Za-z0-9])(\d)\s+(\d)(?=:)', r'\1\2', s)
    s = re.sub(r':(\d)\s+(\d)\b', r':\1\2', s)            # ":0 0" -> ":00"
    s = re.sub(r'\b([AaPp])\s*\.?\s*[Mm]\b', lambda m: m.group(1).upper() + 'M', s)
    s = re.sub(r'(\d)\s*(AM|PM)\b', r'\1 \2', s)          # "12PM" -> "12 PM"
    return s

TIME_RE = re.compile(r'\b(\d{1,2}:\d{2}\s*(?:AM|PM))', re.I)
# An event line: TIME [ (Approx.) ] – Title
EVENT_RE = re.compile(
    r'(\d{1,2}:\d{2}\s*(?:AM|PM))\s*(\(Approx\.?\))?\s*[–—-]\s*(.+)',
    re.I,
)

TYPE_RULES = [
    ("press conference", "Press conference"),
    ("media availability", "Press conference"),
    ("bill signing", "Bill signing"),
    ("signs", "Bill signing"),
    ("executive order", "Bill signing"),
    ("delivers remarks", "Remarks / speech"),
    ("keynote", "Remarks / speech"),
    ("commencement", "Ceremony"),
    ("graduation", "Ceremony"),
    ("swearing", "Ceremony"),
    ("ceremony", "Ceremony"),
    ("ribbon", "Ceremony"),
    ("proclamation", "Ceremony"),
    ("talk with the people", "“Talk With the People” livestream"),
    ("live stream", "Livestream / online"),
    ("livestream", "Livestream / online"),
    ("appears live", "Media appearance"),
    ("appears on", "Media appearance"),
    ("interview", "Media appearance"),
    ("radio", "Media appearance"),
    ("town hall", "Town hall"),
    ("visits", "Visit / tour"),
    ("visit", "Visit / tour"),
    ("tours", "Visit / tour"),
    ("tour", "Visit / tour"),
    ("attends", "Attends / appearance"),
    ("celebrates", "Attends / appearance"),
    ("receives", "Attends / appearance"),
    ("joins", "Attends / appearance"),
    ("marches", "Attends / appearance"),
    ("march", "Attends / appearance"),
    ("parade", "Attends / appearance"),
    ("rally", "Attends / appearance"),
    ("hosts", "Hosts event"),
    ("meets", "Meeting"),
    ("meeting", "Meeting"),
    ("roundtable", "Meeting"),
    ("announce", "Announcement"),
    ("holds", "Public event"),
    ("delivers", "Remarks / speech"),
]

def classify(title: str) -> str:
    low = title.lower()
    for kw, label in TYPE_RULES:
        if kw in low:
            return label
    return "Other public event"

BOROUGH_RE = [
    (re.compile(r'\b(Brooklyn|BK)\b', re.I), "Brooklyn"),
    (re.compile(r'\b(Bronx)\b', re.I), "Bronx"),
    (re.compile(r'\b(Queens|Astoria|Flushing|Jamaica|Corona|Jackson Heights)\b', re.I), "Queens"),
    (re.compile(r'\b(Staten Island)\b', re.I), "Staten Island"),
    (re.compile(r'\b(Manhattan|City Hall|Gracie Mansion|Harlem|Midtown|Lower Manhattan)\b', re.I), "Manhattan"),
]
def borough_of(text: str):
    for rx, name in BOROUGH_RE:
        if rx.search(text):
            return name
    return None

WEEKDAYS = "MONDAY TUESDAY WEDNESDAY THURSDAY FRIDAY SATURDAY SUNDAY".split()
MONTHS = {m: i for i, m in enumerate(
    ["JANUARY","FEBRUARY","MARCH","APRIL","MAY","JUNE","JULY","AUGUST",
     "SEPTEMBER","OCTOBER","NOVEMBER","DECEMBER"], 1)}

def parse_subject_date(subject: str):
    # "... FOR THURSDAY, JUNE 4, 2026"
    m = re.search(r'FOR\s+([A-Z]+),\s+([A-Z]+)\s+(\d{1,2}),\s+(\d{4})', subject.upper())
    if not m:
        return None, None
    wd, mon, day, yr = m.groups()
    if mon not in MONTHS:
        return None, wd.title()
    return f"{yr}-{MONTHS[mon]:02d}-{int(day):02d}", wd.title()

def plain_to_text(pb: str) -> str:
    """Normalize the email's plaintext body (markdown-ish, quoted lines) to the
    same shape clean_html produces, so one parser handles both."""
    t = pb.replace("*", " ").replace("_", " ").replace('"', " ")
    t = re.sub(r"\[\s*https?://[^\]]*\]", " ", t)   # govDelivery link brackets
    t = re.sub(r"<[^>\s]+@[^>\s]+>", " ", t)          # bare <email> tokens
    t = html.unescape(t)
    t = "\n".join(line.strip() for line in t.splitlines())
    t = re.sub(r"[^\S\n]+", " ", t)
    t = re.sub(r"\n{3,}", "\n\n", t).strip()
    return t


def parse_email(subject: str, text: str) -> dict:
    iso, weekday = parse_subject_date(subject)
    text = fix_times(text)
    updated = subject.upper().strip().startswith("UPDATED")

    # Isolate the itemized block after "Press Schedule:" up to the "###" footer.
    block = text
    ps = re.search(r'Press Schedule\s*:?', text, re.I)
    if ps:
        block = text[ps.end():]
    block = re.split(r'\n#{2,}|\bThis email was sent\b', block)[1 if False else 0]

    # Split the block into event chunks, each starting at a time marker.
    lines = [l for l in block.splitlines()]
    # Rejoin into a single string then split on time markers to capture the
    # location/notes that follow each event line.
    joined = "\n".join(lines)
    parts = re.split(r'(?=\b\d{1,2}:\d{2}\s*(?:AM|PM)\b)', joined, flags=re.I)
    events = []
    for part in parts:
        m = EVENT_RE.search(part)
        if not m:
            continue
        time_s = re.sub(r'\s+', ' ', m.group(1)).upper().replace(" ", "")
        time_s = re.sub(r'(AM|PM)', r' \1', time_s).strip()
        approx = bool(m.group(2))
        rest = m.group(3).strip()
        # Title = the first line after the dash. Location + press notes live on the
        # following lines of the SAME segment (`part`), so scan the whole segment
        # for those (EVENT_RE's `.` stops at the newline, so m.group(3) is title-only).
        title = m.group(3).strip(" .")
        # Location: an address-ish line (number + street) or a named venue line.
        loc = None
        addr = re.search(r'([A-Z][^\n;]*?\d{1,5}[^\n;]*(?:Ave|Avenue|St|Street|Blvd|Boulevard|Road|Rd|Place|Pl|Broadway|Plaza|Dr|Drive|Pier)\b[^\n;]*)', part)
        if not addr:
            addr = re.search(r'(?m)^([A-Z][^\n;]*(?:Center|Museum|Hall|Park|Stadium|Library|Plaza|Terminal|Cathedral|Church|Mosque|Temple|Gardens?|Square)[^\n;]*)$', part)
        if addr:
            loc = re.sub(r'\s+', ' ', addr.group(1)).strip(" .;")
        low = part.lower()
        access = ("Open" if "open to press" in low else
                  "Closed" if ("closed press" in low or "closed to press" in low) else
                  "Limited" if "limited press" in low else None)
        takes_q = "take questions" in low or "takes questions" in low
        streamed = any(p in part for p in ["Twitch", "YouTube", "streamed live", "live stream", "Livestream", "Encompass"])
        events.append({
            "time": time_s,
            "approx": approx,
            "title": re.sub(r'\s+', ' ', title),
            "type": classify(title),
            "location": loc,
            "borough": borough_of(loc) if loc else None,
            "access": access,
            "takes_questions": takes_q,
            "streamed": streamed,
        })
    return {
        "date": iso,
        "weekday": weekday,
        "updated": updated,
        "subject": subject.strip(),
        "n_events": len(events),
        "events": events,
    }


def main(paths):
    by_date = {}
    for p in paths:
        try:
            data = json.load(open(p))
        except Exception:
            continue
        for msg in (data.get("messages") or [data]):
            subj = msg.get("subject", "") or ""
            if "PUBLIC SCHEDULE FOR MAYOR ZOHRAN" not in subj.upper():
                continue
            pb = msg.get("plaintextBody") or ""
            hb = msg.get("htmlBody") or ""
            text = plain_to_text(pb) if pb.strip() else clean_html(hb)
            if not text.strip():
                continue
            rec = parse_email(subj, text)
            if not rec["date"]:
                continue
            # Keep the richest/most-recent version per date: prefer UPDATED, then
            # the one with more events, then the later message date.
            prev = by_date.get(rec["date"])
            key = (rec["updated"], rec["n_events"], msg.get("date", ""))
            if prev is None or key > prev["_key"]:
                rec["_key"] = key
                rec["_src_date"] = msg.get("date")
                by_date[rec["date"]] = rec
    out = []
    for d in sorted(by_date):
        r = by_date[d]
        r.pop("_key", None)
        out.append(r)
    return out


if __name__ == "__main__":
    args = sys.argv[1:]
    if args and args[0] == "--test":
        recs = main(args[1:])
        print(json.dumps(recs, indent=2, ensure_ascii=False))
    else:
        recs = main(args)
        # ---- aggregate stats (computed, transparent) ----
        from collections import Counter
        evs = [e for r in recs for e in r["events"]]
        types = Counter(e["type"] for e in evs)
        wk = Counter(r["weekday"] for r in recs)
        def hour(t):
            m = re.match(r"(\d{1,2}):(\d{2})\s*(AM|PM)", t)
            if not m: return None
            h = int(m.group(1)) % 12 + (12 if m.group(3) == "PM" else 0)
            return h + int(m.group(2)) / 60
        starts = [hour(r["events"][0]["time"]) for r in recs if r["events"]]
        ends = [hour(r["events"][-1]["time"]) for r in recs if r["events"]]
        stats = {
            "days": len(recs),
            "events": len(evs),
            "avg_events_per_day": round(len(evs) / len(recs), 2) if recs else 0,
            "type_counts": dict(types.most_common()),
            "weekday_counts": dict(wk),
            "access_open": sum(1 for e in evs if e["access"] == "Open"),
            "access_closed": sum(1 for e in evs if e["access"] == "Closed"),
            "takes_questions": sum(1 for e in evs if e["takes_questions"]),
            "streamed": sum(1 for e in evs if e["streamed"]),
            "earliest_start": min(starts) if starts else None,
            "latest_end": max(ends) if ends else None,
            "date_min": recs[0]["date"] if recs else None,
            "date_max": recs[-1]["date"] if recs else None,
        }
        out = {
            "source": "Daily 'PUBLIC SCHEDULE FOR MAYOR ZOHRAN KWAME MAMDANI' advisories "
                      "from the Mayor's Press Office (NYCMayorsPressOffice@updates.cityhall.nyc.gov).",
            "caveat": "Announced plans marked 'FOR PLANNING PURPOSES ONLY' — not an "
                      "attendance-confirmed log. Sample of the days for which an advisory "
                      "was issued and received; not every day of the administration.",
            "stats": stats,
            "days": recs,
        }
        print(f"Parsed {len(recs)} schedule days, {len(evs)} events.")
        json.dump(out, open("data/schedule.json", "w"), ensure_ascii=False)
