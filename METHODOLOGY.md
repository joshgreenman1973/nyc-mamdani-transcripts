# Methodology

This page exists so nothing about this archive is a black box. Every number,
filter, and classification rule is described here.

## What this is

A searchable archive of Mayor Zohran Kwame Mamdani's on-the-record public
statements since taking office on January 1, 2026. Every item published by the
New York City Mayor's Office news page and dated on or after January 1, 2026
is included.

## Source

- **All content comes from** `https://www.nyc.gov/mayors-office/news/`, the
  Mayor's Office news page run by the City of New York.
- The site does not publish a public RSS feed, but its news listing is backed
  by a JSON endpoint at `/bin/nyc/articlesearch.json`. We page through that
  endpoint with `fromDate=2026-01-01` and fetch each article's full body via
  its component model JSON (`<path>.model.json`).
- We do not modify article text. Punctuation, spelling, and capitalization
  match what the Mayor's Office published.

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
| Press release (other)         | Everything else &mdash; staff-written announcements               |

The default search scope is **Speeches + Press conferences + Media appearances
+ Statements + Ceremonies**: the closest approximation of "what the Mayor said
on the record." Toggles expand the search to staff-written press releases and
executive orders.

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
| `text`        | Plain-text body extracted from the article's component tree, paragraph breaks preserved |
| `word_count`  | Token count of `text`                                    |
| `url`         | Canonical nyc.gov URL                                    |

## Reproducibility

The scraper, frontend, and this document are all in
[the project repository](https://github.com/joshgreenman1973/nyc-mamdani-transcripts).
Anyone can re-run `python3 scrape.py` to regenerate `data/corpus.json` from
scratch. The script uses only the Python standard library &mdash; no scraping
dependencies, no API keys. To regenerate the plain-language search vectors,
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
