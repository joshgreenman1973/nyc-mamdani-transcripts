# Why YouTube captions are fetched locally

## The problem

`scrape_youtube.py` has two jobs: list the videos on the NYC Mayor's Office
channel, and fetch captions for the ones that have no nyc.gov twin. In GitHub
Actions, the second job had never once succeeded.

Every caption request from an Actions runner came back as `IpBlocked` from
`youtube-transcript-api`. The run log always ended the same way:

```
Still rate-limited by YouTube — stopping caption fetches. 14 video(s) left for the next run.
Matched 0 videos to existing items; added 0 new video items; 0 failures.
```

This is not throttling that clears with backoff. YouTube blocks caption and
player requests from datacenter IP ranges, and every GitHub-hosted runner sits in
one. The script's 30-second backoff and 3-day grace period were built for a
transient limit that does not exist here — the block is permanent from that
address. As of 24 July 2026, `youtube_coverage.last_ingest` was `null`: no video
had ever been ingested by the scheduled job.

The listing half was quietly degraded too. `list_videos()` tries yt-dlp's
flat-playlist first and falls back to the channel's Atom feed, which is plain XML
and not bot-gated. In CI the yt-dlp pass also failed, so the fallback carried
every run — and the Atom feed only exposes the 15 most recent uploads. CI saw 15
videos. The channel has 211 since 1 January 2026.

## The fix

Split the work by what each environment can actually reach.

**GitHub Actions** (`.github/workflows/refresh.yml`, twice daily) runs the
nyc.gov scrape and calls `scrape_youtube.py` with `YT_CAPTIONS=0`. It lists and
matches videos, updates `youtube_coverage`, and commits — but never attempts a
caption fetch, so it never goes red for a block it cannot avoid.

**A launchd agent on Josh's Mac** (`scripts/refresh-captions-local.sh`, daily)
runs the same script with captions enabled from a residential connection, where
both yt-dlp and the transcript API work. It rebuilds embeddings and topics, then
commits and pushes.

A captions-off run deliberately does not advance
`youtube_coverage.last_ingest`. It never exercises the part that breaks, so
letting it reset the clock would hide exactly the staleness the watchdog exists
to catch. The 3-day staleness watchdog now only fires on runs that actually tried
to fetch captions — that is, the local ones.

## First local run, 24 July 2026

| | Scheduled Actions job | First local run |
|---|---|---|
| Channel videos listed | 15 | 211 |
| Matched to nyc.gov items | 0 | 167 |
| New video items added | 0 | 39 |
| Caption failures | n/a | 5 |
| Coverage | — | 196/211 |

The 15 still unaccounted are livestreams and shorts with captions genuinely
disabled — `blXWEtO-vH0` ("Talk with the People") and `R_M-vwYHTy8` ("Ramadan
Mubarak") both return `TranscriptsDisabled` rather than a block. These are
tracked by ID in `youtube_coverage.unaccounted` rather than dropped.

## Installing the launchd agent

```bash
cp launchd/com.joshgreenman.mamdani-captions.plist ~/Library/LaunchAgents/
launchctl load ~/Library/LaunchAgents/com.joshgreenman.mamdani-captions.plist
```

It runs at 08:10 local time daily. Logs go to
`~/Library/Logs/nyc-mamdani-captions.log`; every failure path in the script
writes a line beginning `FATAL:` and exits non-zero.

To run it by hand:

```bash
bash scripts/refresh-captions-local.sh
```

## Known limitation

The Mac has to be awake. A missed day is not lossy — the next run picks up
everything still listed in `unaccounted` — but a long sleep means a stale
corpus with nothing going red to say so, since the failure is an absence of runs
rather than a failing one. If that starts to bite, the honest fixes are a
`StartInterval` agent that catches up on wake, or moving the caption fetch to a
box that stays on.
