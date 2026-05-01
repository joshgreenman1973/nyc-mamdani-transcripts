# Mayor Mamdani transcript search

Searchable archive of Mayor Zohran Mamdani's on-the-record speeches, press-
conference transcripts, prepared remarks, and statements since he took office
on January 1, 2026.

**Live site:** https://joshgreenman1973.github.io/nyc-mamdani-transcripts/

**Source:** Everything is pulled from
[nyc.gov/mayors-office/news](https://www.nyc.gov/mayors-office/news/). See
[METHODOLOGY.md](METHODOLOGY.md) for what's included, what's excluded, and how
items are classified.

## Files

- `scrape.py` &mdash; Python 3 scraper, stdlib only. Generates `data/corpus.json`.
- `data/corpus.json` &mdash; full text + metadata for every news item dated on or after 2026-01-01.
- `index.html` / `app.js` / `styles.css` &mdash; the static front end. MiniSearch via CDN; no build step.
- `.github/workflows/refresh.yml` &mdash; daily cron that re-runs the scraper and commits new items.
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
