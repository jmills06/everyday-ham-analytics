# Everyday Ham Analytics

Central data repo for The Everyday Ham podcast and YouTube channel.
Collectors run daily via GitHub Actions, commit JSON snapshots and
append-only history, and GitHub Pages serves the data plus the display
boards to DakBoard.

```
collectors/            Python collectors (run by the workflow)
data/latest/           Board-facing snapshots (overwritten each run)
data/history/          Append-only daily history (JSONL, upserted by date)
data/content/          Video/episode metadata with a "topics" field
data/milestones.json   Server-computed milestone events (72h takeover state)
boards/                Display boards (added in phase 2)
```

## Why history matters

The APIs only tell you *now*. Buzzsprout has no daily-downloads endpoint,
YouTube trend deltas need a stored yesterday, and topic analytics need
per-video launch curves. Every day the collectors run is a row of history
that cannot be reconstructed later.

## Data flow

```
cron-job.org (daily, off-peak odd minute)
  -> POST workflow_dispatch (GitHub API, fine-grained PAT)
    -> collect.yml runs collectors
      -> commit to main (fetch-depth 0 + 5x rebase-retry push)
        -> GitHub Pages serves data/ and boards/
          -> DakBoard fullscreen webpage blocks
```

GitHub's built-in `schedule:` cron is deliberately not used; it is
unreliable at congested times. External trigger only.

## Files and conventions

- All dates/timestamps are **UTC**. History rows key on `date` (YYYY-MM-DD).
- Re-running a collector on the same day **replaces** that day's row
  (no duplicates).
- Analytics/revenue rows are upserted over a trailing 35-day window each
  run because YouTube finalizes revenue 2-3 days late; provisional numbers
  converge to final automatically.
- On fetch failure a collector exits non-zero and touches **nothing**:
  stale data beats no data. Boards flag staleness via `fetched_at`.
- `content/*.json` preserves the `topics` array across runs; tags added by
  hand or by a future Claude classification pass survive collection.

## Secrets (repo Settings > Secrets and variables > Actions)

| Secret | What it is |
|---|---|
| `YT_API_KEY` | Data API v3 key, restricted to that API |
| `YT_CLIENT_ID` | OAuth Desktop client (analytics-collector) |
| `YT_CLIENT_SECRET` | Same client |
| `YT_REFRESH_TOKEN` | Minted via get_token.py flow, account: everydayhampodcast@gmail.com |
| `BUZZSPROUT_TOKEN` | Buzzsprout API token |
| `BUZZSPROUT_PODCAST_ID` | 2438895 |

Credential notes for future maintenance:

- Google Cloud project: `everyday-ham-analytics`. APIs enabled: YouTube
  Data v3, YouTube Analytics, YouTube Reporting.
- The OAuth consent screen **must stay "In production"**. In Testing mode,
  refresh tokens expire after 7 days and the pipeline silently dies.
- If the refresh token is ever revoked, re-mint with the
  `google_auth_oauthlib` local-server flow using scopes
  `yt-analytics.readonly` and `yt-analytics-monetary.readonly`, signing in
  as the channel identity.
- The old milestone-board API key (pre-2026 project) was public in page
  source; it is retired. Delete the old project once nothing depends on it.

## cron-job.org setup

- URL: `https://api.github.com/repos/jmills06/everyday-ham-analytics/actions/workflows/collect.yml/dispatches`
- Method: POST
- Headers:
  - `Authorization: Bearer <fine-grained PAT>`
  - `Accept: application/vnd.github+json`
- Body: `{"ref":"main"}`
- Schedule: once daily, off-peak odd minute (e.g. 06:17 UTC)
- Enable failure notifications: the PAT expires after at most 1 year and
  the failure mode is silent 401s.

Optional second job for fresher board numbers: same call with body
`{"ref":"main","inputs":{"collectors":"youtube"}}` every 30-60 min
(channel totals are the only intraday-visible numbers).

## Running locally

```
pip install -r requirements.txt
set YT_API_KEY=...            (PowerShell: $env:YT_API_KEY="...")
python collectors/youtube_channel.py
```

Each collector prints a one-line OK summary. `compute_milestones.py` needs
at least two days of history before it can detect anything.

## Verification checklist (first week)

- [ ] Manual workflow run succeeds from the Actions tab
- [ ] `data/latest/*.json` updated, `fetched_at` is current
- [ ] Each history file gained exactly one row per day
- [ ] Re-running on the same day replaces (not duplicates) today's rows
- [ ] Revenue rows for recent days change across runs (lag convergence)
- [ ] cron-job.org fires and the run appears in Actions
- [ ] Simulate a milestone: edit yesterday's row below a threshold in a
      scratch branch, run compute_milestones, confirm the event appears
- [ ] After 3-4 clean days: build boards (phase 2)
