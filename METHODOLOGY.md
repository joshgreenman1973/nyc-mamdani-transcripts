# Methodology

This page exists so nothing about this archive is a black box. Every number,
filter, and classification rule is described here.

## What this is

A searchable archive of the Mamdani administration on the record since he took
office on January 1, 2026. At its center is Mayor Zohran Kwame Mamdani's own
public record — speeches, press conferences, prepared remarks and statements
from the mayor's office, and his interviews. Around that it adds the
**press releases of New York
City's agencies**, so the same box searches the whole administration, not only
the mayor's own events. Every item is dated on or after January 1, 2026, and is
labeled by source, type and reliability.

## Source

The archive draws from several sources. The bulk is the mayor's office's own
published record; the rest are outside transcripts of the mayor's interviews.
**Every item is tagged
with its `source` and a `reliability` level**, and the page lets you filter by
reliability.

### Reliability levels

| Level | Meaning | Sources |
|-------|---------|---------|
| **Official transcript** | A transcript the producing institution published as an official record. | nyc.gov |
| **Published transcript** | A human-prepared transcript published by a news outlet (rush-deadline radio transcripts, NPR's posted transcripts, human YouTube captions). | NPR, WNYC, manually-captioned videos |
| **Auto-caption** | Machine-generated closed captions. May contain errors. | C-SPAN closed captions, auto-captioned videos |
| **Press release** | A press release published by an agency &mdash; a written summary plus attributed quotes, **not** a verbatim transcript of an event. | City-agency press releases; NYPD crime-statistics briefings |

### Per-source detail

- **nyc.gov** (official) — `https://www.nyc.gov/mayors-office/news/`, the mayor's
  Office news page. No public RSS, but the listing is backed by a JSON endpoint
  at `/bin/nyc/articlesearch.json`; we page through it with `fromDate=2026-01-01`
  and fetch each article's full body via its component model JSON
  (`<path>.model.json`). This includes transcripts the office *reposts* of
  friendly media hits (e.g. WNYC, "The View").
- **YouTube** — the mayor's office channel (`@NYCMayorsOffice`), read across all
  three of its tabs: `/videos`, `/streams` (livestreamed press conferences and
  events) and `/shorts`. Videos with an nyc.gov twin get a "Watch" link;
  produced clips with no twin are added with their captions (human → published,
  auto-generated → auto-caption). Each run reconciles the channel against the
  corpus and records the result in `youtube_coverage` (see [Known
  limits](#youtube-coverage)).
- **NPR** (published) — interview transcripts at `npr.org/transcripts/<id>`,
  parsed into speaker turns.
- **WNYC** (published) — the Brian Lehrer Show's "Ask the Mayor" and related
  segments. These are the *raw* rush-deadline radio transcripts (with caller and
  host framing), distinct from the cleaned versions the mayor's office reposts.
  Discovered both from a curated seed list and the show's RSS feed.
- **C-SPAN** (auto-caption) — closed-caption transcripts from the C-SPAN Video
  Library. C-SPAN's search is JavaScript-rendered and its servers bot-block
  aggressively, so coverage here is opportunistic and seeded by hand; a blocked
  fetch is skipped, never recorded as an empty transcript.
- **NYPD** (press release) — the NYPD's monthly, quarterly and year-end
  **crime-statistics briefings**, from the department's newsroom
  (`nyc.gov/site/nypd/news/`). These are included because the mayor attends only
  some of these briefings; the ones he attends are transcribed on the mayor's
  Office site (and are already in this archive), but for the rest **there is no
  public transcript** — the NYPD's own briefing videos carry no captions. What
  the NYPD publishes for every briefing is a press release: a statistical
  write-up plus attributed quotes from Police Commissioner Jessica Tisch (and
  sometimes the mayor). So these items are clearly labeled **"press release &mdash;
  not a verbatim transcript,"** and they carry no speaker turns. The headline is
  shown in sentence case (the source publishes them in all-caps); the wording and
  body text are otherwise unchanged. Scope is **crime-statistics briefings only** —
  gun-removal, strategy and other public-safety announcements are not included.
  The newsroom listing is a session-gated JavaScript widget that can't be fetched
  headless, so briefing URLs are seeded by hand in `nypd_sources.json` (same
  pattern as the curated seeds below); add the next month's release there and it
  is ingested on the next refresh. Any genuine mayor quote inside a release is
  still extracted, so it surfaces under "Only the mayor's words." These are
  keyword-searchable and topic-tagged but kept out of the plain-language
  (semantic) index. They are also **excluded from the "Mayor &amp;
  Police Commissioner Tisch together" featured filter**, because a press release
  is not evidence the two were at the same event.
- **City agencies** (press release) — the press releases of New York City's
  *agencies* (as distinct from City Hall), so the archive is a citywide search,
  not only the mayor's own events. The mayor's words remain the center: every
  agency release is scanned for quotes attributed to him, which surface under
  "Only the mayor's words," and the default views and featured filters stay
  mayor-focused. Agency releases are labeled **"press release — not a verbatim
  transcript,"** filterable individually under **Source / agency**, and kept
  out of the plain-language semantic index.

  *How they're crawled.* Agency newsrooms run on an older CMS whose listing feed
  resists headless scraping. `scrape_agencies.py` uses two strategies, configured
  in `agencies.json`:
  - **Numeric:** most newsrooms give each release a numeric, year-scoped URL id,
    and requesting `/site/<agency>/news/<id>/x` redirects to the canonical
    article — so the crawler walks each agency's ids upward until a run of
    misses. The highest id seen per agency is remembered in the corpus so daily
    refreshes are incremental.
  - **Index:** a second group uses slug URLs (no numeric id) on a different page
    template (`ls-col-body`). For these the crawler scrapes the agency's
    press-release **index page** for release links and parses each; the article
    body, which has no clean wrapper there, is bounded by the dateline and the
    page footer, and the headline is taken from the page `<title>`.
  - **Legacy /html:** a few agencies (notably DOT) are on an older static
    `/html/.../pr2026/*.shtml` site with different markup again. The crawler
    scrapes their static press-release index for links and parses the
    `agency-content` body (headline from the page subtitle, ending at the
    `###` release marker).

  Thin "in the news" stubs (a headline plus an external media link, no body) are
  skipped, as are releases under 25 words. ALL-CAPS headlines are shown in
  sentence case; wording and body are otherwise unchanged.

  *Agencies currently included:* **NYPD, Fire (FDNY), Sanitation (DSNY), Housing
  Preservation &amp; Development (HPD), Environmental Protection (DEP), Consumer
  &amp; Worker Protection (DCWP), Children's Services (ACS), Citywide
  Administrative Services (DCAS)** (numeric), plus **Health (DOHMH), Homeless
  Services (DHS), Small Business Services (SBS), Taxi &amp; Limousine (TLC),
  Immigrant Affairs (MOIA), and Media &amp; Entertainment (MOME)** (index), plus
  **Transportation (DOT)** (legacy /html). This is an expanding set determined by
  a one-time discovery sweep of every city agency. Still out: a few agencies
  whose index pages are themselves JavaScript-rendered (e.g. HRA, Law, Finance,
  Investigation) and agencies on separate websites (Parks, Schools, NYCHA,
  Health + Hospitals) or outside the mayoral administration (Comptroller, Public
  Advocate) — all noted rather than silently omitted.
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

Each item is assigned a single type from the title. The mayor's office publishes
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
| Op-ed                          | The body shows the Mayor's Office reposting an outside opinion piece ("in a new opinion piece," "read the full piece in&hellip;"). **Only the summary + a link are captured** — the verbatim op-ed lives at the outlet (copyright). Detected from the body, not the title. |
| Ceremony / public event       | Title contains "Ceremony", "Memorial", "Wreath Laying", "Ribbon Cutting", "Groundbreaking" |
| Executive order               | Title contains "Executive Order"                                  |
| Video                         | A YouTube clip with no nyc.gov twin (assigned by the YouTube scraper) |
| NYPD crime briefing           | An NYPD crime-statistics press release (assigned by the NYPD scraper, not by title) |
| Agency press release          | A city-agency press release (assigned by the agency crawler, not by title) |
| Press release (other)         | Everything else &mdash; mayor's office staff-written announcements |

Interviews captured from outside outlets (NPR, WNYC, C-SPAN) are filed as
**Media appearances**.

By default the search covers everything except staff-written press releases and
executive orders: speeches, press conferences, media appearances, statements,
ceremonies, videos and NYPD crime briefings. Toggles add the
press releases and executive orders, or narrow to any subset.

### What this misses

- **Spontaneous remarks** the mayor's office didn't transcribe (gaggles, off-
  the-cuff comments at events, etc.) are not in the archive at all. We can
  only index what the mayor's office publishes.
- **Press releases written by staff** quote the mayor in blocks but are not
  end-to-end his words. They sit in the "Other news" bucket. Searching with
  that toggle on will surface his quoted lines along with the surrounding
  staff-written framing.
- **Embargoed and internal memos** are not published and therefore not here.
- **Social media posts** are not in scope. The mayor's X account
  (`x.com/NYCMayor`) reposts much of the video content, but X's timeline is
  rendered behind authentication and cannot be read without a paid API tier, so
  it is not a source here. Video posted there is generally also on the YouTube
  channel, which is covered in full.

<a id="youtube-coverage"></a>
### YouTube coverage, and how it is checked

Between April 29 and July 22, 2026, YouTube ingestion silently stopped: YouTube
began rejecting the video-metadata requests, and the scraper could not tell
that failure apart from "the channel has nothing new," so the daily refresh
reported success while adding nothing. Roughly three months of video went
unindexed. It has been backfilled.

Three checks now make a repeat visible rather than silent:

1. The scraper reads every channel tab, not just `/videos`. `/streams` — where
   livestreamed press conferences land — holds most of the channel and had
   never been read.
2. A run that resolves no videos at all is treated as a failure, not an empty
   channel, and turns the scheduled build red.
3. Every run reconciles the channel listing against the corpus and writes
   `youtube_coverage` into `data/corpus.json`, naming any video that is present
   on the channel but absent from the archive.

Two limits remain. YouTube rate-limits caption requests, so a large backlog
drains over several runs rather than one; affected videos are retried, never
dropped. And videos with captions disabled cannot be transcribed at all — they
stay listed as unaccounted rather than being quietly forgotten.

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
- The type, date, and "only the mayor's words" filters still apply. Results below
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
3. **The mayor is present and his remarks place her at the event** &mdash; a
   mention of Tisch within about 90 characters of language such as "joining me,"
   "with us today," "joined by," or a thank-you to her for being there.

To avoid false positives, the filter **excludes**:

- **Passing references**: a reporter's question about Tisch, "I'm in constant
  communication with Commissioner Tisch," news recaps discussing something she
  said elsewhere, or appointment press releases that merely name her.

Limitation: this is a transparent rule, not human curation. It can miss an event
where she was present but unnamed in the text, and the boundary between "present"
and "discussed" is occasionally a judgment call. Each match links to its full
source so you can confirm. As of the latest refresh it flags roughly a dozen
events from January 2026 onward.

## Trends &amp; themes

The **Trends &amp; themes** tab summarizes *what* the mayor talks about and how
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
quotes from the mayor** under each. Quote selection is deterministic and
extractive &mdash; we never paraphrase, summarize, or generate text:

- Candidates are the mayor's attributed quotes inside press releases plus his own
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

<a name="language"></a>

## How the mayor speaks: word cloud &amp; signature phrases

The "How the mayor speaks" panel on the Trends &amp; themes page is built by
`build_topics.mjs` and refreshed on the same daily schedule. Both halves are
computed **only over the mayor's own words** &mdash; the `mayor_text` field,
which holds his transcript turns and the quotes attributed to him inside press
releases, and **never** reporters' questions or other speakers. As of the last
build that is roughly 410,000 words across about 550 items. Nothing here uses a
model or any paid service; it is plain word-counting you can reproduce.

### Words he uses most (word cloud)

- We tokenize the mayor's words, lowercase them, and count how often each word
  appears. The 110 most frequent are shown, sized by the **square root** of
  their count (so the single most common word doesn't dwarf the rest) and shaded
  in three tiers by rank.
- Before counting we remove a **published stop-word list** &mdash; common
  function words ("the," "and," "to"), filler ("really," "actually," "like"),
  bare numbers, and a few artifacts such as "york" (which only ever appears
  inside "New York"). The full list is in `build_topics.mjs`.
- This is raw frequency, **not** a distinctiveness measure: it shows what he says
  a lot, not what he says more than other politicians. A word can also carry more
  than one meaning.

### Phrases he returns to (signature phrases)

- We start from a **published candidate list** of recurring expressions (in
  `build_topics.mjs`, and echoed in `topics.json` as `language.phrase_candidates`),
  seeded from the most common two-to-four-word sequences in his remarks plus his
  known refrains.
- For each phrase we count its exact occurrences and, more tellingly, the number
  of **separate events** he used it in. A phrase is shown only if he used it
  across at least **8 different events** (and at least 10 times total), so the
  list reflects habits, not one memorable speech. Phrases are ordered by event
  spread.
- Each phrase shows a **verbatim example sentence** from his own words, linked to
  its source. Nothing is paraphrased.

### Matching the counts on screen

Clicking any word or phrase runs a live "only the mayor's words" search for it
across the whole administration (all types, all agencies). Because his quotes
inside agency press releases count as his words, that search returns the same
total shown on the card &mdash; e.g. "far too long" reads *44 events* and the
search returns 44 items. The candidate list is deliberately conservative: a phrase
he repeats that we didn't list simply won't appear, so treat the panel as a
transparent sample of his rhetoric, not an exhaustive ranking.

<a name="schedule"></a>

## The mayor's public days (public-schedule analysis)

The "Public schedule" tab summarizes the mayor's announced public events.

- **Source.** The daily *"PUBLIC SCHEDULE FOR MAYOR ZOHRAN KWAME MAMDANI"*
  advisories the Mayor's Press Office emails to the press
  (`NYCMayorsPressOffice@updates.cityhall.nyc.gov`). These are not posted on
  nyc.gov in a machine-readable form, so the data is drawn from the emails
  themselves. `parse_schedules.py` strips each email, isolates the itemized
  "Press Schedule" block, and extracts one record per event: time, title, a
  keyword-based event type, location (when an address is given), whether it is
  open or closed to press, whether the mayor takes questions, and whether it is
  streamed.
- **Press access is read from the advisory's exact wording**, not lumped into
  "open/closed." Each event is placed in one bucket by the strongest signal:
  *Open to all press* ("open to press" with no caveat); *RSVP / press-office
  clearance* ("media interested in attending must RSVP / register"); *Limited —
  space-constrained* ("space constraints," "does not guarantee entry," "cameras
  will not be permitted"); *Footage provided* ("footage will be pooled / sent");
  *Closed to press*; *Broadcast / remote* (a TV or radio hit or livestream, where
  in-person access does not apply); or *Not specified* (no press note given). A
  closed/footage note outranks a space limit, which outranks a plain RSVP, which
  outranks a plain "open." The keyword rules are in `parse_schedules.py`.
- **These are plans, not attendance.** Every advisory is headed *"FOR PLANNING
  PURPOSES ONLY."* It is what the office *announced*, issued the day before or
  morning of. Events can move or be cancelled; the mayor may add stops not on the
  public schedule. Treat this as the planned public calendar, not a confirmed log
  of what happened.
- **Coverage is a growing sample, not a census.** The office does not issue an
  advisory every day, and this archive currently holds the subset that have been
  processed — **not every day of the administration.** The on-page banner always
  states the exact date range and day count. Percentages (open to press, takes
  questions, streamed) are shares of the events in that sample. Because coverage
  is uneven across time, we do **not** chart events-per-week trends, which gaps
  would distort.
- **Known limits.** Event-type tags come from a keyword list and can misfile an
  unusual event. Location parsing is best-effort — many events list only a venue
  name or no address, so location/borough are shown only when clearly given.
  When the office sends an "UPDATED" schedule for a day, we use the updated one.
- **Refresh.** Unlike the rest of the site (which a GitHub Action rebuilds from
  public web sources), this dataset comes from email and is updated separately as
  new advisories are added.

## Data fields stored per item

| Field         | Description                                              |
|---------------|----------------------------------------------------------|
| `title`       | Full headline as published                               |
| `date`        | Publication date as written by the mayor's office        |
| `iso_date`    | ISO format (YYYY-MM-DD) of the publication date          |
| `type`        | Classification (see above)                               |
| `source`      | Where it came from: `nyc.gov`, `youtube`, `npr`, `wnyc`, `cspan` |
| `reliability` | `official`, `verified` (published), or `auto` (auto-caption) |
| `text`        | Plain-text body, paragraph breaks preserved              |
| `mayor_text`  | The subset of `text` attributable to the mayor himself (his speaker turns or attributed quotes); empty when he isn't a speaker |
| `word_count`  | Token count of `text`                                    |
| `url`         | Canonical URL at the source                              |

## Reproducibility

The scraper, frontend, and this document are all in
[the project repository](https://github.com/joshgreenman1973/nyc-mamdani-transcripts).
Anyone can re-run `python3 scrape.py` to regenerate the nyc.gov portion of
`data/corpus.json` from scratch, using only the Python standard library &mdash;
no scraping dependencies, no API keys. The outside sources are added by
`python3 scrape_youtube.py` (mayor's office channel), and `python3 scrape_external.py`
(NPR, WNYC, C-SPAN, podcasts &mdash; seeded by `external_sources.json`).
Each appends to the same
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
operated on behalf of the mayor's office or the City of New York.
