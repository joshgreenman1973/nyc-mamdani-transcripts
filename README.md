# Mamdani administration transcript & press release search

A searchable archive of the Mamdani administration on the record since he took
office on January 1, 2026 — Mayor Zohran Mamdani's speeches, press-conference
transcripts, prepared remarks and statements (with his interviews and the City
Council hearings where his administration testifies), plus the press releases of
New York City's agencies. The mayor's words stay the center; agency releases
widen it into a citywide search. Filter by source/agency, type and reliability.

**Live site:** https://joshgreenman1973.github.io/nyc-mamdani-transcripts/

**Sources:** City Hall content from
[nyc.gov/mayors-office/news](https://www.nyc.gov/mayors-office/news/); agency
press releases from each agency's nyc.gov newsroom; plus NPR, WNYC, C-SPAN and
NYC Council hearing records. See [METHODOLOGY.md](METHODOLOGY.md) for what's
included, what's excluded, how items are classified, and how each agency is
crawled.

## Files

- `scrape.py` &mdash; Python 3 scraper (stdlib only) for the Mayor's Office news. Chains the others in CI.
- `scrape_agencies.py` + `agencies.json` &mdash; city-agency press-release crawler (numeric, index and legacy-/html strategies).
- `scrape_external.py`, `scrape_council.py`, `scrape_nypd.py`, `scrape_youtube.py` &mdash; the other sources.
- `data/corpus.json` &mdash; full text + metadata for every item dated on or after 2026-01-01.
- `index.html` / `app.js` / `styles.css` &mdash; the static front end. MiniSearch via CDN; no build step.
- `build_embeddings.mjs` / `build_topics.mjs` &mdash; plain-language search index and the Trends & themes data.
- `.github/workflows/refresh.yml` &mdash; daily cron that re-runs the scrapers and commits new items.
- `METHODOLOGY.md` &mdash; data sources, classification rules, limitations.

## Running locally

```bash
python3 scrape.py          # writes data/corpus.json
python3 -m http.server 8000   # then open http://localhost:8000
```

## Refreshing the archive

The scraper is idempotent &mdash; re-running it only fetches the bodies of new
articles (it keys off `link` and reuses cached entries). The GitHub Action
runs this daily.
