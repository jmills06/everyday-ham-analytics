"""Buzzsprout daily stats collector.

Buzzsprout documents a per-day downloads endpoint (sections/stats.md in
buzzsprout/buzzsprout-api) that returns each episode's downloads for one
date. That gives true daily numbers straight from Buzzsprout, instead of
deriving them from lifetime-total deltas, and it can fill days the snapshot
collector missed.

Each run re-fetches a trailing window (late-arriving downloads can still
change recent days). Set BUZZSPROUT_STATS_FROM=YYYY-MM-DD to backfill from
that date: days already on file are skipped and each run fetches at most
MAX_BACKFILL_DAYS of them (oldest first), so a long backfill is finished
by dispatching the same date again until the log says nothing is left.

NOTE: `date` here is the podcast's local calendar date, as Buzzsprout
defines it, not a UTC date like the rest of data/history.

Writes:
- data/history/buzzsprout_stats_daily.jsonl     (show total per day)
- data/history/buzzsprout_downloads_daily.jsonl (per-episode per day)

Auth: BUZZSPROUT_TOKEN + BUZZSPROUT_PODCAST_ID.
"""

import os
import sys
import time
from datetime import date, timedelta

import requests

from common import HISTORY, ensure_dirs, read_jsonl, require_env, write_jsonl

TIMEOUT = 30
TRAILING_DAYS = 7
# Keeps one run well inside the workflow's 15-minute timeout
MAX_BACKFILL_DAYS = 400
# Documented limit is 60 requests/minute per token
REQUEST_GAP_SEC = 1.1


def fetch_day(token: str, podcast_id: str, day: str) -> list[dict]:
    url = f"https://www.buzzsprout.com/api/{podcast_id}/downloads"
    headers = {
        "Authorization": f"Token token={token}",
        "User-Agent": "everyday-ham-analytics (jmills06@gmail.com)",
    }
    for attempt in range(4):
        r = requests.get(url, headers=headers, params={"date": day}, timeout=TIMEOUT)
        if r.status_code == 429 or r.status_code >= 500:
            time.sleep(5 * 2 ** attempt)
            continue
        r.raise_for_status()
        return r.json()
    r.raise_for_status()
    return []


def span(start: date, end: date) -> list[str]:
    return [(start + timedelta(days=i)).isoformat()
            for i in range((end - start).days + 1)]


def date_range() -> list[str]:
    # End at yesterday (UTC) so a partial day is never recorded as final
    end = date.today() - timedelta(days=1)
    trailing = span(end - timedelta(days=TRAILING_DAYS - 1), end)
    start_env = os.environ.get("BUZZSPROUT_STATS_FROM", "").strip()
    if not start_env:
        return trailing
    start = date.fromisoformat(start_env)
    if start > end:
        print(f"ERROR: BUZZSPROUT_STATS_FROM {start} is after {end}", file=sys.stderr)
        sys.exit(1)
    have = {r["date"] for r in read_jsonl(HISTORY / "buzzsprout_stats_daily.jsonl")}
    missing = [d for d in span(start, end) if d not in have and d not in trailing]
    todo = missing[:MAX_BACKFILL_DAYS]
    left = len(missing) - len(todo)
    print(f"backfill: {len(todo)} missing days this run, {left} left after it"
          + (" (dispatch again with the same date to continue)" if left else ""))
    return sorted(set(todo) | set(trailing))


def replace_days(path, days: set[str], new_rows: list[dict]) -> None:
    """Replace every row for the fetched days, so an episode that dropped out
    of a re-fetched day doesn't leave a stale row behind."""
    rows = [r for r in read_jsonl(path) if r.get("date") not in days]
    rows.extend(new_rows)
    rows.sort(key=lambda r: (r["date"], str(r.get("episode_id", ""))))
    write_jsonl(path, rows)


def main() -> None:
    ensure_dirs()
    token = require_env("BUZZSPROUT_TOKEN")
    podcast_id = require_env("BUZZSPROUT_PODCAST_ID")
    days = date_range()

    # Fetch everything before writing anything: a failure mid-range must
    # leave history untouched
    per_episode, per_day = [], []
    for i, day in enumerate(days):
        if i:
            time.sleep(REQUEST_GAP_SEC)
        batch = fetch_day(token, podcast_id, day)
        rows = [{"date": day, "episode_id": int(b["episode_id"]),
                 "downloads": int(b["total"])} for b in batch]
        per_episode += rows
        per_day.append({"date": day,
                        "downloads": sum(r["downloads"] for r in rows),
                        "episodes_with_downloads": len(rows)})
        print(f"  {day}: {per_day[-1]['downloads']} downloads "
              f"across {len(rows)} episodes")

    fetched = set(days)
    replace_days(HISTORY / "buzzsprout_stats_daily.jsonl", fetched, per_day)
    replace_days(HISTORY / "buzzsprout_downloads_daily.jsonl", fetched, per_episode)
    total = sum(d["downloads"] for d in per_day)
    print(f"buzzsprout stats OK: {total} downloads over {len(days)} days "
          f"({days[0]} to {days[-1]})")


if __name__ == "__main__":
    main()
