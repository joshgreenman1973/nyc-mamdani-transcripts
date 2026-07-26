#!/bin/bash
# Fetch YouTube captions for the Mayor's Office channel and push the result.
#
# This runs on Josh's Mac rather than in GitHub Actions because YouTube refuses
# caption requests from datacenter IPs — every attempt from a runner comes back
# IpBlocked. The same requests succeed from a residential connection. The GitHub
# Action still does the nyc.gov scrape twice a day and lists/matches videos with
# YT_CAPTIONS=0; this job fills in the transcripts.
#
# Installed as a launchd agent — see docs/youtube-captions.md.

set -uo pipefail

REPO="/Users/joshgreenman/Experiments/nyc-mamdani-transcripts"
LOG="$HOME/Library/Logs/nyc-mamdani-captions.log"
VENV="$REPO/.venv"
MAX_ATTEMPTS=4

exec >>"$LOG" 2>&1
echo "===== $(date -u +%Y-%m-%dT%H:%M:%SZ) starting captions run ====="

cd "$REPO" || { echo "FATAL: $REPO is gone."; exit 1; }

# Node, python and gh live in /usr/local/bin (~/.local/bin for gh), which
# launchd does not put on PATH.
export PATH="/usr/local/bin:/opt/homebrew/bin:$HOME/.local/bin:/usr/bin:/bin:/usr/sbin:/sbin"

# gh is git's credential helper, and its active account silently flips to
# vitalcity-nyc, which 403s on this repo. Pin it before any push.
if command -v gh >/dev/null; then
  gh auth switch -u joshgreenman1973 >/dev/null 2>&1 \
    || echo "WARN: gh auth switch failed; push may 403 if the active account is wrong."
fi

if [ ! -x "$VENV/bin/python" ]; then
  echo "Creating venv…"
  python3 -m venv "$VENV" || { echo "FATAL: venv creation failed."; exit 1; }
fi
# Cheap on every run, and it keeps yt-dlp current — YouTube breaks extractors
# often enough that a stale yt-dlp is its own silent failure.
"$VENV/bin/pip" install -q --upgrade yt-dlp youtube-transcript-api

# One attempt = reset to whatever origin holds now, scrape captions onto it,
# rebuild, commit, push. If the push loses a race with the twice-daily CI
# refresh, the next attempt resets to the NEW origin and re-derives.
#
# We reset --hard rather than rebase because corpus.json / embeddings.json /
# topics.json are generated: rebasing a local regenerated copy onto CI's
# regenerated copy collides on every line, every time — that is exactly what
# wedged this job into a half-finished rebase on 2026-07-25. Re-scraping on the
# fresh base is the only correct reconciliation anyway, because the scraper
# merges several sources; blindly keeping our copy would drop the nyc.gov items
# CI added while we ran. The scrape is idempotent (skips videos already in the
# corpus), so a re-run only re-fetches what is genuinely still missing.
#
# NB: reset --hard also reverts any uncommitted change to THIS script mid-run.
# Bash has already parsed the loop into memory by then, so the running job is
# unaffected — but edit-then-run in one shot will not test the edit. Commit
# script changes before relying on them.
attempt=1
while [ "$attempt" -le "$MAX_ATTEMPTS" ]; do
  echo "--- attempt $attempt/$MAX_ATTEMPTS"

  if ! git fetch -q origin; then
    echo "attempt $attempt: fetch failed; retrying."
    sleep $((attempt * 15)); attempt=$((attempt + 1)); continue
  fi
  git reset --hard origin/main >/dev/null

  YT_CAPTIONS=1 "$VENV/bin/python" scrape_youtube.py
  scrape_status=$?
  if [ $scrape_status -ne 0 ]; then
    # A non-zero scrape is a real failure (broken listing, or the staleness
    # watchdog firing), not a race. Do not loop on it — surface it.
    echo "FATAL: scrape_youtube.py exited $scrape_status. Nothing committed."
    exit $scrape_status
  fi

  if git diff --quiet data/corpus.json; then
    echo "Corpus unchanged — nothing to publish."
    echo "===== done $(date -u +%Y-%m-%dT%H:%M:%SZ) ====="
    exit 0
  fi

  echo "Corpus changed; rebuilding search vectors and topics…"
  npm install --no-audit --no-fund >/dev/null || { echo "FATAL: npm install failed."; exit 1; }
  node build_embeddings.mjs || { echo "FATAL: build_embeddings.mjs failed."; exit 1; }
  node build_topics.mjs      || { echo "FATAL: build_topics.mjs failed."; exit 1; }

  git add data/corpus.json data/embeddings.json data/topics.json
  git commit -q -m "Refresh YouTube captions: $(date -u +%Y-%m-%d)" || {
    echo "Nothing staged after rebuild."; exit 0;
  }

  if git push 2>&1; then
    echo "Pushed. ===== done $(date -u +%Y-%m-%dT%H:%M:%SZ) ====="
    exit 0
  fi

  echo "attempt $attempt: push failed (GitHub 500 or origin moved); re-deriving."
  sleep $((attempt * 15))
  attempt=$((attempt + 1))
done

echo "FATAL: still could not publish after $MAX_ATTEMPTS attempts."
exit 1
