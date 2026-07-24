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

exec >>"$LOG" 2>&1
echo "===== $(date -u +%Y-%m-%dT%H:%M:%SZ) starting captions run ====="

cd "$REPO" || { echo "FATAL: $REPO is gone."; exit 1; }

# Node and python live in /usr/local/bin, which launchd does not put on PATH.
export PATH="/usr/local/bin:/opt/homebrew/bin:/usr/bin:/bin:/usr/sbin:/sbin"

if [ ! -x "$VENV/bin/python" ]; then
  echo "Creating venv…"
  python3 -m venv "$VENV" || { echo "FATAL: venv creation failed."; exit 1; }
fi
# Cheap on every run, and it keeps yt-dlp current — YouTube breaks extractors
# often enough that a stale yt-dlp is its own silent failure.
"$VENV/bin/pip" install -q --upgrade yt-dlp youtube-transcript-api

git pull --rebase --autostash || { echo "FATAL: pull failed; not scraping."; exit 1; }

"$VENV/bin/python" scrape_youtube.py
scrape_status=$?
if [ $scrape_status -ne 0 ]; then
  echo "FATAL: scrape_youtube.py exited $scrape_status. Corpus left as-is."
  exit $scrape_status
fi

if git diff --quiet data/corpus.json; then
  echo "Corpus unchanged — nothing to publish."
  echo "===== done $(date -u +%Y-%m-%dT%H:%M:%SZ) ====="
  exit 0
fi

echo "Corpus changed; rebuilding search vectors and topics…"
npm install --no-audit --no-fund || { echo "FATAL: npm install failed."; exit 1; }
node build_embeddings.mjs || { echo "FATAL: build_embeddings.mjs failed."; exit 1; }
node build_topics.mjs || { echo "FATAL: build_topics.mjs failed."; exit 1; }

git add data/corpus.json data/embeddings.json data/topics.json
git commit -m "Refresh YouTube captions: $(date -u +%Y-%m-%d)" || {
  echo "Nothing staged after rebuild."; exit 0;
}

# Same 500-on-push flakiness the Actions jobs hit; retry rather than strand the
# commit locally, where nothing would ever pick it up again.
for attempt in 1 2 3; do
  if git push; then
    echo "Pushed. ===== done $(date -u +%Y-%m-%dT%H:%M:%SZ) ====="
    exit 0
  fi
  echo "Push attempt $attempt failed; waiting $((attempt * 15))s."
  sleep $((attempt * 15))
  git pull --rebase --autostash || true
done

echo "FATAL: push failed three times — commit is sitting unpushed in $REPO."
exit 1
