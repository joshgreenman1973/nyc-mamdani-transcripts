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

- Full-text index built client-side with [MiniSearch](https://github.com/lucaong/minisearch).
- Query terms are matched against title (boosted &times;3) and body text.
- Multiple words are combined with AND.
- Prefix matching is on (e.g. "rent" matches "rental", "renting").
- Fuzzy matching tolerates one-character typos on longer terms.
- Results are sorted by date (newest first) by default; toggle to relevance to
  rank by match strength.

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
dependencies, no API keys.

## Independence

This is an independent archive. It is not affiliated with, endorsed by, or
operated on behalf of the Mayor's Office or the City of New York.
