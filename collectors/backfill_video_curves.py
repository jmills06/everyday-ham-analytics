"""One-time backfill of per-video launch curves.

The Analytics API can return daily views for any video back to its publish
date, so unlike Buzzsprout, YouTube's launch-curve history is recoverable.
This script queries every video once and writes age-indexed daily views to
data/history/videos/launch_curves.json:

{
  "updated_at": "...",
  "videos": {
    "<video_id>": {
      "published": "YYYY-MM-DD",
      "daily_views": [day0, day1, day2, ...]
    }
  }
}

Safe to re-run: it rebuilds curves from scratch each time.
Run via the backfill.yml workflow (uses repo secrets), or locally with the
four YT_* environment variables set.
"""

import sys
import time
from datetime import datetime, timezone

import requests

from common import (
    HISTORY, LATEST, YT_CHANNEL_ID,
    ensure_dirs, read_json, require_env, utc_now_iso, write_json,
)

API = "https://youtubeanalytics.googleapis.com/v2/reports"
TOKEN_URL = "https://oauth2.googleapis.com/token"
TIMEOUT = 30
PAUSE_SEC = 0.15          # be polite between the ~150 queries


def get_access_token() -> str:
    r = requests.post(TOKEN_URL, data={
        "client_id": require_env("YT_CLIENT_ID"),
        "client_secret": require_env("YT_CLIENT_SECRET"),
        "refresh_token": require_env("YT_REFRESH_TOKEN"),
        "grant_type": "refresh_token",
    }, timeout=TIMEOUT)
    r.raise_for_status()
    return r.json()["access_token"]


def fetch_curve(token: str, video_id: str, published: str) -> list[int]:
    """Daily views from publish date to yesterday, age-indexed with zero fill."""
    pub = datetime.fromisoformat(published.replace("Z", "+00:00")).date()
    today = datetime.now(timezone.utc).date()
    if pub >= today:
        return []
    r = requests.get(API, params={
        "ids": f"channel=={YT_CHANNEL_ID}",
        "startDate": pub.isoformat(),
        "endDate": today.isoformat(),
        "metrics": "views",
        "dimensions": "day",
        "filters": f"video=={video_id}",
        "sort": "day",
    }, headers={"Authorization": f"Bearer {token}"}, timeout=TIMEOUT)
    r.raise_for_status()
    by_date = {row[0]: int(row[1]) for row in (r.json().get("rows") or [])}
    n_days = (today - pub).days
    return [by_date.get(
        (pub + __import__("datetime").timedelta(days=i)).isoformat(), 0)
        for i in range(n_days)]


def main() -> None:
    ensure_dirs()
    yt = read_json(LATEST / "youtube.json")
    if not yt:
        print("ERROR: data/latest/youtube.json missing; run youtube_channel.py first",
              file=sys.stderr)
        sys.exit(1)

    token = get_access_token()
    curves, failed = {}, []
    videos = yt["videos"]
    for i, v in enumerate(videos, 1):
        try:
            daily = fetch_curve(token, v["id"], v["published_at"])
            curves[v["id"]] = {
                "published": v["published_at"][:10],
                "daily_views": daily,
            }
            print(f"[{i}/{len(videos)}] {v['id']}  {sum(daily)} views over "
                  f"{len(daily)} days  {v['title'][:50]}")
        except Exception as exc:
            failed.append(v["id"])
            print(f"[{i}/{len(videos)}] FAILED {v['id']}: {exc}", file=sys.stderr)
        time.sleep(PAUSE_SEC)

    write_json(HISTORY / "videos" / "launch_curves.json", {
        "updated_at": utc_now_iso(),
        "videos": curves,
    })
    print(f"\nbackfill complete: {len(curves)} curves written, {len(failed)} failed")
    if failed:
        print("failed ids:", ", ".join(failed), file=sys.stderr)


if __name__ == "__main__":
    main()
