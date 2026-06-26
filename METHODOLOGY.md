# Methodology

This page exists so nothing about this archive is a black box. Every number,
filter, and classification rule is described here.

## What this is

A searchable archive of Mayor Zohran Kwame Mamdani's on-the-record public
statements since taking office on January 1, 2026. Every item published by the
New York City Mayor's Office news page and dated on or after January 1, 2026
is included.

## Source

The archive draws from several sources. The bulk is the Mayor's Office's own
published record; the rest are outside transcripts of the Mayor's interviews and
City Council hearings where his administration testifies. **Every item is tagged
with its `source` and a `reliability` level**, and the page lets you filter by
reliability.

### Reliability levels

| Level | Meaning | Sources |
|-------|---------|---------|
| **Official transcript** | A transcript the producing institution published as an official record. | nyc.gov; NYC Council hearing transcripts |
| **Published transcript** | A human-prepared transcript published by a news outlet (rush-deadline radio transcripts, NPR's posted transcripts, human YouTube captions). | NPR, WNYC, manually-captioned videos |
| **Auto-caption** | Machine-generated closed captions. May contain errors. | C-SPAN closed captions, auto-captioned videos |
| **Press release** | A press release published by an agency &mdash; a written summary plus attributed quotes, **not** a verbatim transcript of an event. | City-agency press releases; NYPD crime-statistics briefings |

### Per-source detail

- **nyc.gov** (official) — `https://www.nyc.gov/mayors-office/news/`, the Mayor's
  Office news page. No public RSS, but the listing is backed by a JSON endpoint
  at `/bin/nyc/articlesearch.json`; we page through it with `fromDate=2026-01-01`
  and fetch each article's full body via its component model JSON
  (`<path>.model.json`). This includes transcripts the office *reposts* of
  friendly media hits (e.g. WNYC, "The View").
- **YouTube** — the Mayor's Office channel (`@NYCMayorsOffice`). Videos with an
  nyc.gov twin get a "Watch" link; produced clips with no twin are added with
  their captions (human → published, auto-generated → auto-caption).
- **NPR** (published) — interview transcripts at `npr.org/transcripts/<id>`,
  parsed into speaker turns.
- **WNYC** (published) — the Brian Lehrer Show's "Ask the Mayor" and related
  segments. These are the *raw* rush-deadline radio transcripts (with caller and
  host framing), distinct from the cleaned versions the Mayor's Office reposts.
  Discovered both from a curated seed list and the show's RSS feed.
- **C-SPAN** (auto-caption) — closed-caption transcripts from the C-SPAN Video
  Library. C-SPAN's search is JavaScript-rendered and its servers bot-block
  aggressively, so coverage here is opportunistic and seeded by hand; a blocked
  fetch is skipped, never recorded as an empty transcript.
- **NYC Council** (official) — verbatim stenographic hearing transcripts from the
  Council's Legistar Web API, filtered to **oversight hearings where the Mayor's
  administration testifies**. The filtering is deliberately strict, because the
  raw data is messy:
  - *Stated-meeting* transcripts (the Council's own legislative voting sessions)
    are excluded — they're council members, not administration testimony.
  - The same transcript is often cross-linked to many committees' agendas. We
    keep only files referenced by a **single** committee event (a genuine
    single-committee hearing), and additionally drop **content-duplicates** (a
    joint hearing uploaded separately under each committee) by comparing text.
  - We keep a hearing only when it shows agency testimony — the transcript
    references a "Commissioner" several times **and** someone "testifies."
  Because the Mayor himself rarely testifies, these items usually have no
  "Mayor's words" and the mayor-only filter skips them. They're also very long
  (tens of thousands of words), so they're keyword-searchable and topic-tagged
  but kept out of the plain-language (semantic) index to keep its download small.
  Requires a free Legistar API token; absent the token this source is skipped.
- **NYPD** (press release) — the NYPD's monthly, quarterly and year-end
  **crime-statistics briefings**, from the department's newsroom
  (`nyc.gov/site/nypd/news/`). These are included because the Mayor attends only
  some of these briefings; the ones he attends are transcribed on the Mayor's
  Office site (and are already in this archive), but for the rest **there is no
  public transcript** — the NYPD's own briefing videos carry no captions. What
  the NYPD publishes for every briefing is a press release: a statistical
  write-up plus attributed quotes from Police Commissioner Jessica Tisch (and
  sometimes the Mayor). So these items are clearly labeled **"press release &mdash;
  not a verbatim transcript,"** and they carry no speaker turns. The headline is
  shown in sentence case (the source publishes them in all-caps); the wording and
  body text are otherwise unchanged. Scope is **crime-statistics briefings only** —
  gun-removal, strategy and other public-safety announcements are not included.
  The newsroom listing is a session-gated JavaScript widget that can't be fetched
  headless, so briefing URLs are seeded by hand in `nypd_sources.json` (same
  pattern as the curated seeds below); add the next month's release there and it
  is ingested on the next refresh. Any genuine Mayor quote inside a release is
  still extracted, so it surfaces under "Only the Mayor's words." Like Council
  hearings, these are keyword-searchable and topic-tagged but kept out of the
  plain-language (semantic) index. They are also **excluded from the "Mayor &amp;
  Police Commissioner Tisch together" featured filter**, because a press release
  is not evidence the two were at the same event.
- **City agencies** (press release) — the press releases of New York City's
  *agencies* (as distinct from City Hall), so the archive is a citywide search,
  not only the Mayor's own events. The Mayor's words remain the center: every
  agency release is scanned for quotes attributed to him, which surface under
  "Only the Mayor's words," and the default views and featured filters stay
  Mayor-focused. Agency releases are labeled **"press release — not a verbatim
  transcript,"** filterable individually under **Source / agency**, and (like
  Council hearings) kept out of the plain-language semantic index.

  *How they're crawled.* Agency newsrooms run on an older CMS whose listing feed
  resists headless scraping, but each release has a numeric, year-scoped URL id,
  and requesting `/site/<agency>/news/<id>/x` redirects to the canonical article.
  So `scrape_agencies.py` walks each agency's ids upward until a run of misses,
  following the redirects. Agencies and their id formats are configured in
  `agencies.json`; the highest id seen per agency is remembered in the corpus so
  daily refreshes are incremental. Thin "in the news" stubs (a headline plus an
  external media link, no body) are skipped. ALL-CAPS headlines are shown in
  sentence case; wording and body are otherwise unchanged.

  *Agencies currently included* (numeric-id newsrooms sharing the standard
  article template): **NYPD, Sanitation (DSNY), Housing Preservation &amp;
  Development (HPD), Environmental Protection (DEP), Consumer &amp; Worker
  Protection (DCWP), Children's Services (ACS), and Citywide Administrative
  Services (DCAS).** This is an expanding set. Some agencies publish on different
  page templates — Health (`/site/doh/.../press/`) and DOT (a legacy `/html/`
  site) use slug-based URLs and different markup, and FDNY uses several
  irregular id prefixes — so they need their own parsers and are a planned next
  wave rather than a limit of the design.
- **Curated seeds** — outside sources can't be fully auto-discovered (their
  search pages are JavaScript-rendered and bot-gated), so known appearances are
  listed in `external_sources.json`. Adding an entry there ingests it on the next
  refresh.

We do not modify transcript text. Punctuation, spelling, and capitalization match
what each source published; auto-captions are labeled as such because they can
contain transcription errors.

## Refresh cadence

A scheduled job re-runs the scraper every day at approximately 7&nbsp;a.m.
Eastern. New articles are appended; existing entries are not re-fetched. The
"Last refreshed" timestamp at the top of the page reflects the last run.

## Classification

Each item is assigned a single type from the title. The Mayor's Office publishes
many speeches under a `Transcript:` prefix (the as-delivered version), so we
strip that prefix first and let the rest of the title drive classification.
Order matters — speech rules run before press-conference rules so that
"Transcript: Mayor Mamdani Joins Bernie Sanders to Deliver Remarks" is filed
as a speech, not a press conference.

| Type                          | Rule (after stripping `Transcript:` / `ICYMI:` / `Watch:` prefix) |
|-------------------------------|-------------------------------------------------------------------|
| Speech &amp; prepared remarks | Title contains "Delivers Remarks", "Delivers Address", "Delivers Speech", "Delivers Keynote", "Remarks as Prepared", "Prepared Remarks", "100 Day Address", "Inaugural Address", "Eulogy", or similar |
| Press conference              | Title contains "Holds Press Conference", "Holds Media Availability", "Press Briefing", or any other `Transcript:` item that didn't match a more specific rule |
| Media appearance              | Title contains "Appears on", "Appears Live on", "Hosts Town Hall", or "Interview" |
| Statement                     | Title begins with "Statement from", "Statement by", or contains "Mamdani Statement" |
| Ceremony / public event       | Title contains "Ceremony", "Memorial", "Wreath Laying", "Ribbon Cutting", "Groundbreaking" |
| Executive order               | Title contains "Executive Order"                                  |
| Council hearing               | A Council hearing transcript (assigned by the Council scraper, not by title) |
| Video                         | A YouTube clip with no nyc.gov twin (assigned by the YouTube scraper) |
| NYPD crime briefing           | An NYPD crime-statistics press release (assigned by the NYPD scraper, not by title) |
| Agency press release          | A city-agency press release (assigned by the agency crawler, not by title) |
| Press release (other)         | Everything else &mdash; Mayor's Office staff-written announcements |

Interviews captured from outside outlets (NPR, WNYC, C-SPAN) are filed as
**Media appearances**.

By default the search covers everything except staff-written press releases and
executive orders: speeches, press conferences, media appearances, statements,
ceremonies, videos, Council hearings and NYPD crime briefings. Toggles add the
press releases and executive orders, or narrow to any subset.

### What this misses

- **Spontaneous remarks** the Mayor's Office didn't transcribe (gaggles, off-
  the-cuff comments at events, etc.) are not in the archive at all. We can
  only index what the Mayor's Office publishes.
- **Press releases written by staff** quote the Mayor in blocks but are not
  end-to-end his words. They sit in the "Other news" bucket. Searching with
  that toggle on will surface his quoted lines along with the surrounding
  staff-written framing.
- **Embargoed and internal memos** are not published and therefore not here.
- **Social media posts** are not in scope.

## Search

There are two search modes, toggled at the top of the page.

### Keyword (default)

- Full-text index built client-side with [MiniSearch](https://github.com/lucaong/minisearch).
- Query terms are matched against title (boosted &times;3) and body text.
- Multiple words are combined with AND.
- Prefix matching is on (e.g. "rent" matches "rental", "renting").
- Fuzzy matching tolerates one-character typos on longer terms.
- Results are sorted by date (newest first) by default; toggle to relevance to
  rank by match strength.

### Plain language (semantic)

This mode lets you ask a question in ordinary words and ranks passages by
**meaning** rather than exact wording, so "how will buses become free?" can
surface relevant remarks even when they never use those words.

- Each item's body is split into passages of roughly 900 characters (paragraph
  boundaries first, with very long paragraphs split on sentence boundaries).
- Every passage is converted to a 384-number vector ("embedding") using the
  open-source [gte-small](https://huggingface.co/Xenova/gte-small) model. These
  vectors are precomputed once (see `build_embeddings.mjs`), quantized to 8-bit
  integers to keep the file small, and stored in `data/embeddings.json` alongside
  each passage's location in the source text and the corpus's average vector.
- When you type a question, the **same model runs in your browser** (loaded once
  from a public CDN, about 35&nbsp;MB, then cached) and converts your question to
  a vector. We subtract the corpus average from every vector first &mdash; without
  that step, all of these speech passages look similar to each other and the
  topical signal is lost. Passages are then ranked by cosine similarity; the
  best-matching passage per document is shown.
- Everything runs on your device. **No query ever leaves your browser**, there is
  no server, no external search API, and no cost &mdash; the same reason the
  archive can stay a free, static page.
- The type, date, and "only the Mayor's words" filters still apply. Results below
  a minimum similarity are dropped, and the top 50 are shown, ranked by relevance.
- Limitation: semantic relevance is approximate. It is good at finding passages
  that are *about* a topic, but for exact phrases or names, keyword mode is more
  precise.

## Featured filters

<a name="appeared-together"></a>

### Mayor &amp; Police Commissioner Tisch together

The **Featured** chip under the search box restricts the archive to events where
Mayor Mamdani and Police Commissioner Jessica Tisch *appeared together* &mdash;
not merely items where her name comes up. It is recomputed in your browser from
the day's corpus, so the count tracks the daily refresh.

An item qualifies if any one of these is true:

1. **Tisch has her own speaking turn** in the transcript (the parsed speaker list
   includes a "Commissioner Tisch" / "Police Commissioner Jessica Tisch" turn).
2. **The headline pairs the two**, e.g. "Mayor Mamdani and Commissioner Tisch
   Announce&hellip;" or "Mayor Mamdani Joins NYPD Commissioner Jessica S. Tisch&hellip;",
   or the item is a **joint statement**.
3. **The Mayor is present and his remarks place her at the event** &mdash; a
   mention of Tisch within about 90 characters of language such as "joining me,"
   "with us today," "joined by," or a thank-you to her for being there.

To avoid false positives, the filter **excludes**:

- **Council hearings** (committee testimony &mdash; the Mayor doesn't testify).
- **Passing references**: a reporter's question about Tisch, "I'm in constant
  communication with Commissioner Tisch," news recaps discussing something she
  said elsewhere, or appointment press releases that merely name her.

Limitation: this is a transparent rule, not human curation. It can miss an event
where she was present but unnamed in the text, and the boundary between "present"
and "discussed" is occasionally a judgment call. Each match links to its full
source so you can confirm. As of the latest refresh it flags roughly a dozen
events from January 2026 onward.

## Trends &amp; themes

The **Trends &amp; themes** tab summarizes *what* the Mayor talks about and how
that changes month to month. Like everything else here, the method is simple and
fully published &mdash; no machine-learning model, no API, and nothing hidden.

### How items are tagged

- Each item is scanned for the keywords listed below. A keyword counts only as a
  **whole word**, case-insensitively, so "rent" does not match "different" and
  "ICE" does not match "price".
- An item is tagged with a theme when that theme is hit **three or more times**,
  **or** when **two or more different keywords** from its list appear. A single
  passing mention is not enough &mdash; this stops a wide-ranging press conference
  from being tagged with every theme it grazes.
- We then keep only an item's **top three** themes (by number of hits), so the
  chart reflects what an event was mainly about. About one in five items match no
  theme strongly and are left untagged.
- A bar's height is the **count of items** tagged with each theme that month; an
  item can count toward up to three themes, so columns can total more than the
  number of items that month. The most recent month is partial (month-to-date).

### The full keyword list

This is the entire lexicon. It is editorial, not exhaustive &mdash; it covers the
recurring policy themes of this administration, and it can be extended. The live
version is in `build_topics.mjs` and `data/topics.json`.

| Theme | Keywords (whole-word, case-insensitive) |
|-------|------------------------------------------|
| Housing & rent | rent, rent freeze, rent-stabilized, rent stabilized, housing, affordable housing, NYCHA, public housing, CityFHEPS, FHEPS, eviction, evicted, landlord, tenant, tenants, Section 8, housing voucher, homeless, homelessness, shelter |
| Transit & buses | subway, subways, bus, buses, free buses, fare, fares, MTA, transit, congestion pricing, straphangers, commute, commuters |
| Public safety | police, NYPD, officers, crime, shooting, shootings, gun, guns, public safety, precinct, violence, violent, homicide, subway safety, police commissioner |
| Immigration | ICE, immigrant, immigrants, immigration, deportation, deport, deported, asylum, sanctuary, migrant, migrants, undocumented |
| Child care & schools | child care, childcare, universal childcare, day care, daycare, pre-K, 3-K, schools, public schools, students, teachers, CUNY, education, DOE, Department of Education |
| Cost of living | affordability, affordable, cost of living, groceries, grocery, city-owned grocery, prices, working-class, working class, minimum wage, living wage, wages, cost-of-living |
| Jobs & labor | union, unions, labor, workers, worker, prevailing wage, jobs, hiring, apprenticeship, collective bargaining, DC 37, unionized |
| Health & food | health, hospital, hospitals, mental health, Medicaid, Medicare, SNAP, food assistance, food stamps, public health, health care, healthcare, overdose |
| Federal & Trump | Trump, federal government, Washington, White House, the administration, federal funding, federal cuts, DOJ, Department of Justice, tariffs, Congress |
| Albany & the state | Albany, Hochul, Governor, state legislature, New York State, state budget, state lawmakers, the legislature, assembly, state senate |
| Budget & taxes | budget, taxes, tax, revenue, fiscal, deficit, millionaire, millionaires, spending, comptroller, tax the rich |
| Climate & environment | climate, environment, emissions, clean energy, renewable, extreme heat, flooding, resilience, green, solar, Local Law 97 |

### The monthly digest

For each month, the digest lists that month's leading themes and shows **verbatim
quotes from the Mayor** under each. Quote selection is deterministic and
extractive &mdash; we never paraphrase, summarize, or generate text:

- Candidates are the Mayor's attributed quotes inside press releases plus his own
  transcript turns, split into sentences and limited to a readable length
  (roughly 60&ndash;320 characters).
- Each candidate is scored by how many of the theme's keywords it contains; the
  highest-scoring, then shortest, one or two are shown, with near-duplicates
  removed. Every quote links to its source on nyc.gov.

### What this misses

- Keyword tagging catches a theme only when one of the listed words appears. A
  remark about housing that never uses a housing keyword will be missed, and a
  theme outside the list is not tracked at all.
- A keyword can occasionally land in an unrelated context (for example, "green"
  meaning a color rather than the environment). The multi-hit threshold reduces
  but does not eliminate this.
- The digest surfaces *representative* quotes by keyword density, not the single
  most newsworthy line; treat it as a starting point, then read the full items.

## Data fields stored per item

| Field         | Description                                              |
|---------------|----------------------------------------------------------|
| `title`       | Full headline as published                               |
| `date`        | Publication date as written by the Mayor's Office        |
| `iso_date`    | ISO format (YYYY-MM-DD) of the publication date          |
| `type`        | Classification (see above)                               |
| `source`      | Where it came from: `nyc.gov`, `youtube`, `npr`, `wnyc`, `cspan`, `council` |
| `reliability` | `official`, `verified` (published), or `auto` (auto-caption) |
| `text`        | Plain-text body, paragraph breaks preserved              |
| `mayor_text`  | The subset of `text` attributable to the Mayor himself (his speaker turns or attributed quotes); empty when he isn't a speaker |
| `word_count`  | Token count of `text`                                    |
| `url`         | Canonical URL at the source                              |

## Reproducibility

The scraper, frontend, and this document are all in
[the project repository](https://github.com/joshgreenman1973/nyc-mamdani-transcripts).
Anyone can re-run `python3 scrape.py` to regenerate the nyc.gov portion of
`data/corpus.json` from scratch, using only the Python standard library &mdash;
no scraping dependencies, no API keys. The outside sources are added by
`python3 scrape_youtube.py` (Mayor's Office channel), `python3 scrape_external.py`
(NPR, WNYC, C-SPAN, podcasts &mdash; seeded by `external_sources.json`), and
`python3 scrape_council.py` (Council hearings; needs a free `LEGISTAR_TOKEN` and
`pdfminer.six`, and is a no-op without the token). Each appends to the same
corpus and is non-fatal, so a blocked source never breaks the others. To
regenerate the plain-language search vectors,
run `npm install` then `node build_embeddings.mjs`, which writes
`data/embeddings.json`. The embedding model downloads from a public model hub;
no API key or paid service is involved. To regenerate the theme tags, trend
matrix, and monthly digest, run `node build_topics.mjs`, which writes
`data/topics.json` using only the Node standard library (no dependencies, no
model, no API). The daily refresh job rebuilds the vectors and the topic trends
automatically whenever the corpus changes.

## Independence

This is an independent archive. It is not affiliated with, endorsed by, or
operated on behalf of the Mayor's Office or the City of New York.
